from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from agents_cluster.core import db
from agents_cluster.core.config import (
    add_project,
    command_exists,
    find_project,
    list_projects,
    load_config,
    save_config,
)
from agents_cluster.core.env import load_dotenv
from agents_cluster.core.paths import (
    CONFIG_EXAMPLE_PATH,
    CONFIG_PATH,
    ENV_PATH,
    PATCHES_DIR,
    RUNS_DIR,
    WORKTREES_DIR,
)
from agents_cluster.orchestrator.controller import apply_run, run_task


def main(argv: Optional[List[str]] = None) -> None:
    load_dotenv(ENV_PATH)
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentsCluster")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init", help="Initialize database and check local tools.")
    init_cmd.set_defaults(func=cmd_init)

    config_cmd = sub.add_parser("config", help="Configuration helpers.")
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)
    config_open = config_sub.add_parser("open", help="Open the agents.yaml path.")
    config_open.set_defaults(func=cmd_config_open)
    config_show = config_sub.add_parser("show", help="Print config path.")
    config_show.set_defaults(func=cmd_config_show)

    project_cmd = sub.add_parser("project", help="Register and list projects.")
    project_sub = project_cmd.add_subparsers(dest="project_command", required=True)
    project_add = project_sub.add_parser("add", help="Add a git project.")
    project_add.add_argument("path")
    project_add.add_argument("--name")
    project_add.set_defaults(func=cmd_project_add)
    project_list = project_sub.add_parser("list", help="List registered projects.")
    project_list.set_defaults(func=cmd_project_list)

    run_cmd = sub.add_parser("run", help="Run an orchestrated task.")
    run_cmd.add_argument("--project", required=True, help="Project name or path.")
    run_cmd.add_argument("--goal", required=True, help="Task goal.")
    run_cmd.add_argument("--yes", action="store_true", help="Skip plan confirmation.")
    run_cmd.add_argument(
        "--workers",
        help="Comma-separated worker agent names. Default: architect,coder,tester.",
    )
    run_cmd.set_defaults(func=cmd_run)

    chat_cmd = sub.add_parser("chat", help="Interactive task entry.")
    chat_cmd.set_defaults(func=cmd_chat)

    runs_cmd = sub.add_parser("runs", help="Inspect previous runs.")
    runs_sub = runs_cmd.add_subparsers(dest="runs_command", required=True)
    runs_list = runs_sub.add_parser("list", help="List runs.")
    runs_list.add_argument("--limit", type=int, default=20)
    runs_list.set_defaults(func=cmd_runs_list)
    runs_show = runs_sub.add_parser("show", help="Show one run.")
    runs_show.add_argument("run_id")
    runs_show.set_defaults(func=cmd_runs_show)

    apply_cmd = sub.add_parser("apply", help="Choose merge/diff/patch/discard for a run.")
    apply_cmd.add_argument("run_id")
    apply_cmd.add_argument("--mode", choices=["merge", "diff", "patch", "discard"])
    apply_cmd.set_defaults(func=cmd_apply)

    return parser


def cmd_init(args: argparse.Namespace) -> None:
    for path in (RUNS_DIR, WORKTREES_DIR, PATCHES_DIR, CONFIG_PATH.parent):
        path.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists() and CONFIG_EXAMPLE_PATH.exists():
        shutil.copyfile(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
    db.init_db()

    print(f"Config: {CONFIG_PATH}")
    print(f"Env:    {ENV_PATH}")
    print(f"DB:     {db.DB_PATH if hasattr(db, 'DB_PATH') else 'agentsCluster.db'}")
    print("")
    print("Tool check:")
    for tool in ("git", "codex", "claude"):
        print(f"- {tool}: {'ok' if command_exists(tool) else 'missing'}")
    print("")
    print("Initialized.")


def cmd_config_open(args: argparse.Namespace) -> None:
    print(CONFIG_PATH)
    if os.name == "nt":
        subprocess.run(["notepad", str(CONFIG_PATH)], check=False)


def cmd_config_show(args: argparse.Namespace) -> None:
    print(CONFIG_PATH)


def cmd_project_add(args: argparse.Namespace) -> None:
    config = load_config()
    project = add_project(config, Path(args.path), args.name)
    save_config(config)
    print(f"Added project: {project['name']} -> {project['path']}")


def cmd_project_list(args: argparse.Namespace) -> None:
    config = load_config()
    projects = list_projects(config)
    if not projects:
        print("No projects registered.")
        return
    for index, project in enumerate(projects, start=1):
        print(f"{index}. {project.get('name')} -> {project.get('path')}")


def cmd_run(args: argparse.Namespace) -> None:
    config = load_config()
    project = find_project(config, args.project)
    workers = [item.strip() for item in args.workers.split(",") if item.strip()] if args.workers else None
    run_task(config, project, args.goal, yes=args.yes, workers=workers)


def cmd_chat(args: argparse.Namespace) -> None:
    config = load_config()
    projects = list_projects(config)
    if projects:
        print("Registered projects:")
        for index, project in enumerate(projects, start=1):
            print(f"{index}. {project.get('name')} -> {project.get('path')}")
        selector = input("Project number/name/path: ").strip()
        if selector.isdigit() and 1 <= int(selector) <= len(projects):
            project = projects[int(selector) - 1]
        else:
            project = find_project(config, selector)
    else:
        selector = input("Project path: ").strip()
        project = find_project(config, selector)

    goal = input("Goal: ").strip()
    if not goal:
        raise ValueError("Goal is required")
    run_task(config, project, goal)


def cmd_runs_list(args: argparse.Namespace) -> None:
    db.init_db()
    runs = db.list_runs(limit=args.limit)
    if not runs:
        print("No runs.")
        return
    for run in runs:
        print(
            f"{run['id']} | {run['status']} | {run['project_name']} | "
            f"{run['created_at']} | {run['goal'][:80]}"
        )


def cmd_runs_show(args: argparse.Namespace) -> None:
    db.init_db()
    run = db.get_run(args.run_id)
    if not run:
        raise KeyError(f"Run not found: {args.run_id}")
    print(f"ID:       {run['id']}")
    print(f"Status:   {run['status']}")
    print(f"Project:  {run['project_name']} -> {run['project_path']}")
    print(f"Worktree: {run['worktree_path']}")
    print(f"Branch:   {run['branch_name']}")
    print(f"Goal:     {run['goal']}")
    print("")
    summary_path = RUNS_DIR / run["id"] / "summary.md"
    if summary_path.exists():
        print(summary_path.read_text(encoding="utf-8"))


def cmd_apply(args: argparse.Namespace) -> None:
    db.init_db()
    apply_run(args.run_id, mode=args.mode)


if __name__ == "__main__":
    main()
