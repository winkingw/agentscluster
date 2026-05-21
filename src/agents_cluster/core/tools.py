from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .paths import CLUSTER_ROOT


@dataclass(frozen=True)
class ToolStatus:
    name: str
    installed: bool
    # The default command name expected on PATH (for subprocess runners).
    command: str
    # Resolved command path on PATH (if any).
    command_path: Optional[str]
    # Cluster-managed local install root (if applicable).
    local_root: Optional[str]
    # Cluster-managed local executable path (if applicable and present).
    local_command_path: Optional[str]
    install_hint: str


_KNOWN_TOOLS: Dict[str, Dict[str, str]] = {
    # We intentionally install tool CLIs into isolated venvs under vendor/tools
    # to avoid polluting / breaking the main conda environment.
    "aider": {
        "command": "aider",
        "install_hint": "agentsCluster tools install aider",
    },
    # These are supported as subprocess runners, but not installed by default
    # on Windows due to Python version / Docker constraints.
    "openhands": {
        "command": "openhands",
        "install_hint": "Install OpenHands CLI separately (Python 3.12+). See: agentsCluster integrations list",
    },
    "swe-agent": {
        "command": "sweagent",
        "install_hint": "Use Docker/WSL on Windows; see: agentsCluster integrations list",
    },
}


def tools_root() -> Path:
    return CLUSTER_ROOT / "vendor" / "tools"


def list_tools() -> List[ToolStatus]:
    return [get_tool_status(name) for name in sorted(_KNOWN_TOOLS.keys())]


def get_tool_status(name: str) -> ToolStatus:
    if name not in _KNOWN_TOOLS:
        raise ValueError(f"Unknown tool: {name}")
    command = _KNOWN_TOOLS[name]["command"]
    command_path = shutil.which(command)
    local_root = _local_tool_root(name)
    local_command_path = _local_tool_command_path(name)
    return ToolStatus(
        name=name,
        installed=bool(command_path or local_command_path),
        command=command,
        command_path=command_path,
        local_root=str(local_root) if local_root else None,
        local_command_path=str(local_command_path) if local_command_path else None,
        install_hint=_KNOWN_TOOLS[name]["install_hint"],
    )


def install_tool(name: str) -> ToolStatus:
    if name == "aider":
        _install_aider()
        return get_tool_status(name)
    raise ValueError(f"Unsupported tool install on this platform: {name}")


def uninstall_tool(name: str) -> ToolStatus:
    root = _local_tool_root(name)
    if root and root.exists():
        # Safety: only allow deleting within vendor/tools
        base = tools_root().resolve()
        target = root.resolve()
        if base not in target.parents and base != target:
            raise RuntimeError(f"Refuse to delete outside tools root: {target}")
        shutil.rmtree(target, ignore_errors=False)
    return get_tool_status(name)


def _local_tool_root(name: str) -> Optional[Path]:
    if name == "aider":
        return tools_root() / "aider"
    return None


def _local_tool_venv_dir(name: str) -> Optional[Path]:
    root = _local_tool_root(name)
    if not root:
        return None
    return root / ".venv"


def _local_tool_command_path(name: str) -> Optional[Path]:
    venv_dir = _local_tool_venv_dir(name)
    if not venv_dir:
        return None
    if os.name == "nt":
        candidate = venv_dir / "Scripts" / "aider.exe"
        if candidate.exists():
            return candidate
        # Fallback for some environments.
        candidate = venv_dir / "Scripts" / "aider.cmd"
        if candidate.exists():
            return candidate
        return None
    candidate = venv_dir / "bin" / "aider"
    return candidate if candidate.exists() else None


def _install_aider() -> None:
    root = _local_tool_root("aider")
    assert root is not None
    venv_dir = _local_tool_venv_dir("aider")
    assert venv_dir is not None

    root.mkdir(parents=True, exist_ok=True)
    if not venv_dir.exists():
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])

    python = _venv_python(venv_dir)
    env = os.environ.copy()
    # Keep installs deterministic-ish and avoid writing caches outside the repo.
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

    subprocess.check_call([python, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], env=env)
    subprocess.check_call([python, "-m", "pip", "install", "--upgrade", "aider-chat"], env=env)


def _venv_python(venv_dir: Path) -> str:
    if os.name == "nt":
        python = venv_dir / "Scripts" / "python.exe"
    else:
        python = venv_dir / "bin" / "python"
    if not python.exists():
        raise RuntimeError(f"venv python not found: {python}")
    return str(python)

