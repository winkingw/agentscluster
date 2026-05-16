from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from agents_cluster.core import db
from agents_cluster.core.config import get_agent
from agents_cluster.core.paths import PATCHES_DIR, RUNS_DIR
from agents_cluster.core.time import now_id, now_iso
from agents_cluster.runners.factory import create_runner
from agents_cluster.workspace import git_ops
from agents_cluster.workspace.manager import prepare_worktree

from .prompts import agent_capability_hint, master_plan_prompt, master_summary_prompt, review_prompt, worker_prompt


DEFAULT_WORKERS = ["architect", "coder", "tester"]


def run_task(
    config: Dict,
    project: Dict[str, str],
    goal: str,
    yes: bool = False,
    workers: Optional[List[str]] = None,
    max_rework_rounds: Optional[int] = None,
) -> Dict:
    db.init_db()
    run_id = f"run_{now_id()}_{uuid4().hex[:6]}"
    worktree_info = prepare_worktree(project, run_id)
    run_dir = RUNS_DIR / run_id
    outputs_dir = run_dir / "agent_outputs"
    run_dir.mkdir(parents=True, exist_ok=True)

    run_record = {
        "id": run_id,
        "created_at": now_iso(),
        "project_name": worktree_info["project_name"],
        "project_path": worktree_info["project_path"],
        "worktree_path": worktree_info["worktree_path"],
        "branch_name": worktree_info["branch_name"],
        "goal": goal,
        "status": "planning",
        "metadata": {"base_branch": worktree_info["base_branch"]},
    }
    db.insert_run(run_record)

    worktree_path = Path(worktree_info["worktree_path"])
    max_rework_rounds = _max_rework_rounds(config, max_rework_rounds)

    print(f"Run: {run_id}")
    print(f"Worktree: {worktree_path}")
    print(f"Branch: {worktree_info['branch_name']}")

    try:
        plan = _run_agent(
            config,
            "master",
            master_plan_prompt(worktree_path, goal, _capability_hint(config, "master")),
            worktree_path,
            outputs_dir,
        )
        (run_dir / "plan.md").write_text(plan, encoding="utf-8")
        db.update_run(run_id, status="planned")

        print("\nMaster plan saved.")
        if not yes:
            print("\n--- Plan preview ---")
            print(_preview(plan, 2500))
            answer = input("\nStart worker execution? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                db.update_run(run_id, status="paused")
                return {"id": run_id, "status": "paused", "run_dir": str(run_dir)}

        db.update_run(run_id, status="running")
        worker_names = workers or DEFAULT_WORKERS
        worker_log_parts: List[str] = []
        previous_output = ""
        for worker_name in worker_names:
            print(f"\nRunning worker: {worker_name}")
            output = _run_agent(
                config,
                worker_name,
                worker_prompt(
                    worker_name,
                    worktree_path,
                    goal,
                    plan,
                    previous_output,
                    _capability_hint(config, worker_name),
                ),
                worktree_path,
                outputs_dir,
            )
            worker_log_parts.append(f"## {worker_name}\n\n{output}")
            previous_output = output[-6000:]

        worker_log = "\n\n".join(worker_log_parts)
        (run_dir / "worker-log.md").write_text(worker_log, encoding="utf-8")

        status_text = git_ops.status(worktree_path)
        diff_text = git_ops.diff(worktree_path)
        (run_dir / "status.txt").write_text(status_text, encoding="utf-8")
        (run_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

        review = ""
        for review_round in range(max_rework_rounds + 1):
            print("\nRunning reviewer.")
            review = _run_agent(
                config,
                "reviewer",
                review_prompt(
                    worktree_path,
                    goal,
                    plan,
                    _cap(diff_text),
                    status_text,
                    _capability_hint(config, "reviewer"),
                ),
                worktree_path,
                outputs_dir / f"review_round_{review_round}",
            )
            review_name = "review.md" if review_round == 0 else f"review-round-{review_round}.md"
            (run_dir / review_name).write_text(review, encoding="utf-8")

            if not _review_requests_changes(review) or review_round >= max_rework_rounds:
                break

            print(f"\nReviewer requested changes; running rework round {review_round + 1}.")
            rework_output = _run_agent(
                config,
                "coder",
                worker_prompt(
                    "coder",
                    worktree_path,
                    goal,
                    plan,
                    f"Reviewer requested changes:\n{review}",
                    _capability_hint(config, "coder"),
                ),
                worktree_path,
                outputs_dir / f"rework_round_{review_round + 1}",
            )
            worker_log_parts.append(f"## coder rework {review_round + 1}\n\n{rework_output}")

            if "tester" in config.get("agents", {}):
                tester_output = _run_agent(
                    config,
                    "tester",
                    worker_prompt(
                        "tester",
                        worktree_path,
                        goal,
                        plan,
                        f"Rework was applied after reviewer feedback:\n{review}",
                        _capability_hint(config, "tester"),
                    ),
                    worktree_path,
                    outputs_dir / f"rework_round_{review_round + 1}_tester",
                )
                worker_log_parts.append(f"## tester rework {review_round + 1}\n\n{tester_output}")

            worker_log = "\n\n".join(worker_log_parts)
            (run_dir / "worker-log.md").write_text(worker_log, encoding="utf-8")
            status_text = git_ops.status(worktree_path)
            diff_text = git_ops.diff(worktree_path)
            (run_dir / "status.txt").write_text(status_text, encoding="utf-8")
            (run_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

        print("\nRunning master final summary.")
        summary = _run_agent(
            config,
            "master",
            master_summary_prompt(
                worktree_path,
                goal,
                plan,
                _cap(worker_log),
                review,
                _cap(diff_text),
                status_text,
                _capability_hint(config, "master"),
            ),
            worktree_path,
            outputs_dir / "final",
        )
        (run_dir / "summary.md").write_text(summary, encoding="utf-8")
        db.update_run(run_id, status="reviewed", summary=summary)
    except Exception as exc:
        (run_dir / "failure.txt").write_text(str(exc), encoding="utf-8")
        db.update_run(run_id, status="failed", summary=str(exc))
        print(f"\nRun failed: {exc}")
        print(f"Run directory: {run_dir}")
        raise

    print("\n--- Final summary ---")
    print(_preview(summary, 5000))
    print(f"\nNext: agentsCluster apply {run_id}")

    return {"id": run_id, "status": "reviewed", "run_dir": str(run_dir)}


def _run_agent(config: Dict, agent_name: str, prompt: str, cwd: Path, output_dir: Path) -> str:
    agent_config = get_agent(config, agent_name)
    runner = create_runner(agent_config)
    result = runner.run(prompt, cwd, output_dir)
    db.add_event(
        run_id=_run_id_from_output_dir(output_dir),
        created_at=now_iso(),
        agent=agent_name,
        kind="agent_result",
        message=f"returncode={result.returncode}, output={result.output_file}",
        metadata={"command": result.command, "cwd": str(cwd)},
    )
    if not result.ok:
        raise RuntimeError(
            f"Agent {agent_name} failed with code {result.returncode}. "
            f"See {result.output_file}\n{result.stderr[-2000:]}"
        )
    return result.stdout.strip()


def _capability_hint(config: Dict, agent_name: str) -> str:
    try:
        return agent_capability_hint(get_agent(config, agent_name))
    except Exception:
        return "Preferred skills/MCP: none configured."


def _max_rework_rounds(config: Dict, override: Optional[int]) -> int:
    if override is not None:
        return max(0, override)
    settings = config.get("settings", {}) or {}
    try:
        return max(0, int(settings.get("max_rework_rounds", 1)))
    except (TypeError, ValueError):
        return 1


def _review_requests_changes(review: str) -> bool:
    upper = review.upper()
    if "REQUEST_CHANGES" in upper:
        return True
    if "DECISION: APPROVE" in upper or "\nAPPROVE" in upper:
        return False
    lowered = review.lower()
    return any(
        token in lowered
        for token in (
            "needs changes",
            "request changes",
            "\u4e0d\u901a\u8fc7",
            "\u9700\u8981\u4fee\u6539",
        )
    )


def _run_id_from_output_dir(output_dir: Path) -> str:
    for part in output_dir.parts:
        if part.startswith("run_"):
            return part
    return "unknown"


def _cap(text: str, limit: int = 60000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[truncated]\n"


def _preview(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


def apply_run(run_id: str, mode: Optional[str] = None) -> None:
    run = db.get_run(run_id)
    if not run:
        raise KeyError(f"Run not found: {run_id}")

    project_path = Path(run["project_path"])
    worktree_path = Path(run["worktree_path"])
    branch_name = run["branch_name"]

    if not mode:
        print("Choose how to handle this run:")
        print("1. merge  - git merge the worktree branch into the original project")
        print("2. diff   - print git diff")
        print("3. patch  - write a patch file")
        print("4. discard - remove the worktree")
        choice = input("Selection [diff]: ").strip().lower() or "diff"
        mode = {"1": "merge", "2": "diff", "3": "patch", "4": "discard"}.get(choice, choice)

    if mode == "diff":
        print(git_ops.diff(worktree_path))
        return

    if mode == "patch":
        patch_path = PATCHES_DIR / f"{run_id}.patch"
        git_ops.write_patch(worktree_path, patch_path)
        print(f"Patch written: {patch_path}")
        return

    if mode == "merge":
        output = git_ops.merge_branch(project_path, branch_name)
        db.update_run(run_id, status="merged")
        print(output)
        print("Merged into original project.")
        return

    if mode == "discard":
        git_ops.remove_worktree(project_path, worktree_path, force=True)
        db.update_run(run_id, status="discarded")
        print("Worktree removed.")
        return

    raise ValueError(f"Unknown apply mode: {mode}")
