from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from agents_cluster.core import db
from agents_cluster.core.config import add_project, get_agent, list_projects, load_config, remove_project, save_config
from agents_cluster.core.paths import PATCHES_DIR
from agents_cluster.orchestrator.agent_test import test_agent
from agents_cluster.workspace import git_ops


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    db.init_db()
    server = ThreadingHTTPServer((host, port), AgentsClusterHandler)
    print(f"agentsCluster API listening on http://{host}:{port}")
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
            if action == "events":
                self._send_json({"run_id": run_id, "events": db.list_events(run_id)})
                return
            if action == "diff":
                self._send_json({"run_id": run_id, "diff": git_ops.diff(Path(run["worktree_path"]))})
                return
            if action:
                self._send_error(HTTPStatus.NOT_FOUND, f"Unknown run action: {action}")
                return
            self._send_json({"run": run, "events": db.list_events(run_id)})
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
        if route.startswith("/api/agents/") and route.endswith("/test"):
            agent_name = unquote(route.removeprefix("/api/agents/").removesuffix("/test").strip("/"))
            self._handle_agent_test(agent_name)
            return
        if route.startswith("/api/runs/") and route.endswith("/apply"):
            run_id, action = _run_route(route)
            if action != "apply":
                self._send_error(HTTPStatus.NOT_FOUND, f"Unknown run action: {action}")
                return
            self._handle_apply(run_id)
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
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)

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
            if mode == "diff":
                self._send_json({"run_id": run_id, "mode": mode, "diff": git_ops.diff(worktree_path)})
                return
            if mode == "patch":
                patch_path = PATCHES_DIR / f"{run_id}.patch"
                git_ops.write_patch(worktree_path, patch_path)
                self._send_json({"run_id": run_id, "mode": mode, "patch_path": str(patch_path)})
                return
            if mode == "merge":
                output = git_ops.merge_branch(project_path, branch_name)
                db.update_run(run_id, status="merged")
                self._send_json({"run_id": run_id, "mode": mode, "output": output})
                return
            if mode == "discard":
                git_ops.remove_worktree(project_path, worktree_path, force=True)
                db.update_run(run_id, status="discarded")
                self._send_json({"run_id": run_id, "mode": mode, "discarded": True})
                return
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))


def _int_query(query: Dict[str, Any], name: str, default: int) -> int:
    try:
        values = query.get(name)
        if not values:
            return default
        return max(1, int(values[0]))
    except (TypeError, ValueError):
        return default


def _run_route(route: str) -> Tuple[str, str]:
    rest = route.removeprefix("/api/runs/").strip("/")
    run_id, _, action = rest.partition("/")
    return unquote(run_id), action.strip("/")


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
