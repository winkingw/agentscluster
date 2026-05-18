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
    remove_project,
    save_config,
)
from agents_cluster.core.doctor import run_doctor
from agents_cluster.core.env import load_dotenv
from agents_cluster.core.integrations import list_integrations, run_spike
from agents_cluster.core.paths import (
    CONFIG_EXAMPLE_PATH,
    CONFIG_PATH,
    ENV_PATH,
    PATCHES_DIR,
    RUNS_DIR,
    WORKTREES_DIR,
)
from agents_cluster.orchestrator.controller import apply_run, execute_run, plan_run, run_task
from agents_cluster.orchestrator.agent_test import test_agent
from agents_cluster.api.server import serve


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

    doctor_cmd = sub.add_parser("doctor", help="Check environment, tools, config, keys, and MCP.")
    doctor_cmd.set_defaults(func=cmd_doctor)

    integrations_cmd = sub.add_parser("integrations", help="Inspect optional orchestration/worker integrations.")
    integrations_sub = integrations_cmd.add_subparsers(dest="integrations_command", required=True)
    integrations_list = integrations_sub.add_parser("list", help="List optional integrations.")
    integrations_list.set_defaults(func=cmd_integrations_list)
    integrations_spike = integrations_sub.add_parser("spike", help="Run a local no-model spike for one integration.")
    integrations_spike.add_argument("name", choices=["langgraph", "openai-agents", "openhands"])
    integrations_spike.add_argument("--goal", default="验证 agentsCluster 可插拔集成")
    integrations_spike.set_defaults(func=cmd_integrations_spike)

    serve_cmd = sub.add_parser("serve", help="Start the local JSON API server for frontend use.")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8765)
    serve_cmd.set_defaults(func=cmd_serve)

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
    project_remove = project_sub.add_parser("remove", help="Remove a registered project without deleting files.")
    project_remove.add_argument("selector", help="Project name or path.")
    project_remove.set_defaults(func=cmd_project_remove)
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
    run_cmd.add_argument(
        "--max-rework-rounds",
        type=int,
        help="Override automatic rework rounds when reviewer requests changes.",
    )
    run_cmd.set_defaults(func=cmd_run)

    test_agent_cmd = sub.add_parser("test-agent", help="Run or validate one configured agent.")
    test_agent_cmd.add_argument("agent", help="Agent name, for example: master")
    test_agent_cmd.add_argument("--cwd", help="Working directory for the test. Default: current directory.")
    test_agent_cmd.add_argument("--prompt", help="Custom test prompt.")
    test_agent_cmd.add_argument("--dry-run", action="store_true", help="Validate config without calling the model.")
    test_agent_cmd.set_defaults(func=cmd_test_agent)

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
    runs_replan = runs_sub.add_parser("replan", help="Re-run planning for an existing run.")
    runs_replan.add_argument("run_id")
    runs_replan.set_defaults(func=cmd_runs_replan)
    runs_execute = runs_sub.add_parser("execute", help="Execute workers/review for an existing run.")
    runs_execute.add_argument("run_id")
    runs_execute.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    runs_execute.set_defaults(func=cmd_runs_execute)
    runs_artifacts = runs_sub.add_parser("artifacts", help="List or print run artifacts.")
    runs_artifacts.add_argument("run_id")
    runs_artifacts.add_argument("--name", help="Relative artifact path to print.")
    runs_artifacts.set_defaults(func=cmd_runs_artifacts)

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


def cmd_doctor(args: argparse.Namespace) -> None:
    raise SystemExit(run_doctor())


def cmd_integrations_list(args: argparse.Namespace) -> None:
    print("Optional integrations:")
    for status in list_integrations():
        marker = "installed" if status.installed else "missing"
        print(f"- {status.name}: {marker}")
        print(f"  detail: {status.detail}")
        print(f"  use: {status.use_for}")
        if not status.installed:
            print(f"  install: {status.install_hint}")


def cmd_integrations_spike(args: argparse.Namespace) -> None:
    print(run_spike(args.name, args.goal))


def cmd_serve(args: argparse.Namespace) -> None:
    serve(host=args.host, port=args.port)


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


