from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import simple_yaml
from .paths import CONFIG_PATH


@dataclass
class AgentConfig:
    name: str
    runner: str
    model: Optional[str]
    role: str
    timeout_seconds: int
    raw: Dict[str, Any]


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = simple_yaml.load(path)
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a map: {path}")
    settings = data.setdefault("settings", {})
    if isinstance(settings, dict):
        settings.setdefault("orchestrator", "langgraph")
        settings.setdefault("integration_strategy", "adapter")
    data.setdefault("agents", {})
    data.setdefault("projects", [])
    return data


def save_config(data: Dict[str, Any], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(simple_yaml.dumps(data), encoding="utf-8")


def get_agent(data: Dict[str, Any], name: str) -> AgentConfig:
    agents = data.get("agents", {})
    raw = agents.get(name)
    if not isinstance(raw, dict):
        raise KeyError(f"Agent '{name}' is not configured")

    settings = data.get("settings", {})
    timeout = int(raw.get("timeout_seconds") or settings.get("default_timeout_seconds") or 1800)
    return AgentConfig(
        name=name,
        runner=str(raw.get("runner", "direct_llm")),
        model=raw.get("model"),
        role=str(raw.get("role", name)),
        timeout_seconds=timeout,
        raw=raw,
    )


def list_projects(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    projects = data.get("projects", [])
    return projects if isinstance(projects, list) else []


def find_project(data: Dict[str, Any], selector: str) -> Dict[str, Any]:
    selector_path = str(Path(selector).resolve()).lower()
    for project in list_projects(data):
        name = str(project.get("name", ""))
        path = str(Path(project.get("path", "")).resolve())
        if selector == name or selector_path == path.lower():
            return project
    candidate = Path(selector).resolve()
    if candidate.exists():
        return {"name": candidate.name, "path": str(candidate)}
    raise KeyError(f"Project not found: {selector}")


def add_project(data: Dict[str, Any], project_path: Path, name: Optional[str] = None) -> Dict[str, Any]:
    resolved = project_path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Project path does not exist: {resolved}")
    if not (resolved / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise ValueError(f"Project is not a git repository: {resolved}")

    projects = list_projects(data)
    normalized = str(resolved).lower()
    for project in projects:
        if str(Path(project.get("path", "")).resolve()).lower() == normalized:
            project["name"] = name or project.get("name") or resolved.name
            return project

    project = {"name": name or resolved.name, "path": str(resolved)}
    projects.append(project)
    data["projects"] = projects
    return project


def remove_project(data: Dict[str, Any], selector: str) -> Dict[str, Any]:
    projects = list_projects(data)
    if not projects:
        raise KeyError("No projects registered")

    selector_path = str(Path(selector).resolve()).lower()
    for index, project in enumerate(projects):
        name = str(project.get("name", ""))
        raw_path = str(project.get("path", ""))
        normalized_path = str(Path(raw_path).resolve()).lower() if raw_path else ""
        if selector == name or selector_path == normalized_path:
            removed = projects.pop(index)
            data["projects"] = projects
            return removed

    raise KeyError(f"Project not found: {selector}")


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None
