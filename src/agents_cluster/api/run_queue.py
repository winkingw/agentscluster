from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Dict

from agents_cluster.core import db
from agents_cluster.core.config import load_config
from agents_cluster.core.time import now_iso
from agents_cluster.orchestrator.controller import RunCancelled, execute_run, plan_run
from agents_cluster.core.paths import RUNS_DIR


class RunQueue:
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="agentsCluster")
        self._lock = threading.Lock()
        self._futures: Dict[str, Future] = {}
        self._cancel_events: Dict[str, threading.Event] = {}

    def submit_plan(self, run_id: str) -> None:
        self._submit(run_id, "plan")

    def submit_execute(self, run_id: str) -> None:
        self._submit(run_id, "execute")

    def recover_stale_runs(self) -> int:
        """
        Best-effort recovery for runs left in non-terminal states after a server restart.

        This does NOT enqueue any new model calls. It only normalizes statuses based on
        existing artifacts on disk, so the UI can present a consistent state.
        """
        recovered = 0
        candidates = db.list_runs_by_status(
            ["planning", "running", "cancel_requested", "queued"],
            limit=200,
        )
        for run in candidates:
            run_id = str(run.get("id") or "")
            if not run_id:
                continue
            run_dir = RUNS_DIR / run_id
            plan_path = run_dir / "plan.md"
            task_plan_path = run_dir / "task-plan.json"
            summary_path = run_dir / "summary.md"
            status = str(run.get("status") or "")

            # If a final summary exists, promote to reviewed.
            if summary_path.exists():
                summary_text = ""
                try:
                    summary_text = summary_path.read_text(encoding="utf-8").strip()
                except Exception:
                    summary_text = ""
                db.update_run(run_id, status="reviewed", summary=summary_text or run.get("summary"))
                db.add_event(run_id, now_iso(), "system", "run_recovered", f"recovered from {status}: summary exists")
                recovered += 1
                continue

            # Planning may have finished writing artifacts before the status update landed.
            if status == "planning" and plan_path.exists() and task_plan_path.exists():
                db.update_run(run_id, status="waiting_approval")
                db.add_event(
                    run_id,
                    now_iso(),
                    "system",
                    "run_recovered",
                    f"recovered from {status}: plan artifacts exist",
                )
                recovered += 1
                continue

            # Otherwise, we cannot safely resume without re-running models.
            db.update_run(run_id, status="interrupted", summary=f"interrupted from {status} after server restart")
            db.add_event(run_id, now_iso(), "system", "run_interrupted", f"interrupted from {status} after server restart")
            recovered += 1
        return recovered

    def request_cancel(self, run_id: str) -> None:
        with self._lock:
            event = self._cancel_events.setdefault(run_id, threading.Event())
            event.set()
        run = db.get_run(run_id)
        if not run:
            return
        status = str(run.get("status") or "")
        if status in {"waiting_approval", "planned", "paused", "queued"}:
            db.update_run(run_id, status="cancelled", summary="cancelled by user before execution")
            db.add_event(run_id, now_iso(), "system", "run_cancelled", "cancelled by user before execution")
        elif status not in {"cancelled", "failed", "reviewed", "merged", "discarded"}:
            db.update_run(run_id, status="cancel_requested")
            db.add_event(run_id, now_iso(), "system", "cancel_requested", "cancellation requested")

    def _submit(self, run_id: str, phase: str) -> None:
        with self._lock:
            future = self._futures.get(run_id)
            if future and not future.done():
                raise RuntimeError(f"Run {run_id} already has an active background task")
            event = self._cancel_events.setdefault(run_id, threading.Event())
            # A new submission starts a new phase; clear any old cancellation signal.
            # If the user cancels again, request_cancel() will set it.
            event.clear()
            future = self._executor.submit(self._run_phase, run_id, phase, event)
            self._futures[run_id] = future

    def _run_phase(self, run_id: str, phase: str, cancel_event: threading.Event) -> None:
        db.add_event(run_id, now_iso(), "system", "queue_started", f"{phase} started in background")
        try:
            config = load_config()
            if phase == "plan":
                plan_run(config, run_id, cancel_check=cancel_event.is_set)
            elif phase == "execute":
                execute_run(config, run_id, cancel_check=cancel_event.is_set)
            else:
                raise ValueError(f"Unknown phase: {phase}")
            db.add_event(run_id, now_iso(), "system", "queue_completed", f"{phase} completed in background")
        except RunCancelled:
            pass
        except Exception as exc:
            db.add_event(run_id, now_iso(), "system", "queue_failed", str(exc))
        finally:
            with self._lock:
                self._futures.pop(run_id, None)


RUN_QUEUE = RunQueue()
