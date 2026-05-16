from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional


class GitError(RuntimeError):
    pass


def run_git(project_path: Path, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(project_path), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise GitError(proc.stderr.strip() or proc.stdout.strip())
    return proc


def repo_root(project_path: Path) -> Path:
    proc = run_git(project_path, ["rev-parse", "--show-toplevel"])
    return Path(proc.stdout.strip()).resolve()


def current_branch(project_path: Path) -> str:
    proc = run_git(project_path, ["branch", "--show-current"])
    branch = proc.stdout.strip()
    return branch or "HEAD"


def is_dirty(project_path: Path) -> bool:
    proc = run_git(project_path, ["status", "--porcelain"])
    return bool(proc.stdout.strip())


def create_worktree(project_path: Path, worktree_path: Path, branch_name: str) -> None:
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    run_git(project_path, ["worktree", "add", "-b", branch_name, str(worktree_path)])


def remove_worktree(project_path: Path, worktree_path: Path, force: bool = False) -> None:
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree_path))
    proc = run_git(project_path, args, check=False)
    if proc.returncode != 0 and worktree_path.exists() and force:
        shutil.rmtree(worktree_path)
    elif proc.returncode != 0:
        raise GitError(proc.stderr.strip() or proc.stdout.strip())


def diff(worktree_path: Path, base_ref: str = "HEAD") -> str:
    proc = run_git(worktree_path, ["diff", base_ref])
    return proc.stdout


def status(worktree_path: Path) -> str:
    proc = run_git(worktree_path, ["status", "--short"])
    return proc.stdout


def write_patch(worktree_path: Path, patch_path: Path, base_ref: str = "HEAD") -> Path:
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(diff(worktree_path, base_ref), encoding="utf-8")
    return patch_path


def merge_branch(project_path: Path, branch_name: str, no_ff: bool = True) -> str:
    args = ["merge"]
    if no_ff:
        args.append("--no-ff")
    args.append(branch_name)
    proc = run_git(project_path, args)
    return proc.stdout + proc.stderr


def checkout_branch(project_path: Path, branch: Optional[str]) -> None:
    if branch and branch != "HEAD":
        run_git(project_path, ["checkout", branch])
