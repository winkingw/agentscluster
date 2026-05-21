from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional
from uuid import uuid4

from agents_cluster.core import db
from agents_cluster.core.config import get_agent
from agents_cluster.core.paths import PATCHES_DIR, RUNS_DIR
from agents_cluster.core.time import now_id, now_iso
from agents_cluster.runners.factory import create_runner
from agents_cluster.workspace import git_ops
from agents_cluster.workspace.manager import prepare_worktree

from .prompts import agent_capability_hint, master_plan_prompt, master_summary_prompt, review_prompt, worker_prompt
from .task_protocol import build_task_plan, write_agent_result, write_task_plan
from .langgraph_controller import execute_with_langgraph, plan_with_langgraph


DEFAULT_WORKERS = ["architect", "coder", "tester"]


class RunCancelled(RuntimeError):
    pass


def create_run(
    config: Dict,
    project: Dict[str, str],
    goal: str,
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
        "metadata": {
            "base_branch": worktree_info["base_branch"],
            "workers": workers or DEFAULT_WORKERS,
            "max_rework_rounds": _max_rework_rounds(config, max_rework_rounds),
            "orchestrator": _orchestrator_name(config),
        },
    }
    db.insert_run(run_record)
    db.add_event(run_id, now_iso(), "system", "run_created", "run created", run_record["metadata"])
    return run_record


