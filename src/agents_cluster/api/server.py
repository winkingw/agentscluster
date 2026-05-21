from __future__ import annotations

import mimetypes
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from agents_cluster.core import db
from agents_cluster.core.config import add_project, find_project, get_agent, list_projects, load_config, remove_project, save_config
from agents_cluster.core.doctor import collect_doctor_checks
from agents_cluster.core.env import read_dotenv, write_dotenv
from agents_cluster.core.integrations import list_integrations
from agents_cluster.core.paths import ENV_PATH, PATCHES_DIR, RUNS_DIR
from agents_cluster.core.paths import UI_DIR, UI_DIST_DIR
from agents_cluster.core.time import now_iso
from agents_cluster.orchestrator.agent_test import test_agent
from agents_cluster.orchestrator.controller import create_run
from agents_cluster.workspace import git_ops
from .run_queue import RUN_QUEUE


TERMINAL_RUN_STATUSES = {"reviewed", "failed", "cancelled", "merged", "discarded", "interrupted"}
ACTIVE_RUN_STATUSES = {"queued", "planning", "planned", "paused", "waiting_approval", "running", "cancel_requested"}
RUN_ARTIFACT_MAX_BYTES = 2_000_000


class AgentsClusterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Tuple[str, int]) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError)):
            return
        super().handle_error(request, client_address)


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    db.init_db()
    _ensure_ui_dist()
    recovered = RUN_QUEUE.recover_stale_runs()
    server = AgentsClusterHTTPServer((host, port), AgentsClusterHandler)
    server.agentscluster_recovered = recovered  # type: ignore[attr-defined]
    return server


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = create_server(host, port)
    print(f"agentsCluster API listening on http://{host}:{port}")
    recovered = getattr(server, "agentscluster_recovered", 0)
    if recovered:
        print(f"Recovered {recovered} stale run(s) on startup.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAPI server stopped.")
    finally:
        server.server_close()


