from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from agents_cluster.core import db
from agents_cluster.core.config import add_project, load_config, remove_project, save_config
from agents_cluster.core.paths import CONFIG_PATH, RUNS_DIR
from agents_cluster.workspace import git_ops
from agents_cluster.workspace.manager import prepare_worktree


def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc


def main() -> None:
    db.init_db()
    original_config = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None
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
        finally:
            if original_config is not None:
                CONFIG_PATH.write_text(original_config, encoding="utf-8")

    print("smoke ok")


if __name__ == "__main__":
    main()