def run_task(
    config: Dict,
    project: Dict[str, str],
    goal: str,
    yes: bool = False,
    workers: Optional[List[str]] = None,
    max_rework_rounds: Optional[int] = None,
) -> Dict:
    run_record = create_run(
        config,
        project,
        goal,
        workers=workers,
        max_rework_rounds=max_rework_rounds,
    )
    run_id = run_record["id"]
    worktree_path = Path(run_record["worktree_path"])

    print(f"Run: {run_id}")
    print(f"Worktree: {worktree_path}")
    print(f"Branch: {run_record['branch_name']}")

    try:
        planning = plan_run(config, run_id)
        plan = planning["plan"]

        print("\nMaster plan saved.")
        if not yes:
            print("\n--- Plan preview ---")
            print(_preview(plan, 2500))
            answer = input("\nStart worker execution? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                return {"id": run_id, "status": "waiting_approval", "run_dir": str(_run_dir(run_id))}

        result = execute_run(config, run_id)
    except Exception:
        print(f"Run directory: {_run_dir(run_id)}")
        raise

    print("\n--- Final summary ---")
    print(_preview(result["summary"], 5000))
    print(f"\nNext: agentsCluster apply {run_id}")

    return {"id": run_id, "status": "reviewed", "run_dir": str(_run_dir(run_id))}


def plan_run(
    config: Dict,
    run_id: str,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict:
    run = _require_run(run_id)
    run_dir = _run_dir(run_id)
    outputs_dir = _outputs_dir(run_id)
    worktree_path = Path(run["worktree_path"])
    goal = str(run["goal"])
    metadata = run.get("metadata", {}) or {}
    worker_names = _worker_names(metadata)
    orchestrator = str(metadata.get("orchestrator") or _orchestrator_name(config))

    try:
        _ensure_not_cancelled(run_id, cancel_check)
        db.update_run(run_id, status="planning")
        db.add_event(run_id, now_iso(), "system", "planning_started", "planning started")
        if orchestrator == "langgraph":
            def plan_agent(plan_goal: str, plan_worktree: Path) -> str:
                _ensure_not_cancelled(run_id, cancel_check)
                return _run_agent(
                    config,
                    "master",
                    master_plan_prompt(plan_worktree, plan_goal, _capability_hint(config, "master")),
                    plan_worktree,
                    outputs_dir,
                )

            planning_state = plan_with_langgraph(goal, worktree_path, worker_names, plan_agent)
            plan = str(planning_state["plan"])
            task_plan = planning_state["task_plan"]
        else:
            if orchestrator != "builtin":
                print(f"Configured orchestrator '{orchestrator}' is not active yet; using builtin flow.")
            plan = _run_agent(
                config,
                "master",
                master_plan_prompt(worktree_path, goal, _capability_hint(config, "master")),
                worktree_path,
                outputs_dir,
            )
            task_plan = build_task_plan(goal, plan, worker_names)

        (run_dir / "plan.md").write_text(plan, encoding="utf-8")
        write_task_plan(run_dir / "task-plan.json", task_plan)
        db.update_run(run_id, status="waiting_approval")
        db.add_event(run_id, now_iso(), "master", "planning_completed", "plan ready for approval")
        return {"id": run_id, "status": "waiting_approval", "plan": plan, "task_plan": task_plan}
    except RunCancelled as exc:
        _mark_cancelled(run_id, str(exc))
        raise
    except Exception as exc:
        _write_failure(run_id, exc)
        raise


def execute_run(
    config: Dict,
    run_id: str,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict:
    run = _require_run(run_id)
    run_dir = _run_dir(run_id)
    outputs_dir = _outputs_dir(run_id)
    worktree_path = Path(run["worktree_path"])
    goal = str(run["goal"])
    metadata = run.get("metadata", {}) or {}
    max_rework_rounds = int(metadata.get("max_rework_rounds", _max_rework_rounds(config, None)))
    plan_path = run_dir / "plan.md"
    task_plan_path = run_dir / "task-plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan file not found for run {run_id}: {plan_path}")
    if not task_plan_path.exists():
        raise FileNotFoundError(f"Task plan file not found for run {run_id}: {task_plan_path}")
    plan = plan_path.read_text(encoding="utf-8")
    task_plan = _load_task_plan(task_plan_path)
    worker_names = [str(task.get("agent")) for task in task_plan.get("tasks", []) if str(task.get("agent", "")).strip()]
    orchestrator = str(metadata.get("orchestrator") or _orchestrator_name(config))

    try:
        _ensure_not_cancelled(run_id, cancel_check)
        db.update_run(run_id, status="running")
        db.add_event(run_id, now_iso(), "system", "execution_started", "worker execution started")
        if orchestrator == "langgraph":
            result = _execute_run_with_langgraph(
                config=config,
                run_id=run_id,
                run_dir=run_dir,
                outputs_dir=outputs_dir,
                worktree_path=worktree_path,
                goal=goal,
                plan=plan,
                task_plan=task_plan,
                max_rework_rounds=max_rework_rounds,
                cancel_check=cancel_check,
            )
            return result

        worker_log_parts: List[str] = []
        previous_output = ""
        for index, worker_name in enumerate(worker_names):
            _ensure_not_cancelled(run_id, cancel_check)
            task_id = task_plan["tasks"][index]["id"] if index < len(task_plan["tasks"]) else ""
            print(f"\nRunning worker: {worker_name}")
            db.add_event(run_id, now_iso(), worker_name, "task_started", f"started {task_id}", {"task_id": task_id})
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
            write_agent_result(outputs_dir, worker_name, output, "completed", task_id=task_id)
            db.add_event(run_id, now_iso(), worker_name, "task_completed", f"completed {task_id}", {"task_id": task_id})
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
            _ensure_not_cancelled(run_id, cancel_check)
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
            write_agent_result(
                outputs_dir / f"review_round_{review_round}",
                "reviewer",
                review,
                "request_changes" if _review_requests_changes(review) else "approved",
            )

            if not _review_requests_changes(review) or review_round >= max_rework_rounds:
                break

            _ensure_not_cancelled(run_id, cancel_check)
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
            write_agent_result(
                outputs_dir / f"rework_round_{review_round + 1}",
                "coder",
                rework_output,
                "completed",
                task_id=f"rework_{review_round + 1}",
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
                write_agent_result(
                    outputs_dir / f"rework_round_{review_round + 1}_tester",
                    "tester",
                    tester_output,
                    "completed",
                    task_id=f"rework_{review_round + 1}_tester",
                )
                worker_log_parts.append(f"## tester rework {review_round + 1}\n\n{tester_output}")

            worker_log = "\n\n".join(worker_log_parts)
            (run_dir / "worker-log.md").write_text(worker_log, encoding="utf-8")
            status_text = git_ops.status(worktree_path)
            diff_text = git_ops.diff(worktree_path)
            (run_dir / "status.txt").write_text(status_text, encoding="utf-8")
            (run_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

        _ensure_not_cancelled(run_id, cancel_check)
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
        write_agent_result(outputs_dir / "final", "master", summary, "completed")
        db.update_run(run_id, status="reviewed", summary=summary)
        db.add_event(run_id, now_iso(), "master", "execution_completed", "run reviewed")
        return {"id": run_id, "status": "reviewed", "summary": summary, "run_dir": str(run_dir)}
    except RunCancelled as exc:
        _mark_cancelled(run_id, str(exc))
        raise
    except Exception as exc:
        _write_failure(run_id, exc)
        raise


def _execute_run_with_langgraph(
    *,
    config: Dict,
    run_id: str,
    run_dir: Path,
    outputs_dir: Path,
    worktree_path: Path,
    goal: str,
    plan: str,
    task_plan: Dict,
    max_rework_rounds: int,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict:
    tasks = task_plan.get("tasks", []) if isinstance(task_plan, dict) else []
    include_tester_rework = "tester" in config.get("agents", {})

    def run_worker(agent_name: str, task_id: str, previous_output: str) -> str:
        _ensure_not_cancelled(run_id, cancel_check)
        print(f"\nRunning worker: {agent_name}")
        db.add_event(run_id, now_iso(), agent_name, "task_started", f"started {task_id}", {"task_id": task_id})
        output_dir = outputs_dir / "workers" / (task_id or agent_name)
        output = _run_agent(
            config,
            agent_name,
            worker_prompt(
                agent_name,
                worktree_path,
                goal,
                plan,
                previous_output,
                _capability_hint(config, agent_name),
            ),
            worktree_path,
            output_dir,
        )
        write_agent_result(output_dir, agent_name, output, "completed", task_id=task_id)
        db.add_event(run_id, now_iso(), agent_name, "task_completed", f"completed {task_id}", {"task_id": task_id})
        return output

    def run_reviewer(review_round: int, diff_text: str, status_text: str) -> str:
        _ensure_not_cancelled(run_id, cancel_check)
        print("\nRunning reviewer.")
        output = _run_agent(
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
            outputs_dir / "review" / f"round_{review_round}",
        )
        write_agent_result(
            outputs_dir / "review" / f"round_{review_round}",
            "reviewer",
            output,
            "request_changes" if _review_requests_changes(output) else "approved",
        )
        return output

    def run_rework(review_round: int, review: str) -> str:
        _ensure_not_cancelled(run_id, cancel_check)
        print(f"\nReviewer requested changes; running rework round {review_round}.")
        output = _run_agent(
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
            outputs_dir / "rework" / f"round_{review_round}",
        )
        write_agent_result(
            outputs_dir / "rework" / f"round_{review_round}",
            "coder",
            output,
            "completed",
            task_id=f"rework_{review_round}",
        )
        return output

    def run_tester_rework(review_round: int, review: str) -> Optional[str]:
        if not include_tester_rework:
            return None
        _ensure_not_cancelled(run_id, cancel_check)
        output = _run_agent(
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
            outputs_dir / "rework" / f"round_{review_round}_tester",
        )
        write_agent_result(
            outputs_dir / "rework" / f"round_{review_round}_tester",
            "tester",
            output,
            "completed",
            task_id=f"rework_{review_round}_tester",
        )
        return output

    def summarize(worker_log: str, review: str, diff_text: str, status_text: str) -> str:
        _ensure_not_cancelled(run_id, cancel_check)
        print("\nRunning master final summary.")
        return _run_agent(
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

    def refresh_repo_state() -> tuple[str, str]:
        return git_ops.status(worktree_path), git_ops.diff(worktree_path)

    result = execute_with_langgraph(
        goal=goal,
        plan=plan,
        worktree_path=worktree_path,
        task_plan=task_plan,
        max_rework_rounds=max_rework_rounds,
        include_tester_rework=include_tester_rework,
        run_worker=run_worker,
        run_reviewer=run_reviewer,
        run_rework=run_rework,
        run_tester_rework=run_tester_rework,
        summarize=summarize,
        refresh_repo_state=refresh_repo_state,
        review_requests_changes=_review_requests_changes,
    )

    worker_log = "\n\n".join(result.get("worker_log_parts", []) or [])
    review = str(result.get("review") or "")
    summary = str(result.get("summary") or "")
    status_text = str(result.get("status_text") or "")
    diff_text = str(result.get("diff_text") or "")
    review_round = int(result.get("review_round") or 0)

    if worker_log:
        (run_dir / "worker-log.md").write_text(worker_log, encoding="utf-8")
    if review:
        review_name = "review.md" if review_round <= 0 else f"review-round-{review_round}.md"
        (run_dir / review_name).write_text(review, encoding="utf-8")
    (run_dir / "status.txt").write_text(status_text, encoding="utf-8")
    (run_dir / "diff.patch").write_text(diff_text, encoding="utf-8")
    if summary:
        (run_dir / "summary.md").write_text(summary, encoding="utf-8")
        write_agent_result(outputs_dir / "final", "master", summary, "completed")

    db.update_run(run_id, status="reviewed", summary=summary)
    db.add_event(run_id, now_iso(), "master", "execution_completed", "run reviewed")
    return {"id": run_id, "status": "reviewed", "summary": summary, "run_dir": str(run_dir)}


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


def _orchestrator_name(config: Dict) -> str:
    settings = config.get("settings", {}) or {}
    orchestrator = settings.get("orchestrator", "langgraph")
    return str(orchestrator).strip().lower() or "langgraph"


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


def _run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def _outputs_dir(run_id: str) -> Path:
    return _run_dir(run_id) / "agent_outputs"


def _require_run(run_id: str) -> Dict:
    run = db.get_run(run_id)
    if not run:
        raise KeyError(f"Run not found: {run_id}")
    return run


def _load_task_plan(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _worker_names(metadata: Dict) -> List[str]:
    raw = metadata.get("workers") or DEFAULT_WORKERS
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    return DEFAULT_WORKERS


def _ensure_not_cancelled(run_id: str, cancel_check: Optional[Callable[[], bool]]) -> None:
    run = db.get_run(run_id)
    if run and run.get("status") == "cancel_requested":
        raise RunCancelled(f"Run {run_id} was cancelled")
    if cancel_check and cancel_check():
        raise RunCancelled(f"Run {run_id} was cancelled")


def _write_failure(run_id: str, exc: Exception) -> None:
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "failure.txt").write_text(str(exc), encoding="utf-8")
    db.update_run(run_id, status="failed", summary=str(exc))
    db.add_event(run_id, now_iso(), "system", "run_failed", str(exc))


def _mark_cancelled(run_id: str, reason: str) -> None:
    db.update_run(run_id, status="cancelled", summary=reason)
    db.add_event(run_id, now_iso(), "system", "run_cancelled", reason)


def apply_run(run_id: str, mode: Optional[str] = None) -> None:
    run = db.get_run(run_id)
    if not run:
        raise KeyError(f"Run not found: {run_id}")

    project_path = Path(run["project_path"])
    worktree_path = Path(run["worktree_path"])
    branch_name = run["branch_name"]
    metadata = run.get("metadata", {}) or {}
    base_branch = str(metadata.get("base_branch") or "")

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
        # Also store the patch inside the run directory so it can be served as an artifact.
        try:
            run_dir = _run_dir(run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "changes.patch").write_text(patch_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        except Exception:
            pass
        print(f"Patch written: {patch_path}")
        return

    if mode == "merge":
        # Merge is intentionally conservative: we only merge into the original
        # repo worktree when it is clean and on the expected base branch.
        if base_branch:
            current = git_ops.current_branch(project_path)
            if current != base_branch:
                raise ValueError(
                    f"Refusing to merge: project is on branch '{current}', expected '{base_branch}'. "
                    "Checkout the expected base branch and ensure the repo is clean, or use --mode patch."
                )
        if git_ops.is_dirty(project_path):
            raise ValueError(
                "Refusing to merge: original project worktree has uncommitted changes. "
                "Commit/stash them first, or use --mode patch."
            )
        output = git_ops.merge_branch(project_path, branch_name)
        db.update_run(run_id, status="merged")
        # Best-effort cleanup after a successful merge.
        try:
            git_ops.remove_worktree(project_path, worktree_path, force=True)
        except Exception:
            pass
        try:
            git_ops.delete_branch(project_path, branch_name, force=False)
        except Exception:
            pass
        print(output)
        print("Merged into original project.")
        return

    if mode == "discard":
        git_ops.remove_worktree(project_path, worktree_path, force=True)
        db.update_run(run_id, status="discarded")
        # Best-effort delete the branch after discarding the worktree.
        try:
            git_ops.delete_branch(project_path, branch_name, force=True)
        except Exception:
            pass
        print("Worktree removed.")
        return

    raise ValueError(f"Unknown apply mode: {mode}")