def cmd_project_remove(args: argparse.Namespace) -> None:
    config = load_config()
    project = remove_project(config, args.selector)
    save_config(config)
    print(f"Removed project registration: {project.get('name')} -> {project.get('path')}")


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
    run_task(
        config,
        project,
        args.goal,
        yes=args.yes,
        workers=workers,
        max_rework_rounds=args.max_rework_rounds,
    )


def cmd_test_agent(args: argparse.Namespace) -> None:
    config = load_config()
    cwd = Path(args.cwd) if args.cwd else Path.cwd()
    raise SystemExit(test_agent(config, args.agent, cwd=cwd, prompt=args.prompt, dry_run=args.dry_run))


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
    run_dir = RUNS_DIR / run["id"]
    if run_dir.exists():
        artifacts = [path.relative_to(run_dir).as_posix() for path in sorted(run_dir.rglob("*")) if path.is_file()]
        if artifacts:
            print("Artifacts:")
            for item in artifacts[:20]:
                print(f"- {item}")
            if len(artifacts) > 20:
                print(f"... and {len(artifacts) - 20} more")
            print("")
    summary_path = RUNS_DIR / run["id"] / "summary.md"
    if summary_path.exists():
        print(summary_path.read_text(encoding="utf-8"))
        return
    plan_path = RUNS_DIR / run["id"] / "plan.md"
    if plan_path.exists():
        print(plan_path.read_text(encoding="utf-8"))


def cmd_runs_replan(args: argparse.Namespace) -> None:
    db.init_db()
    config = load_config()
    run = db.get_run(args.run_id)
    if not run:
        raise KeyError(f"Run not found: {args.run_id}")
    if run["status"] in {"merged", "discarded"}:
        raise ValueError(f"Run {args.run_id} is already finalized: {run['status']}")
    result = plan_run(config, args.run_id)
    print(f"Run:    {args.run_id}")
    print(f"Status: {result['status']}")
    print(f"Plan:   {RUNS_DIR / args.run_id / 'plan.md'}")
    print(f"Tasks:  {RUNS_DIR / args.run_id / 'task-plan.json'}")


def cmd_runs_execute(args: argparse.Namespace) -> None:
    db.init_db()
    config = load_config()
    run = db.get_run(args.run_id)
    if not run:
        raise KeyError(f"Run not found: {args.run_id}")
    if run["status"] in {"merged", "discarded"}:
        raise ValueError(f"Run {args.run_id} is already finalized: {run['status']}")
    plan_path = RUNS_DIR / args.run_id / "plan.md"
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan file not found: {plan_path}")
    if not args.yes:
        print("--- Plan preview ---")
        print(plan_path.read_text(encoding="utf-8")[:2500])
        answer = input("\nStart execution for this run? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Skipped.")
            return
    result = execute_run(config, args.run_id)
    print(f"Run:     {args.run_id}")
    print(f"Status:  {result['status']}")
    print(f"Summary: {RUNS_DIR / args.run_id / 'summary.md'}")


def cmd_runs_artifacts(args: argparse.Namespace) -> None:
    db.init_db()
    run = db.get_run(args.run_id)
    if not run:
        raise KeyError(f"Run not found: {args.run_id}")
    run_dir = RUNS_DIR / args.run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    if not args.name:
        artifacts = [path.relative_to(run_dir).as_posix() for path in sorted(run_dir.rglob("*")) if path.is_file()]
        if not artifacts:
            print("No artifacts.")
            return
        for item in artifacts:
            print(item)
        return
    rel = args.name.replace("\\", "/").strip("/")
    if not rel or ".." in rel.split("/"):
        raise ValueError("Invalid artifact path")
    target = (run_dir / rel).resolve()
    root = run_dir.resolve()
    if root not in target.parents and target != root:
        raise ValueError("Artifact path escapes run directory")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"Artifact not found: {rel}")
    print(target.read_text(encoding="utf-8", errors="replace"))


def cmd_apply(args: argparse.Namespace) -> None:
    db.init_db()
    apply_run(args.run_id, mode=args.mode)


if __name__ == "__main__":
    main()
