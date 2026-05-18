from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from agents_cluster.api.server import AgentsClusterHandler
from agents_cluster.core import db
from agents_cluster.core.paths import CONFIG_PATH
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


def wait_for_status(base_url: str, run_id: str, expected: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = request_json(f"{base_url}/api/runs/{run_id}")
        if last["run"]["status"] == expected:
            return last
        time.sleep(0.2)
    raise RuntimeError(f"Run {run_id} did not reach status {expected}; last={last}")


def main() -> None:
    db.init_db()
    original_config = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None
    original_run_agent = controller._run_agent
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentsClusterHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        def fake_run_agent(config, agent_name, prompt, cwd, output_dir):
            if agent_name == "master":
                if "final report" in prompt or "final summary" in prompt:
                    return "summary ok"
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

            health = request_json(f"{base_url}/health")
            assert health["ok"] is True

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

            created_run = request_json(
                f"{base_url}/api/runs",
                method="POST",
                payload={"project": "api-smoke", "goal": "exercise async flow"},
            )
            async_run_id = created_run["run_id"]
            assert created_run["status"] == "planning"

            waiting = wait_for_status(base_url, async_run_id, "waiting_approval")
            assert waiting["run"]["goal"] == "exercise async flow"
            assert any(event["kind"] == "planning_completed" for event in waiting["events"])

            approved = request_json(
                f"{base_url}/api/runs/{async_run_id}/approve-plan",
                method="POST",
                payload={"confirm": True},
            )
            assert approved["status"] == "running"

            reviewed = wait_for_status(base_url, async_run_id, "reviewed")
            assert reviewed["run"]["summary"] == "summary ok"
            assert any(event["kind"] == "execution_completed" for event in reviewed["events"])

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

            for queued_run_id in (async_run_id, cancel_run_id):
                detail = request_json(f"{base_url}/api/runs/{queued_run_id}")
                queued_worktree = Path(detail["run"]["worktree_path"])
                if queued_worktree.exists():
                    git_ops.remove_worktree(repo, queued_worktree, force=True)

            removed = request_json(f"{base_url}/api/projects/api-smoke", method="DELETE")
            assert removed["removed"]["name"] == "api-smoke"

            runs = request_json(f"{base_url}/api/runs?limit=1")
            assert "runs" in runs
    finally:
        server.shutdown()
        server.server_close()
        controller._run_agent = original_run_agent
        if original_config is not None:
            CONFIG_PATH.write_text(original_config, encoding="utf-8")

    print("api smoke ok")


if __name__ == "__main__":
    main()
