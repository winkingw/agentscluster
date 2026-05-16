from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agents_cluster.api.server import AgentsClusterHandler
from agents_cluster.core import db
from agents_cluster.core.paths import CONFIG_PATH


def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc


def request_json(url: str, method: str = "GET", payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    db.init_db()
    original_config = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentsClusterHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            run(["git", "init"], repo)
            run(["git", "config", "user.email", "agentsCluster@example.local"], repo)
            run(["git", "config", "user.name", "agentsCluster Smoke"], repo)
            (repo / "README.md").write_text("# api smoke\n", encoding="utf-8")
            run(["git", "add", "README.md"], repo)
            run(["git", "commit", "-m", "init"], repo)

            health = request_json(f"{base_url}/health")
            assert health["ok"] is True

            created = request_json(
                f"{base_url}/api/projects",
                method="POST",
                payload={"name": "api-smoke", "path": str(repo)},
            )
            assert created["project"]["name"] == "api-smoke"

            projects = request_json(f"{base_url}/api/projects")
            assert any(project["name"] == "api-smoke" for project in projects["projects"])

            removed = request_json(f"{base_url}/api/projects/api-smoke", method="DELETE")
            assert removed["removed"]["name"] == "api-smoke"

            runs = request_json(f"{base_url}/api/runs?limit=1")
            assert "runs" in runs
    finally:
        server.shutdown()
        server.server_close()
        if original_config is not None:
            CONFIG_PATH.write_text(original_config, encoding="utf-8")

    print("api smoke ok")


if __name__ == "__main__":
    main()