class AgentsClusterHandler(BaseHTTPRequestHandler):
    server_version = "agentsCluster/0.1"

    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        route, query = self._route()
        if route == "/health":
            self._send_json({"ok": True, "service": "agentsCluster"})
            return
        if route == "/api/config":
            self._send_json({"config": load_config()})
            return
        if route == "/api/env":
            self._send_json({"env": read_dotenv(ENV_PATH)})
            return
        if route == "/api/doctor":
            checks = collect_doctor_checks()
            failed = [check.name for check in checks if not check.ok]
            self._send_json(
                {
                    "checks": [
                        {"name": check.name, "ok": check.ok, "detail": check.detail, "hint": check.hint}
                        for check in checks
                    ],
                    "summary": {
                        "total": len(checks),
                        "failed": len(failed),
                        "passed": len(checks) - len(failed),
                    },
                }
            )
            return
        if route == "/api/integrations":
            self._send_json(
                {
                    "integrations": [
                        {
                            "name": status.name,
                            "installed": status.installed,
                            "detail": status.detail,
                            "install_hint": status.install_hint,
                            "use_for": status.use_for,
                        }
                        for status in list_integrations()
                    ]
                }
            )
            return
        if route == "/api/projects":
            config = load_config()
            self._send_json({"projects": list_projects(config)})
            return
        if route == "/api/agents":
            config = load_config()
            self._send_json({"agents": _agent_summaries(config)})
            return
        if route.startswith("/api/agents/"):
            config = load_config()
            agent_name = unquote(route.removeprefix("/api/agents/"))
            agents = {agent["name"]: agent for agent in _agent_summaries(config)}
            agent = agents.get(agent_name)
            if not agent:
                self._send_error(HTTPStatus.NOT_FOUND, f"Agent not found: {agent_name}")
                return
            self._send_json({"agent": agent})
            return
        if route == "/api/runs":
            limit = _int_query(query, "limit", 20)
            self._send_json({"runs": db.list_runs(limit=limit)})
            return
        if route.startswith("/api/runs/"):
            run_id, action = _run_route(route)
            run = db.get_run(run_id)
            if not run:
                self._send_error(HTTPStatus.NOT_FOUND, f"Run not found: {run_id}")
                return
            if not action:
                self._send_json({"run": run, "events": db.list_events(run_id), "artifacts": _list_run_artifacts(run_id)})
                return
            if action == "events/stream":
                self._handle_event_stream(run_id, query, run=run)
                return
            if action == "events":
                after_id = _int_query(query, "after_id", 0, minimum=0)
                limit = _int_query(query, "limit", 500, minimum=1, maximum=2000)
                self._send_json({"run_id": run_id, "events": db.list_events(run_id, after_id=after_id, limit=limit)})
                return
            if action == "artifacts":
                self._handle_artifacts_list(run_id)
                return
            if action.startswith("artifacts/"):
                rel = action.removeprefix("artifacts/").strip("/")
                self._handle_artifact_get(run_id, rel)
                return
            if action == "diff":
                self._send_json({"run_id": run_id, "diff": git_ops.diff(Path(run["worktree_path"]))})
                return
            if action:
                self._send_error(HTTPStatus.NOT_FOUND, f"Unknown run action: {action}")
                return
        if self._handle_frontend(route):
            return
        self._send_error(HTTPStatus.NOT_FOUND, f"Unknown endpoint: {route}")

    def do_POST(self) -> None:
        route, _query = self._route()
        if route == "/api/projects":
            try:
                body = self._read_json()
            except ValueError:
                return
            path = body.get("path")
            if not path:
                self._send_error(HTTPStatus.BAD_REQUEST, "Field 'path' is required")
                return
            config = load_config()
            project = add_project(config, Path(str(path)), body.get("name"))
            save_config(config)
            self._send_json({"project": project}, HTTPStatus.CREATED)
            return
        if route == "/api/config":
            self._handle_update_config()
            return
        if route == "/api/env":
            self._handle_update_env()
            return
        if route == "/api/runs":
            self._handle_create_run()
            return
        if route.startswith("/api/agents/") and route.endswith("/test"):
            agent_name = unquote(route.removeprefix("/api/agents/").removesuffix("/test").strip("/"))
            self._handle_agent_test(agent_name)
            return
        if route.startswith("/api/runs/") and route.endswith("/approve-plan"):
            run_id, action = _run_route(route)
            if action != "approve-plan":
                self._send_error(HTTPStatus.NOT_FOUND, f"Unknown run action: {action}")
                return
            self._handle_approve_plan(run_id)
            return
        if route.startswith("/api/runs/") and route.endswith("/retry-plan"):
            run_id, action = _run_route(route)
            if action != "retry-plan":
                self._send_error(HTTPStatus.NOT_FOUND, f"Unknown run action: {action}")
                return
            self._handle_retry_plan(run_id)
            return
        if route.startswith("/api/runs/") and route.endswith("/retry-execute"):
            run_id, action = _run_route(route)
            if action != "retry-execute":
                self._send_error(HTTPStatus.NOT_FOUND, f"Unknown run action: {action}")
                return
            self._handle_retry_execute(run_id)
            return
        if route.startswith("/api/runs/") and route.endswith("/resume"):
            run_id, action = _run_route(route)
            if action != "resume":
                self._send_error(HTTPStatus.NOT_FOUND, f"Unknown run action: {action}")
                return
            self._handle_resume_run(run_id)
            return
        if route.startswith("/api/runs/") and route.endswith("/cancel"):
            run_id, action = _run_route(route)
            if action != "cancel":
                self._send_error(HTTPStatus.NOT_FOUND, f"Unknown run action: {action}")
                return
            self._handle_cancel_run(run_id)
            return
        if route.startswith("/api/runs/") and route.endswith("/apply"):
            run_id, action = _run_route(route)
            if action != "apply":
                self._send_error(HTTPStatus.NOT_FOUND, f"Unknown run action: {action}")
                return
            self._handle_apply(run_id)
            return
        self._send_error(HTTPStatus.NOT_FOUND, f"Unknown endpoint: {route}")

    def do_PUT(self) -> None:
        route, _query = self._route()
        if route == "/api/config":
            self._handle_update_config()
            return
        if route == "/api/env":
            self._handle_update_env()
            return
        self._send_error(HTTPStatus.NOT_FOUND, f"Unknown endpoint: {route}")

    def do_DELETE(self) -> None:
        route, _query = self._route()
        if route.startswith("/api/projects/"):
            selector = unquote(route.removeprefix("/api/projects/"))
            config = load_config()
            try:
                project = remove_project(config, selector)
            except KeyError as exc:
                self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            save_config(config)
            self._send_json({"removed": project})
            return
        self._send_error(HTTPStatus.NOT_FOUND, f"Unknown endpoint: {route}")

    def log_message(self, format: str, *args: Any) -> None:
        print("%s - %s" % (self.address_string(), format % args))

    def _route(self) -> Tuple[str, Dict[str, Any]]:
        parsed = urlparse(self.path)
        return parsed.path.rstrip("/") or "/", parse_qs(parsed.query)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            raise
        if not isinstance(data, dict):
            self._send_error(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
            raise ValueError("JSON body must be an object")
        return data

    def _send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_headers(self, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _write_sse_event(self, event: str, payload: Dict[str, Any]) -> None:
        body = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)

    def _handle_frontend(self, route: str) -> bool:
        if route.startswith("/api/") or route == "/health":
            return False
        frontend_root = UI_DIST_DIR if (UI_DIST_DIR / "index.html").exists() else UI_DIR
        target = frontend_root / "index.html" if route in {"/", "/index.html"} else (frontend_root / route.lstrip("/"))
        try:
            resolved = target.resolve()
            ui_root = frontend_root.resolve()
        except Exception:
            resolved = target
            ui_root = frontend_root
        if ui_root not in resolved.parents and resolved != ui_root:
            self._send_error(HTTPStatus.BAD_REQUEST, "Invalid frontend path")
            return True
        if not resolved.exists() or not resolved.is_file():
            if "." not in Path(route).name:
                index_path = frontend_root / "index.html"
                if index_path.exists():
                    self._send_file(index_path)
                    return True
            self._send_error(HTTPStatus.NOT_FOUND, f"Frontend asset not found: {route}")
            return True
        self._send_file(resolved)
        return True

    def _send_file(self, path: Path) -> None:
        data = path.read_bytes()
        mime, _encoding = mimetypes.guess_type(str(path))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _handle_agent_test(self, agent_name: str) -> None:
        try:
            body = self._read_json()
            config = load_config()
            dry_run = bool(body.get("dry_run", True))
            if not dry_run and body.get("confirm") is not True:
                self._send_error(HTTPStatus.BAD_REQUEST, "Non-dry-run agent tests require confirm=true")
                return
            cwd = Path(str(body.get("cwd") or Path.cwd()))
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                returncode = test_agent(
                    config,
                    agent_name,
                    cwd=cwd,
                    prompt=body.get("prompt"),
                    dry_run=dry_run,
                )
            self._send_json(
                {
                    "agent": agent_name,
                    "dry_run": dry_run,
                    "returncode": returncode,
                    "stdout": stdout.getvalue(),
                    "stderr": stderr.getvalue(),
                }
            )
        except KeyError as exc:
            self._send_error(HTTPStatus.NOT_FOUND, str(exc))
        except ValueError:
            return
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_update_config(self) -> None:
        try:
            body = self._read_json()
        except ValueError:
            return
        config = body.get("config", body)
        if not isinstance(config, dict):
            self._send_error(HTTPStatus.BAD_REQUEST, "Field 'config' must be an object")
            return
        config.setdefault("settings", {})
        config.setdefault("agents", {})
        config.setdefault("projects", [])
        try:
            save_config(config)
            self._send_json({"config": config})
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_update_env(self) -> None:
        try:
            body = self._read_json()
        except ValueError:
            return
        env = body.get("env", body)
        if not isinstance(env, dict):
            self._send_error(HTTPStatus.BAD_REQUEST, "Field 'env' must be an object")
            return
        normalized = {str(key): "" if value is None else str(value) for key, value in env.items() if str(key).strip()}
        try:
            write_dotenv(normalized, ENV_PATH, apply_to_process=True)
            self._send_json({"env": read_dotenv(ENV_PATH)})
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_create_run(self) -> None:
        try:
            body = self._read_json()
        except ValueError:
            return
        selector = str(body.get("project") or "").strip()
        goal = str(body.get("goal") or "").strip()
        if not selector:
            self._send_error(HTTPStatus.BAD_REQUEST, "Field 'project' is required")
            return
        if not goal:
            self._send_error(HTTPStatus.BAD_REQUEST, "Field 'goal' is required")
            return

        config = load_config()
        try:
            project = find_project(config, selector)
        except KeyError as exc:
            self._send_error(HTTPStatus.NOT_FOUND, str(exc))
            return

        workers = body.get("workers")
        if workers is not None and not isinstance(workers, list):
            self._send_error(HTTPStatus.BAD_REQUEST, "Field 'workers' must be an array when provided")
            return
        worker_names = [str(item).strip() for item in workers or [] if str(item).strip()] or None
        max_rework_rounds = body.get("max_rework_rounds")
        if max_rework_rounds is not None and not isinstance(max_rework_rounds, int):
            self._send_error(HTTPStatus.BAD_REQUEST, "Field 'max_rework_rounds' must be an integer when provided")
            return

        try:
            run = create_run(
                config,
                project,
                goal,
                workers=worker_names,
                max_rework_rounds=max_rework_rounds,
            )
            _mark_run_queued(run["id"], "plan", clear_summary=False)
            try:
                db.add_event(run["id"], now_iso(), "system", "queue_enqueued", "enqueued: plan")
            except Exception:
                pass
            RUN_QUEUE.submit_plan(run["id"])
            self._send_json({"run_id": run["id"], "status": "queued", "phase": "plan"}, HTTPStatus.ACCEPTED)
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_approve_plan(self, run_id: str) -> None:
        try:
            body = self._read_json()
        except ValueError:
            return
        if body.get("confirm") is not True:
            self._send_error(HTTPStatus.BAD_REQUEST, "approve-plan requires confirm=true")
            return
        run = db.get_run(run_id)
        if not run:
            self._send_error(HTTPStatus.NOT_FOUND, f"Run not found: {run_id}")
            return
        if run["status"] not in {"waiting_approval", "planned", "paused"}:
            self._send_error(HTTPStatus.CONFLICT, f"Run {run_id} is not waiting for approval")
            return
        try:
            _mark_run_queued(run_id, "execute", clear_summary=False)
            try:
                db.add_event(run_id, now_iso(), "system", "queue_enqueued", "enqueued: execute")
            except Exception:
                pass
            RUN_QUEUE.submit_execute(run_id)
            self._send_json({"run_id": run_id, "status": "queued", "phase": "execute"}, HTTPStatus.ACCEPTED)
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_retry_plan(self, run_id: str) -> None:
        try:
            body = self._read_json()
        except ValueError:
            return
        if body.get("confirm") is not True:
            self._send_error(HTTPStatus.BAD_REQUEST, "retry-plan requires confirm=true")
            return
        run = db.get_run(run_id)
        if not run:
            self._send_error(HTTPStatus.NOT_FOUND, f"Run not found: {run_id}")
            return
        worktree_path = Path(str(run.get("worktree_path") or ""))
        if not worktree_path.exists():
            self._send_error(HTTPStatus.CONFLICT, f"Run {run_id} worktree not found: {worktree_path}")
            return
        if run.get("status") in {"merged", "discarded"}:
            self._send_error(HTTPStatus.CONFLICT, f"Run {run_id} is already finalized: {run.get('status')}")
            return
        try:
            _mark_run_queued(run_id, "plan", clear_summary=True)
            db.add_event(run_id, now_iso(), "system", "retry_plan_requested", "retry plan requested")
            db.add_event(run_id, now_iso(), "system", "queue_enqueued", "enqueued: plan")
        except Exception:
            # fallback: do not fail retry on event write issues
            pass
        try:
            RUN_QUEUE.submit_plan(run_id)
            self._send_json({"run_id": run_id, "status": "queued", "phase": "plan"}, HTTPStatus.ACCEPTED)
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_retry_execute(self, run_id: str) -> None:
        try:
            body = self._read_json()
        except ValueError:
            return
        if body.get("confirm") is not True:
            self._send_error(HTTPStatus.BAD_REQUEST, "retry-execute requires confirm=true")
            return
        run = db.get_run(run_id)
        if not run:
            self._send_error(HTTPStatus.NOT_FOUND, f"Run not found: {run_id}")
            return
        if run.get("status") in {"merged", "discarded"}:
            self._send_error(HTTPStatus.CONFLICT, f"Run {run_id} is already finalized: {run.get('status')}")
            return
        run_dir = RUNS_DIR / run_id
        plan_path = run_dir / "plan.md"
        task_plan_path = run_dir / "task-plan.json"
        if not plan_path.exists() or not task_plan_path.exists():
            self._send_error(HTTPStatus.CONFLICT, f"Run {run_id} is missing plan artifacts; retry-plan first")
            return
        worktree_path = Path(str(run.get("worktree_path") or ""))
        if not worktree_path.exists():
            self._send_error(HTTPStatus.CONFLICT, f"Run {run_id} worktree not found: {worktree_path}")
            return
        try:
            _mark_run_queued(run_id, "execute", clear_summary=False)
            db.add_event(run_id, now_iso(), "system", "retry_execute_requested", "retry execute requested")
            db.add_event(run_id, now_iso(), "system", "queue_enqueued", "enqueued: execute")
        except Exception:
            pass
        try:
            RUN_QUEUE.submit_execute(run_id)
            self._send_json({"run_id": run_id, "status": "queued", "phase": "execute"}, HTTPStatus.ACCEPTED)
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_resume_run(self, run_id: str) -> None:
        try:
            body = self._read_json()
        except ValueError:
            return
        if body.get("confirm") is not True:
            self._send_error(HTTPStatus.BAD_REQUEST, "resume requires confirm=true")
            return
        run = db.get_run(run_id)
        if not run:
            self._send_error(HTTPStatus.NOT_FOUND, f"Run not found: {run_id}")
            return
        if run.get("status") in {"merged", "discarded"}:
            self._send_error(HTTPStatus.CONFLICT, f"Run {run_id} is already finalized: {run.get('status')}")
            return

        run_dir = RUNS_DIR / run_id
        summary_path = run_dir / "summary.md"
        plan_path = run_dir / "plan.md"
        task_plan_path = run_dir / "task-plan.json"
        worktree_path = Path(str(run.get("worktree_path") or ""))
        if not worktree_path.exists():
            self._send_error(HTTPStatus.CONFLICT, f"Run {run_id} worktree not found: {worktree_path}")
            return
        if summary_path.exists():
            self._send_json({"run_id": run_id, "status": run.get("status") or "reviewed", "mode": "noop"})
            return

        if plan_path.exists() and task_plan_path.exists():
            try:
                _mark_run_queued(run_id, "execute", clear_summary=False)
                db.add_event(run_id, now_iso(), "system", "resume_requested", "resume requested: execute")
                db.add_event(run_id, now_iso(), "system", "queue_enqueued", "enqueued: execute")
            except Exception:
                pass
            try:
                RUN_QUEUE.submit_execute(run_id)
                self._send_json({"run_id": run_id, "status": "queued", "phase": "execute", "mode": "execute"}, HTTPStatus.ACCEPTED)
                return
            except Exception as exc:
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

        try:
            _mark_run_queued(run_id, "plan", clear_summary=True)
            db.add_event(run_id, now_iso(), "system", "resume_requested", "resume requested: plan")
            db.add_event(run_id, now_iso(), "system", "queue_enqueued", "enqueued: plan")
        except Exception:
            pass
        try:
            RUN_QUEUE.submit_plan(run_id)
            self._send_json({"run_id": run_id, "status": "queued", "phase": "plan", "mode": "plan"}, HTTPStatus.ACCEPTED)
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_cancel_run(self, run_id: str) -> None:
        try:
            body = self._read_json()
        except ValueError:
            return
        if body.get("confirm") is not True:
            self._send_error(HTTPStatus.BAD_REQUEST, "cancel requires confirm=true")
            return
        run = db.get_run(run_id)
        if not run:
            self._send_error(HTTPStatus.NOT_FOUND, f"Run not found: {run_id}")
            return
        try:
            RUN_QUEUE.request_cancel(run_id)
            updated = db.get_run(run_id) or run
            self._send_json({"run_id": run_id, "status": updated["status"]})
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_artifacts_list(self, run_id: str) -> None:
        run_dir = RUNS_DIR / run_id
        if not run_dir.exists():
            self._send_error(HTTPStatus.NOT_FOUND, f"Run directory not found: {run_dir}")
            return
        self._send_json({"run_id": run_id, "artifacts": _list_run_artifacts(run_id)})

    def _handle_artifact_get(self, run_id: str, rel: str) -> None:
        if not rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
            self._send_error(HTTPStatus.BAD_REQUEST, "Invalid artifact path")
            return
        run_dir = RUNS_DIR / run_id
        if not run_dir.exists():
            self._send_error(HTTPStatus.NOT_FOUND, f"Run directory not found: {run_dir}")
            return
        target = (run_dir / rel).resolve()
        try:
            run_root = run_dir.resolve()
        except Exception:
            run_root = run_dir
        if run_root not in target.parents and target != run_root:
            self._send_error(HTTPStatus.BAD_REQUEST, "Artifact path escapes run directory")
            return
        if not target.exists() or not target.is_file():
            self._send_error(HTTPStatus.NOT_FOUND, f"Artifact not found: {rel}")
            return
        size = target.stat().st_size
        if size > RUN_ARTIFACT_MAX_BYTES:
            self._send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"Artifact too large: {size} bytes")
            return
        # For JSON, return parsed form so the frontend doesn't need to re-parse.
        if target.suffix.lower() == ".json":
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
            except Exception as exc:
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Invalid JSON artifact: {exc}")
                return
            self._send_json({"run_id": run_id, "name": rel, "type": "json", "data": data})
            return
        text = target.read_text(encoding="utf-8", errors="replace")
        self._send_json({"run_id": run_id, "name": rel, "type": "text", "text": text})

    def _handle_apply(self, run_id: str) -> None:
        try:
            body = self._read_json()
        except ValueError:
            return
        run = db.get_run(run_id)
        if not run:
            self._send_error(HTTPStatus.NOT_FOUND, f"Run not found: {run_id}")
            return

        mode = str(body.get("mode") or "diff").strip().lower()
        if mode not in {"diff", "patch", "merge", "discard"}:
            self._send_error(HTTPStatus.BAD_REQUEST, f"Unknown apply mode: {mode}")
            return
        if mode in {"merge", "discard"} and body.get("confirm") is not True:
            self._send_error(HTTPStatus.BAD_REQUEST, f"{mode} requires confirm=true")
            return

        project_path = Path(run["project_path"])
        worktree_path = Path(run["worktree_path"])
        branch_name = run["branch_name"]

        try:
            if RUN_QUEUE.is_run_active(run_id) or str(run.get("status") or "") in ACTIVE_RUN_STATUSES:
                self._send_error(HTTPStatus.CONFLICT, f"Run {run_id} is still active; cancel or wait before apply")
                return
            if mode == "diff":
                self._send_json({"run_id": run_id, "mode": mode, "diff": git_ops.diff(worktree_path)})
                return
            if mode == "patch":
                patch_path = PATCHES_DIR / f"{run_id}.patch"
                git_ops.write_patch(worktree_path, patch_path)
                self._send_json({"run_id": run_id, "mode": mode, "patch_path": str(patch_path)})
                return
            if mode == "merge":
                metadata = run.get("metadata", {}) or {}
                base_branch = str(metadata.get("base_branch") or "")
                if base_branch:
                    current = git_ops.current_branch(project_path)
                    if current != base_branch:
                        self._send_error(
                            HTTPStatus.CONFLICT,
                            (
                                f"Refusing to merge: project is on branch '{current}', expected '{base_branch}'. "
                                "Checkout the expected base branch and ensure the repo is clean, or use patch mode."
                            ),
                        )
                        return
                if git_ops.is_dirty(project_path):
                    self._send_error(
                        HTTPStatus.CONFLICT,
                        (
                            "Refusing to merge: original project worktree has uncommitted changes. "
                            "Commit/stash them first, or use patch mode."
                        ),
                    )
                    return
                output = git_ops.merge_branch(project_path, branch_name)
                db.update_run(run_id, status="merged")
                # Best-effort cleanup after successful merge.
                cleanup = {"worktree_removed": False, "branch_deleted": False}
                try:
                    git_ops.remove_worktree(project_path, worktree_path, force=True)
                    cleanup["worktree_removed"] = True
                except Exception:
                    cleanup["worktree_removed"] = False
                try:
                    git_ops.delete_branch(project_path, branch_name, force=False)
                    cleanup["branch_deleted"] = True
                except Exception:
                    cleanup["branch_deleted"] = False
                self._send_json({"run_id": run_id, "mode": mode, "output": output, "cleanup": cleanup})
                return
            if mode == "discard":
                git_ops.remove_worktree(project_path, worktree_path, force=True)
                db.update_run(run_id, status="discarded")
                cleanup = {"branch_deleted": False}
                try:
                    git_ops.delete_branch(project_path, branch_name, force=True)
                    cleanup["branch_deleted"] = True
                except Exception:
                    cleanup["branch_deleted"] = False
                self._send_json({"run_id": run_id, "mode": mode, "discarded": True, "cleanup": cleanup})
                return
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_event_stream(self, run_id: str, query: Dict[str, Any], *, run: Optional[Dict[str, Any]] = None) -> None:
        run = run or db.get_run(run_id)
        if not run:
            self._send_error(HTTPStatus.NOT_FOUND, f"Run not found: {run_id}")
            return

        after_id = _int_query(query, "after_id", 0, minimum=0)
        limit = _int_query(query, "limit", 500, minimum=1, maximum=2000)
        timeout_seconds = _int_query(query, "timeout", 25, minimum=1, maximum=300)
        poll_interval = 0.25
        deadline = time.time() + timeout_seconds
        last_id = after_id
        last_status = str(run.get("status") or "")

        try:
            self._send_sse_headers()
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            self._write_sse_event(
                "ready",
                {
                    "run_id": run_id,
                    "after_id": after_id,
                    "timeout": timeout_seconds,
                    "run": run,
                },
            )
            self._write_sse_event("run-state", {"run_id": run_id, "status": last_status})

            while time.time() < deadline:
                events = db.list_events(run_id, after_id=last_id, limit=limit)
                for event in events:
                    event_id = int(event.get("id") or 0)
                    last_id = max(last_id, event_id)
                    self._write_sse_event("run-event", event)

                current_run = db.get_run(run_id)
                current_status = str((current_run or {}).get("status") or "")
                if current_status and current_status != last_status:
                    self._write_sse_event("run-state", {"run_id": run_id, "status": current_status})
                    last_status = current_status

                if current_status in TERMINAL_RUN_STATUSES and not events:
                    self._write_sse_event(
                        "done",
                        {"run_id": run_id, "status": current_status, "last_event_id": last_id},
                    )
                    return

                time.sleep(poll_interval)

            self.wfile.write(b": timeout\n\n")
            self.wfile.flush()
        except OSError:
            return


