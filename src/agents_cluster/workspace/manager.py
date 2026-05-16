from __future__ import annotations

from pathlib import Path
from typing import Dict

from agents_cluster.core.paths import WORKTREES_DIR
from agents_cluster.core.time import now_id

from . import git_ops


def prepare_worktree(project: Dict[str, str], run_id: str) -> Dict[str, str]:
    project_path = git_ops.repo_root(Path(project["path"]))
    project_name = project.get("name") or project_path.name
    base_branch = git_ops.current_branch(project_path)
    branch_name = f"agentsCluster/{project_name}/{run_id}"
    worktree_path = WORKTREES_DIR / project_name / run_id

    git_ops.create_worktree(project_path, worktree_path, branch_name)
    return {
        "project_name": project_name,
        "project_path": str(project_path),
        "base_branch": base_branch,
        "branch_name": branch_name,
        "worktree_path": str(worktree_path),
    }
