from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

from agents_cluster.core import db
from agents_cluster.core.paths import CONFIG_PATH, RUNS_DIR
from agents_cluster.core.time import now_iso
from agents_cluster.orchestrator.controller import apply_run, create_run, execute_run, plan_run


def run_e2e(
    *,
    mode: str = "dry",
    apply: str = "patch",
    cleanup: str = "discard",
    keep_repo: bool = False,
) -> Dict[str, str]:
    """
    End-to-end validation entrypoint.

    - dry: no real model call, uses fake runner config.
    - real: uses the user's configured runners/models (costs money).
    """

    if mode not in ("dry", "real"):
        raise ValueError(f"Unsupported e2e mode: {mode}")
    if apply not in ("none", "diff", "patch", "merge", "discard"):
        raise ValueError(f"Unsupported apply mode: {apply}")
    if cleanup not in ("none", "discard"):
        raise ValueError(f"Unsupported cleanup mode: {cleanup}")

    db.init_db()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        repo = tmp_dir / "e2e_repo"
        repo.mkdir(parents=True, exist_ok=True)
        _init_repo(repo)

        config = _e2e_config(mode)
        project = {"name": "e2e", "path": str(repo)}
        goal = f"agentsCluster e2e ({mode}) @ {now_iso()}"

        run_record = create_run(config, project, goal, workers=["architect", "coder", "tester"])
        run_id = str(run_record["id"])

        plan_run(config, run_id)
        execute_run(config, run_id)

        if apply != "none":
            apply_run(run_id, mode=apply)
        if cleanup == "discard":
            # Ensure worktrees/branches don't accumulate during repeated dry E2E runs.
            # We only discard if the run hasn't already been merged/discarded.
            try:
                apply_run(run_id, mode="discard")
            except Exception:
                pass

        result = {"ok": "true", "mode": mode, "apply": apply, "cleanup": cleanup, "run_id": run_id, "repo": str(repo)}
        if keep_repo:
            # Persist repo for debugging: copy to runs/<run_id>/e2e_repo_snapshot
            snapshot = RUNS_DIR / run_id / "e2e_repo_snapshot"
            try:
                if snapshot.exists():
                    shutil.rmtree(snapshot)
                shutil.copytree(repo, snapshot, dirs_exist_ok=True)
                result["snapshot"] = str(snapshot)
            except Exception:
                pass
        return result


def _e2e_config(mode: str) -> Dict:
    if mode == "real":
        # Use the user's real config file.
        from agents_cluster.core.config import load_config

        return load_config(CONFIG_PATH)

    # Dry mode: synthetic config with fake runners.
    def agent(name: str, role: str) -> Dict:
        return {
            "runner": "fake",
            "model": "fake",
            "role": role,
            "timeout_seconds": 60,
            "fake": {"files_to_touch": ["README.md"]},
        }

    return {
        "settings": {
            "orchestrator": "langgraph",
            "integration_strategy": "adapter",
            "default_timeout_seconds": 60,
            "max_rework_rounds": 0,
        },
        "agents": {
            "master": agent("master", "orchestrator"),
            "reviewer": agent("reviewer", "reviewer"),
            "architect": agent("architect", "architect"),
            "coder": agent("coder", "coder"),
            "tester": agent("tester", "tester"),
        },
        "projects": [],
    }


def _init_repo(repo: Path) -> None:
    def run(cmd, cwd: Optional[Path] = None) -> None:
        proc = subprocess.run(cmd, cwd=str(cwd or repo), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())

    run(["git", "init"], repo)
    run(["git", "config", "user.email", os.environ.get("AGENTSCLUSTER_E2E_EMAIL", "e2e@example.local")], repo)
    run(["git", "config", "user.name", os.environ.get("AGENTSCLUSTER_E2E_NAME", "agentsCluster E2E")], repo)
    (repo / "README.md").write_text("# e2e\n\ninit\n", encoding="utf-8")
    run(["git", "add", "README.md"], repo)
    run(["git", "commit", "-m", "init"], repo)
