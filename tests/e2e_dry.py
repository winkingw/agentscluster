from __future__ import annotations

import json
from pathlib import Path

from agents_cluster.core.paths import PATCHES_DIR, RUNS_DIR
from agents_cluster.e2e import run_e2e


def main() -> None:
    result = run_e2e(mode="dry", apply="patch", cleanup="discard", keep_repo=False)
    run_id = result["run_id"]

    patch_path = PATCHES_DIR / f"{run_id}.patch"
    assert patch_path.exists(), f"patch not found: {patch_path}"
    patch_text = patch_path.read_text(encoding="utf-8", errors="replace")
    assert "touched by" in patch_text or "README.md" in patch_text

    run_dir = RUNS_DIR / run_id
    assert (run_dir / "plan.md").exists()
    assert (run_dir / "task-plan.json").exists()
    assert (run_dir / "diff.patch").exists()
    assert (run_dir / "summary.md").exists()
    assert (run_dir / "changes.patch").exists()

    # Ensure planning is multi-agent (not master-only).
    task_plan = json.loads((run_dir / "task-plan.json").read_text(encoding="utf-8"))
    assert task_plan.get("planning_mode") == "multi-agent"
    planners = task_plan.get("planning_agents") or []
    assert isinstance(planners, list) and len(planners) >= 2
    planner_outputs = task_plan.get("planner_outputs") or []
    assert isinstance(planner_outputs, list) and len(planner_outputs) >= 2
    for item in planner_outputs:
        artifact = str(item.get("artifact") or "")
        if artifact:
            assert (run_dir / artifact).exists(), f"planner artifact missing: {artifact}"

    # Cleanup artifacts to avoid local growth on repeated runs.
    try:
        patch_path.unlink(missing_ok=True)  # py311+
    except TypeError:
        if patch_path.exists():
            patch_path.unlink()
    if run_dir.exists():
        for child in run_dir.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted([p for p in run_dir.rglob("*") if p.is_dir()], reverse=True):
            try:
                child.rmdir()
            except OSError:
                pass
        try:
            run_dir.rmdir()
        except OSError:
            pass

    print("e2e dry ok")


if __name__ == "__main__":
    main()
