from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from agents_cluster.api.server import create_server
from agents_cluster.api import server as api_server
from agents_cluster.core import db
from agents_cluster.core.paths import CONFIG_EXAMPLE_PATH, CONFIG_PATH, RUNS_DIR
from agents_cluster.core.time import now_iso
from agents_cluster.orchestrator import controller
from agents_cluster.workspace import git_ops
from agents_cluster.workspace.manager import prepare_worktree


def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc


def request_json(url: str, method: str = "GET", payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def request_text(url: str, method: str = "GET", payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")


def request_error(url: str, method: str = "GET", payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body}
        return exc.code, payload


def wait_for_status(base_url: str, run_id: str, expected: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = request_json(f"{base_url}/api/runs/{run_id}")
        if last["run"]["status"] == expected:
            return last
        time.sleep(0.2)
    raise RuntimeError(f"Run {run_id} did not reach status {expected}; last={last}")


def read_sse_until(url: str, target_event: str = "run-event", timeout: float = 10.0):
    result = {}

    def _reader():
        current_event = ""
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line or line.startswith(":") or line.startswith("retry:"):
                        continue
                    if line.startswith("event:"):
                        current_event = line.partition(":")[2].strip()
                        continue
                    if line.startswith("data:"):
                        payload = json.loads(line.partition(":")[2].strip())
                        if current_event == target_event:
                            result["event"] = current_event
                            result["payload"] = payload
                            return
        except Exception as exc:
            result["error"] = repr(exc)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return result, thread


def main() -> None:
    db.init_db()
    original_config = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None
    created_config = False
    if original_config is None and CONFIG_EXAMPLE_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
        created_config = True
    original_env_path = api_server.ENV_PATH
    original_run_agent = controller._run_agent

    try:
        def fake_run_agent(config, agent_name, prompt, cwd, output_dir):
            if agent_name == "master":
                if "final report" in prompt or "final summary" in prompt:
                    return "summary ok"
                # Make the first async planning slow so we can assert project-level queueing deterministically.
                if "exercise async flow" in prompt:
                    time.sleep(1.0)
                return "plan ok"
            if agent_name == "reviewer":
                return "Decision\nAPPROVE\n\nVerification\nok"
            return f"{agent_name} ok"

        controller._run_agent = fake_run_agent
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            run(["git", "init"], repo)
            run(["git", "config", "user.email", "agentsCluster@example.local"], repo)
            run(["git", "config", "user.name", "agentsCluster Smoke"], repo)
            (repo / "README.md").write_text("# api smoke\n", encoding="utf-8")
            run(["git", "add", "README.md"], repo)
            run(["git", "commit", "-m", "init"], repo)

            env_path = Path(tmp) / ".env.api-smoke"
            keep_key = f"API_KEEP_{uuid4().hex[:8]}"
            drop_key = f"API_DROP_{uuid4().hex[:8]}"
            env_path.write_text(f"{keep_key}=1\n{drop_key}=2\n", encoding="utf-8")
            api_server.ENV_PATH = env_path

            server = create_server("127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            health = request_json(f"{base_url}/health")
            assert health["ok"] is True

            root_html = request_text(f"{base_url}/")
            assert "agentsCluster" in root_html

            config_snapshot = request_json(f"{base_url}/api/config")
            assert "settings" in config_snapshot["config"]
            config_echo = request_json(
                f"{base_url}/api/config",
                method="PUT",
                payload={"config": config_snapshot["config"]},
            )
            assert config_echo["config"]["settings"] == config_snapshot["config"]["settings"]

            env_snapshot = request_json(f"{base_url}/api/env")
            assert isinstance(env_snapshot["env"], dict)
            assert env_snapshot["env"][keep_key] == "1"
            assert env_snapshot["env"][drop_key] == "2"
            env_echo = request_json(
                f"{base_url}/api/env",
                method="PUT",
                payload={"env": {keep_key: "3"}},
            )
            assert env_echo["env"] == {keep_key: "3"}
            assert drop_key not in os.environ
            assert drop_key not in env_path.read_text(encoding="utf-8")

            created = request_json(
                f"{base_url}/api/projects",
                method="POST",
                payload={"name": "api-smoke", "path": str(repo)},
            )
            assert created["project"]["name"] == "api-smoke"

            projects = request_json(f"{base_url}/api/projects")
            assert any(project["name"] == "api-smoke" for project in projects["projects"])

            agents = request_json(f"{base_url}/api/agents")
            assert any(agent["name"] == "master" for agent in agents["agents"])

            tools = request_json(f"{base_url}/api/tools")
            assert any(tool["name"] == "aider" for tool in tools["tools"])

            integrations = request_json(f"{base_url}/api/integrations")
            assert any(item["name"] == "langgraph" for item in integrations["integrations"])

            master = request_json(f"{base_url}/api/agents/master")
            assert master["agent"]["runner"]
            assert "OPENAI_API_KEY" in master["agent"]["env_keys"]
            assert "sk-" not in json.dumps(master)

            test = request_json(
                f"{base_url}/api/agents/master/test",
                method="POST",
                payload={"dry_run": True, "cwd": str(repo)},
            )
            assert test["returncode"] == 0
            assert "Dry run only" in test["stdout"]

            run_id = f"run_api_smoke_{uuid4().hex[:6]}"
            info = prepare_worktree(created["project"], run_id)
            worktree = Path(info["worktree_path"])
            try:
                (worktree / "README.md").write_text("# api smoke\n\nchanged\n", encoding="utf-8")
                db.insert_run(
                    {
                        "id": run_id,
                        "created_at": now_iso(),
                        "project_name": info["project_name"],
                        "project_path": info["project_path"],
                        "worktree_path": info["worktree_path"],
                        "branch_name": info["branch_name"],
                        "goal": "api smoke",
                        "status": "reviewed",
                        "metadata": {"base_branch": info["base_branch"]},
                    }
                )
                db.add_event(run_id, now_iso(), "tester", "smoke", "event ok")

                run_detail = request_json(f"{base_url}/api/runs/{run_id}")
                assert run_detail["run"]["id"] == run_id
                assert run_detail["events"][0]["kind"] == "smoke"

                events = request_json(f"{base_url}/api/runs/{run_id}/events")
                assert events["events"][0]["message"] == "event ok"

                diff = request_json(f"{base_url}/api/runs/{run_id}/diff")
                assert "changed" in diff["diff"]

                apply_diff = request_json(
                    f"{base_url}/api/runs/{run_id}/apply",
                    method="POST",
                    payload={"mode": "diff"},
                )
                assert "changed" in apply_diff["diff"]

                patch = request_json(
                    f"{base_url}/api/runs/{run_id}/apply",
                    method="POST",
                    payload={"mode": "patch"},
                )
                assert patch["patch_path"].endswith(f"{run_id}.patch")
            finally:
                if worktree.exists():
                    git_ops.remove_worktree(repo, worktree, force=True)

            created_code, created_run = request_error(
                f"{base_url}/api/runs",
                method="POST",
                payload={"project": "api-smoke", "goal": "exercise async flow"},
            )
            assert created_code == 202, created_run
            async_run_id = created_run["run_id"]
            assert created_run["status"] == "queued"
            assert created_run["phase"] == "plan"

            queued_code, queued_run = request_error(
                f"{base_url}/api/runs",
                method="POST",
                payload={"project": "api-smoke", "goal": "should queue"},
            )
            assert queued_code == 202, queued_run
            queued_plan_run_id = queued_run["run_id"]
            assert queued_run["status"] == "queued"
            assert queued_run["phase"] == "plan"

            time.sleep(0.2)
            queued_detail_early = request_json(f"{base_url}/api/runs/{queued_plan_run_id}")
            assert queued_detail_early["run"]["status"] == "queued"

            waiting = wait_for_status(base_url, async_run_id, "waiting_approval")
            assert waiting["run"]["goal"] == "exercise async flow"
            assert any(event["kind"] == "planning_completed" for event in waiting["events"])

            queued_waiting = wait_for_status(base_url, queued_plan_run_id, "waiting_approval")
            assert queued_waiting["run"]["goal"] == "should queue"
            assert any(event["kind"] == "planning_completed" for event in queued_waiting["events"])

            apply_conflict_code, apply_conflict_body = request_error(
                f"{base_url}/api/runs/{async_run_id}/apply",
                method="POST",
                payload={"mode": "diff"},
            )
            assert apply_conflict_code == 409
            assert "still active" in apply_conflict_body["error"]

            artifacts = request_json(f"{base_url}/api/runs/{async_run_id}/artifacts")
            artifact_names = {item["name"] for item in artifacts["artifacts"]}
            assert "plan.md" in artifact_names
            assert "task-plan.json" in artifact_names

            plan_art = request_json(f"{base_url}/api/runs/{async_run_id}/artifacts/plan.md")
            assert plan_art["type"] == "text"
            assert "plan ok" in plan_art["text"]

            task_plan_art = request_json(f"{base_url}/api/runs/{async_run_id}/artifacts/task-plan.json")
            assert task_plan_art["type"] == "json"
            assert "tasks" in task_plan_art["data"]

            existing_events = request_json(f"{base_url}/api/runs/{async_run_id}/events")
            last_event_id = existing_events["events"][-1]["id"]
            stream_result, stream_thread = read_sse_until(
                f"{base_url}/api/runs/{async_run_id}/events/stream?after_id={last_event_id}&timeout=5"
            )
            time.sleep(0.3)
            db.add_event(async_run_id, now_iso(), "tester", "stream_test", "stream ok", {"source": "api_smoke"})
            stream_thread.join(timeout=6)
            assert stream_result.get("error") is None, stream_result.get("error")
            assert stream_result["event"] == "run-event"
            assert stream_result["payload"]["kind"] == "stream_test"
            assert stream_result["payload"]["metadata"]["source"] == "api_smoke"

            approved = request_json(
                f"{base_url}/api/runs/{async_run_id}/approve-plan",
                method="POST",
                payload={"confirm": True},
            )
            assert approved["status"] == "queued"
            assert approved["phase"] == "execute"

            reviewed = wait_for_status(base_url, async_run_id, "reviewed")
            assert reviewed["run"]["summary"] == "summary ok"
            assert any(event["kind"] == "execution_completed" for event in reviewed["events"])

            db.update_run(async_run_id, status="interrupted", summary="manual interruption for retry test")
            retry_exec = request_json(
                f"{base_url}/api/runs/{async_run_id}/retry-execute",
                method="POST",
                payload={"confirm": True},
            )
            assert retry_exec["status"] == "queued"
            assert retry_exec["phase"] == "execute"
            reviewed_again = wait_for_status(base_url, async_run_id, "reviewed")
            assert reviewed_again["run"]["summary"] == "summary ok"
            assert any(event["kind"] == "retry_execute_requested" for event in reviewed_again["events"])

            cancel_run = request_json(
                f"{base_url}/api/runs",
                method="POST",
                payload={"project": "api-smoke", "goal": "cancel me"},
            )
            cancel_run_id = cancel_run["run_id"]
            wait_for_status(base_url, cancel_run_id, "waiting_approval")
            cancelled = request_json(
                f"{base_url}/api/runs/{cancel_run_id}/cancel",
                method="POST",
                payload={"confirm": True},
            )
            assert cancelled["status"] == "cancelled"
            cancelled_detail = wait_for_status(base_url, cancel_run_id, "cancelled")
            assert any(event["kind"] == "run_cancelled" for event in cancelled_detail["events"])

            retry_plan = request_json(
                f"{base_url}/api/runs/{cancel_run_id}/retry-plan",
                method="POST",
                payload={"confirm": True},
            )
            assert retry_plan["status"] == "queued"
            assert retry_plan["phase"] == "plan"
            retried_plan_detail = wait_for_status(base_url, cancel_run_id, "waiting_approval")
            assert any(event["kind"] == "retry_plan_requested" for event in retried_plan_detail["events"])

            # Ensure the second queued run eventually reaches waiting_approval after the first planning completed.
            wait_for_status(base_url, queued_plan_run_id, "waiting_approval")

            for cleanup_run_id in (async_run_id, cancel_run_id, queued_plan_run_id):
                detail = request_json(f"{base_url}/api/runs/{cleanup_run_id}")
                queued_worktree = Path(detail["run"]["worktree_path"])
                if queued_worktree.exists():
                    git_ops.remove_worktree(repo, queued_worktree, force=True)

            removed = request_json(f"{base_url}/api/projects/api-smoke", method="DELETE")
            assert removed["removed"]["name"] == "api-smoke"

            runs = request_json(f"{base_url}/api/runs?limit=1")
            assert "runs" in runs
    finally:
        if "server" in locals():
            server.shutdown()
            server.server_close()
        controller._run_agent = original_run_agent
        api_server.ENV_PATH = original_env_path
        if original_config is not None:
            CONFIG_PATH.write_text(original_config, encoding="utf-8")
        elif created_config and CONFIG_PATH.exists():
            CONFIG_PATH.unlink()

    print("api smoke ok")


if __name__ == "__main__":
    main()
