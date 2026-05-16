from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from agents_cluster.core import db
from agents_cluster.core.config import add_project, load_config, save_config
from agents_cluster.workspace import git_ops
from agents_cluster.workspace.manager import prepare_worktree


def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc


def main() -> None:
    db.init_db()
    with tempfile.TemporaryDirectory() as tmp:
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

        info = prepare_worktree(project, "run_smoke")
        worktree = Path(info["worktree_path"])
        (worktree / "README.md").write_text("# smoke\n\nchanged\n", encoding="utf-8")
        diff_text = git_ops.diff(worktree)
        assert "changed" in diff_text
        git_ops.remove_worktree(repo, worktree, force=True)

    print("smoke ok")


if __name__ == "__main__":
    main()