def _int_query(
    query: Dict[str, Any],
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> int:
    try:
        values = query.get(name)
        if not values:
            return default
        parsed = int(values[0])
        if maximum is not None:
            parsed = min(maximum, parsed)
        return max(minimum, parsed)
    except (TypeError, ValueError):
        return default


def _run_route(route: str) -> Tuple[str, str]:
    rest = route.removeprefix("/api/runs/").strip("/")
    run_id, _, action = rest.partition("/")
    return unquote(run_id), action.strip("/")


def _project_selector_from_run(run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(run.get("project_name") or ""),
        "path": str(run.get("project_path") or ""),
    }


def _project_active_conflicts(project: Dict[str, Any], exclude_run_id: Optional[str]) -> list:
    project_path = str(project.get("path") or "").strip()
    if not project_path:
        return []
    runs = db.list_runs_by_project_path_and_status(project_path, ACTIVE_RUN_STATUSES, limit=50)
    result = []
    for run in runs:
        if exclude_run_id and run.get("id") == exclude_run_id:
            continue
        result.append(run)
    return result


def _mark_run_queued(run_id: str, pending_phase: str, *, clear_summary: bool) -> None:
    run = db.get_run(run_id)
    if not run:
        return
    metadata = run.get("metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["pending_phase"] = pending_phase
    fields: Dict[str, Any] = {"status": "queued", "metadata": metadata}
    if clear_summary:
        fields["summary"] = None
    db.update_run(run_id, **fields)


def _agent_summaries(config: Dict[str, Any]) -> list:
    agents = config.get("agents", {}) or {}
    if not isinstance(agents, dict):
        return []
    summaries = []
    for name, raw in agents.items():
        if not isinstance(raw, dict):
            continue
        try:
            agent = get_agent(config, str(name))
        except Exception:
            continue
        env_map = raw.get("env", {}) or {}
        summaries.append(
            {
                "name": agent.name,
                "runner": agent.runner,
                "model": agent.model,
                "role": agent.role,
                "timeout_seconds": agent.timeout_seconds,
                "enabled": bool(raw.get("enabled", True)),
                "preferred_skills": raw.get("preferred_skills", []) or [],
                "preferred_mcp": raw.get("preferred_mcp", []) or [],
                "env_keys": list(env_map.keys()) if isinstance(env_map, dict) else [],
            }
        )
    return summaries


def _list_run_artifacts(run_id: str) -> list:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        return []
    items = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(run_dir).as_posix()
        items.append({"name": rel, "bytes": int(path.stat().st_size)})
    return items


def _ensure_ui_dist() -> None:
    if (UI_DIST_DIR / "index.html").exists():
        return
    if not UI_DIR.exists():
        return
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError(
            "UI dist is missing and npm was not found. Run `cd ui && npm install && npm run build`."
        )
    if os.name == "nt" and npm.lower().endswith((".cmd", ".bat")):
        command = ["cmd.exe", "/c", npm, "run", "build"]
    else:
        command = [npm, "run", "build"]
    proc = subprocess.run(
        command,
        cwd=str(UI_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "UI build failed")
