from __future__ import annotations

import threading
from dataclasses import dataclass
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Dict, List, Optional, Set, Tuple

from agents_cluster.core import db
from agents_cluster.core.config import load_config
from agents_cluster.core.time import now_iso
from agents_cluster.orchestrator.controller import RunCancelled, execute_run, plan_run
from agents_cluster.core.paths import RUNS_DIR


@dataclass(frozen=True)
class _PendingTask:
    run_id: str
    phase: str  # "plan" | "execute"
    project_path: str


class RunQueue:
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="agentsCluster")
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._futures: Dict[str, Future] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._project_busy: Set[str] = set()
        self._pending: List[_PendingTask] = []
        self._scheduler = threading.Thread(target=self._scheduler_loop, name="agentsCluster-scheduler", daemon=True)
        self._scheduler.start()

    def submit_plan(self, run_id: str) -> None:
        self._enqueue(run_id, "plan")

    def submit_execute(self, run_id: str) -> None:
        self._enqueue(run_id, "execute")

    def is_run_active(self, run_id: str) -> bool:
        with self._lock:
            future = self._futures.get(run_id)
            return bool(future and not future.done())

    def is_run_pending(self, run_id: str) -> bool:
        with self._lock:
            return any(item.run_id == run_id for item in self._pending)

    def recover_stale_runs(self) -> int:
        """
        Best-effort recovery for runs left in non-terminal states after a server restart.

        This does NOT enqueue any new model calls. It only normalizes statuses based on
        existing artifacts on disk, so the UI can present a consistent state.
        """
        recovered = 0
        candidates = db.list_runs_by_status(["planning", "running", "cancel_requested", "queued"], limit=200)
        candidates = sorted(candidates, key=lambda r: str(r.get("created_at") or ""))
        to_enqueue: List[Tuple[str, str, str]] = []
        for run in candidates:
            run_id = str(run.get("id") or "")
            if not run_id:
                continue
            run_dir = RUNS_DIR / run_id
            plan_path = run_dir / "plan.md"
            task_plan_path = run_dir / "task-plan.json"
            summary_path = run_dir / "summary.md"
            status = str(run.get("status") or "")
            metadata = run.get("metadata", {}) or {}

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

            # If the run was queued, try to re-enqueue its pending phase so it can continue automatically.
            if status == "queued":
                pending_phase = str(metadata.get("pending_phase") or "").strip().lower()
                project_path = str(run.get("project_path") or "")
                if pending_phase in {"plan", "execute"} and project_path:
                    to_enqueue.append((run_id, pending_phase, project_path))
                    recovered += 1
                    continue

            # Otherwise, we cannot safely resume without re-running models.
            db.update_run(run_id, status="interrupted", summary=f"interrupted from {status} after server restart")
            db.add_event(
                run_id,
                now_iso(),
                "system",
                "run_interrupted",
                f"interrupted from {status} after server restart",
            )
            recovered += 1

        if to_enqueue:
            with self._cv:
                for run_id, phase, project_path in to_enqueue:
                    if any(item.run_id == run_id for item in self._pending):
                        continue
                    future = self._futures.get(run_id)
                    if future and not future.done():
                        continue
                    self._pending.append(_PendingTask(run_id=run_id, phase=phase, project_path=project_path))
                    try:
                        db.add_event(
                            run_id,
                            now_iso(),
                            "system",
                            "queue_recovered",
                            f"recovered queued run for phase={phase}",
                        )
                    except Exception:
                        pass
                self._cv.notify_all()
        return recovered

    def request_cancel(self, run_id: str) -> None:
        with self._lock:
            event = self._cancel_events.setdefault(run_id, threading.Event())
            event.set()
            # If the run is still pending (not yet running), drop it from the queue.
            self._pending = [item for item in self._pending if item.run_id != run_id]
            self._cv.notify_all()
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

    def _enqueue(self, run_id: str, phase: str) -> None:
        run = db.get_run(run_id)
        if not run:
            raise KeyError(f"Run not found: {run_id}")
        project_path = str(run.get("project_path") or "")
        if not project_path:
            raise ValueError(f"Run {run_id} has empty project_path")
        with self._lock:
            future = self._futures.get(run_id)
            if future and not future.done():
                raise RuntimeError(f"Run {run_id} already has an active background task")
            event = self._cancel_events.setdefault(run_id, threading.Event())
            # A new submission starts a new phase; clear any old cancellation signal.
            # If the user cancels again, request_cancel() will set it.
            event.clear()
            if any(item.run_id == run_id for item in self._pending):
                raise RuntimeError(f"Run {run_id} is already queued")
            self._pending.append(_PendingTask(run_id=run_id, phase=phase, project_path=project_path))
            self._cv.notify_all()

    def _scheduler_loop(self) -> None:
        while True:
            task: Optional[_PendingTask] = None
            with self._cv:
                # Find the oldest pending task whose project is not busy.
                for idx, item in enumerate(self._pending):
                    if item.project_path in self._project_busy:
                        continue
                    task = self._pending.pop(idx)
                    self._project_busy.add(item.project_path)
                    break
                if not task:
                    self._cv.wait(timeout=1.0)
                    continue

                cancel_event = self._cancel_events.setdefault(task.run_id, threading.Event())
                cancel_event.clear()
                future = self._executor.submit(self._run_phase, task.run_id, task.phase, cancel_event, task.project_path)
                self._futures[task.run_id] = future

    def _run_phase(self, run_id: str, phase: str, cancel_event: threading.Event, project_path: str) -> None:
        run = db.get_run(run_id) or {}
        metadata = run.get("metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.pop("pending_phase", None)
        next_status = "planning" if phase == "plan" else "running"
        db.update_run(run_id, status=next_status, metadata=metadata)
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
                if project_path in self._project_busy:
                    self._project_busy.remove(project_path)
                self._cv.notify_all()


RUN_QUEUE = RunQueue()
