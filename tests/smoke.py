from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from agents_cluster.core import db
from agents_cluster.core.env import read_dotenv, write_dotenv
from agents_cluster.core.config import AgentConfig, add_project, load_config, remove_project, save_config
from agents_cluster.core.paths import CONFIG_EXAMPLE_PATH, CONFIG_PATH, RUNS_DIR
from agents_cluster.runners.claude import ClaudeRunner
from agents_cluster.runners.codex import CodexRunner
from agents_cluster.workspace import git_ops
from agents_cluster.workspace.manager import prepare_worktree


def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc


class FakeCompletedProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def assert_claude_runner_defaults(tmp: Path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        return FakeCompletedProcess(stdout="ok")

    agent = AgentConfig(
        name="coder",
        runner="claude",
        model="deepseek-v4-flash",
        role="coder",
        timeout_seconds=30,
        raw={"claude": {"output_format": "text"}},
    )
    output_dir = tmp / "claude_runner"
    with patch("agents_cluster.runners.subprocess_runner.subprocess.run", side_effect=fake_run):
        result = ClaudeRunner(agent, {}).run("prompt", tmp, output_dir)
    assert result.stdout == "ok"
    command = captured["command"]
    assert "--permission-mode" in command
    assert command[command.index("--permission-mode") + 1] == "acceptEdits"


def assert_codex_runner_uses_last_message(tmp: Path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        last_message_path = Path(command[command.index("-o") + 1])
        last_message_path.parent.mkdir(parents=True, exist_ok=True)
        last_message_path.write_text("clean result\n", encoding="utf-8")
        return FakeCompletedProcess(stdout="noisy stdout", stderr="warn only")

    agent = AgentConfig(
        name="master",
        runner="codex",
        model="gpt-5.5",
        role="orchestrator",
        timeout_seconds=30,
        raw={"codex": {"sandbox": "workspace-write", "approval_policy": "never", "ephemeral": True}},
    )
    output_dir = tmp / "codex_runner"
    with patch("agents_cluster.runners.subprocess_runner.subprocess.run", side_effect=fake_run):
        result = CodexRunner(agent, {}).run("prompt", tmp, output_dir)
    assert result.stdout == "clean result"
    assert "-o" in captured["command"]
    assert "noisy stdout" not in result.output_file.read_text(encoding="utf-8")


def main() -> None:
    db.init_db()
    original_config = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None
    created_config = False
    if original_config is None and CONFIG_EXAMPLE_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
        created_config = True
    with tempfile.TemporaryDirectory() as tmp:
        try:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            run(["git", "init"], repo)
            run(["git", "config", "user.email", "agentsCluster@example.local"], repo)
            run(["git", "config", "user.name", "agentsCluster Smoke"], repo)
            (repo / "README.md").write_text("# smoke\n", encoding="utf-8")
            run(["git", "add", "README.md"], repo)
            run(["git", "commit", "-m", "init"], repo)

            config = load_config()
            project = add_project(config, repo, "smoke")
            save_config(config)

            config = load_config()
            removed = remove_project(config, "smoke")
            assert removed["name"] == "smoke"
            save_config(config)

            config = load_config()
            project = add_project(config, repo, "smoke")
            save_config(config)

            run_id = f"run_smoke_{uuid4().hex[:6]}"
            info = prepare_worktree(project, run_id)
            worktree = Path(info["worktree_path"])
            (worktree / "README.md").write_text("# smoke\n\nchanged\n", encoding="utf-8")
            diff_text = git_ops.diff(worktree)
            assert "changed" in diff_text

            run_dir = RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "plan.md").write_text("plan smoke\n", encoding="utf-8")
            (run_dir / "task-plan.json").write_text('{"tasks":[]}\n', encoding="utf-8")
            db.insert_run(
                {
                    "id": run_id,
                    "created_at": "2026-05-19T00:00:00+08:00",
                    "project_name": info["project_name"],
                    "project_path": info["project_path"],
                    "worktree_path": info["worktree_path"],
                    "branch_name": info["branch_name"],
                    "goal": "cli smoke",
                    "status": "waiting_approval",
                    "metadata": {"base_branch": info["base_branch"]},
                }
            )

            cli_artifacts = run([sys.executable, "-m", "agents_cluster.cli", "runs", "artifacts", run_id])
            assert "plan.md" in cli_artifacts.stdout
            cli_plan = run(
                [sys.executable, "-m", "agents_cluster.cli", "runs", "artifacts", run_id, "--name", "plan.md"]
            )
            assert "plan smoke" in cli_plan.stdout
            cli_show = run([sys.executable, "-m", "agents_cluster.cli", "runs", "show", run_id])
            assert "Status:   waiting_approval" in cli_show.stdout
            git_ops.remove_worktree(repo, worktree, force=True)
            try:
                worktree.parent.rmdir()
            except OSError:
                pass

            env_path = Path(tmp) / "smoke.env"
            keep_key = f"AGENTS_CLUSTER_KEEP_{uuid4().hex[:8]}"
            drop_key = f"AGENTS_CLUSTER_DROP_{uuid4().hex[:8]}"
            original_keep = os.environ.get(keep_key)
            original_drop = os.environ.get(drop_key)
            try:
                env_path.write_text(f"{keep_key}=1\n{drop_key}=old\n", encoding="utf-8")
                os.environ[drop_key] = "old"
                write_dotenv({keep_key: "2"}, env_path, apply_to_process=True)
                rendered = env_path.read_text(encoding="utf-8")
                assert f"{keep_key}=2" in rendered
                assert drop_key not in read_dotenv(env_path)
                assert os.environ[keep_key] == "2"
                assert drop_key not in os.environ
            finally:
                if original_keep is None:
                    os.environ.pop(keep_key, None)
                else:
                    os.environ[keep_key] = original_keep
                if original_drop is None:
                    os.environ.pop(drop_key, None)
                else:
                    os.environ[drop_key] = original_drop

            assert_claude_runner_defaults(Path(tmp))
            assert_codex_runner_uses_last_message(Path(tmp))
        finally:
            if original_config is not None:
                CONFIG_PATH.write_text(original_config, encoding="utf-8")
            elif created_config and CONFIG_PATH.exists():
                CONFIG_PATH.unlink()

    print("smoke ok")


if __name__ == "__main__":
    main()
