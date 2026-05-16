from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from agents_cluster.core import db
from agents_cluster.core.config import add_project, list_projects, load_config, remove_project, save_config


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
        if route == "/api/runs":
            limit = _int_query(query, "limit", 20)
            self._send_json({"runs": db.list_runs(limit=limit)})
            return
        if route.startswith("/api/runs/"):
            run_id = unquote(route.removeprefix("/api/runs/"))
            run = db.get_run(run_id)
            if not run:
                self._send_error(HTTPStatus.NOT_FOUND, f"Run not found: {run_id}")
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


def _int_query(query: Dict[str, Any], name: str, default: int) -> int:
    try:
        values = query.get(name)
        if not values:
            return default
        return max(1, int(values[0]))
    except (TypeError, ValueError):
        return default
