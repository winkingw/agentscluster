from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .paths import DB_PATH


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(
            """
            create table if not exists runs (
                id text primary key,
                created_at text not null,
                project_name text not null,
                project_path text not null,
                worktree_path text not null,
                branch_name text not null,
                goal text not null,
                status text not null,
                summary text,
                metadata_json text not null default '{}'
            );

            create table if not exists events (
                id integer primary key autoincrement,
                run_id text not null,
                created_at text not null,
                agent text not null,
                kind text not null,
                message text not null,
                metadata_json text not null default '{}'
            );
            """
        )


def insert_run(run: Dict[str, Any], path: Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            insert into runs (
                id, created_at, project_name, project_path, worktree_path,
                branch_name, goal, status, summary, metadata_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["id"],
                run["created_at"],
                run["project_name"],
                run["project_path"],
                run["worktree_path"],
                run["branch_name"],
                run["goal"],
                run.get("status", "created"),
                run.get("summary"),
                json.dumps(run.get("metadata", {}), ensure_ascii=False),
            ),
        )


def update_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    converted = {}
    for key, value in fields.items():
        if key == "metadata":
            converted["metadata_json"] = json.dumps(value, ensure_ascii=False)
        else:
            converted[key] = value
    assignments = ", ".join(f"{key}=?" for key in converted)
    values = list(converted.values()) + [run_id]
    with connect() as conn:
        conn.execute(f"update runs set {assignments} where id=?", values)


def add_event(
    run_id: str,
    created_at: str,
    agent: str,
    kind: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            insert into events (run_id, created_at, agent, kind, message, metadata_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (run_id, created_at, agent, kind, message, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return int(cur.lastrowid or 0)


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("select * from runs where id=?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None


def list_runs(limit: int = 20) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "select * from runs order by created_at desc limit ?",
            (limit,),
        ).fetchall()
        return [_row_to_run(row) for row in rows]


def list_events(run_id: str, *, after_id: int = 0, limit: int = 500) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "select * from events where run_id=? and id>? order by id asc limit ?",
            (run_id, int(after_id), int(max(1, limit))),
        ).fetchall()
        return [_row_to_event(row) for row in rows]


def list_runs_by_status(statuses: Sequence[str], *, limit: int = 200) -> List[Dict[str, Any]]:
    normalized = [str(s).strip() for s in statuses if str(s).strip()]
    if not normalized:
        return []
    placeholders = ", ".join("?" for _ in normalized)
    with connect() as conn:
        rows = conn.execute(
            f"select * from runs where status in ({placeholders}) order by created_at desc limit ?",
            (*normalized, int(max(1, limit))),
        ).fetchall()
        return [_row_to_run(row) for row in rows]


def _row_to_run(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
    return data


def _row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    # Present a stable JSON shape to callers; keep the raw column out of the public payload.
    data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
    return data
