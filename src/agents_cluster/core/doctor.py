from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List

from .config import get_agent, load_config
from .env import load_dotenv
from .integrations import list_integrations
from .paths import CLUSTER_ROOT, CONFIG_EXAMPLE_PATH, CONFIG_PATH, ENV_PATH


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""


def run_doctor() -> int:
    load_dotenv(ENV_PATH)
    checks: List[Check] = []
    checks.extend(_path_checks())
    checks.extend(_tool_checks())
    checks.extend(_config_checks())
    checks.extend(_integration_checks())
    checks.extend(_mcp_checks())

    print("agentsCluster doctor")
    print("")
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(f"[{status}] {check.name}: {check.detail}")
        if not check.ok and check.hint:
            print(f"       hint: {check.hint}")

    failed = [check for check in checks if not check.ok]
    print("")
    print(f"Result: {len(checks) - len(failed)} passed, {len(failed)} failed.")
    return 0 if not failed else 1


def _path_checks() -> List[Check]:
    conda_env = os.environ.get("CONDA_DEFAULT_ENV") or "(not active)"
    command_path = shutil.which("agentsCluster") or shutil.which("agentscluster")
    wrapper = CLUSTER_ROOT / "agentsCluster.ps1"
    return [
        Check("python", True, sys.executable),
        Check("conda env", conda_env == "agentsCluster", conda_env, "Run: conda activate agentsCluster"),
        Check(
            "agentsCluster command",
            bool(command_path),
            command_path or "not found in PATH",
            "Use: conda run -n agentsCluster agentsCluster doctor, or .\\agentsCluster.ps1 doctor",
        ),
        Check("local wrapper", wrapper.exists(), str(wrapper)),
    ]


def _tool_checks() -> List[Check]:
    checks = []
    for tool in ("git", "codex", "claude"):
        found = shutil.which(tool)
        checks.append(Check(tool, bool(found), found or "not found in PATH"))
    return checks


def _config_checks() -> List[Check]:
    checks = [
        Check("config example", CONFIG_EXAMPLE_PATH.exists(), str(CONFIG_EXAMPLE_PATH)),
        Check("config", CONFIG_PATH.exists(), str(CONFIG_PATH), "Run: agentsCluster init"),
        Check("env file", ENV_PATH.exists(), str(ENV_PATH), "Create .env from .env.example"),
    ]
    if not CONFIG_PATH.exists():
        return checks

    try:
        config = load_config()
    except Exception as exc:
        checks.append(Check("config parse", False, str(exc)))
        return checks

    checks.append(Check("config parse", True, "ok"))
    agents = config.get("agents", {})
    if not isinstance(agents, dict) or not agents:
        checks.append(Check("agents", False, "no agents configured"))
        return checks

    for agent_name in agents:
        try:
            agent = get_agent(config, agent_name)
        except Exception as exc:
            checks.append(Check(f"agent {agent_name}", False, str(exc)))
            continue
        checks.append(Check(f"agent {agent_name}", True, f"runner={agent.runner}, model={agent.model}"))
        for env_name in _agent_env_names(agent.raw):
            checks.append(
                Check(
                    f"env {agent_name}.{env_name}",
                    bool(os.environ.get(env_name)),
                    "set" if os.environ.get(env_name) else "missing",
                    f"Set {env_name} in .env",
                )
            )
    return checks


def _agent_env_names(raw: Dict) -> List[str]:
    names = []
    env_map = raw.get("env", {}) or {}
    if isinstance(env_map, dict):
        for value in env_map.values():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                names.append(value[2:-1])
    direct = raw.get("direct_llm", {}) or {}
    if isinstance(direct, dict) and direct.get("api_key_env"):
        names.append(str(direct["api_key_env"]))
    return sorted(set(names))


def _mcp_checks() -> List[Check]:
    codex = shutil.which("codex")
    if not codex:
        return [Check("codex mcp", False, "codex not found")]
    try:
        proc = subprocess.run(
            [codex, "mcp", "list"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
    except Exception as exc:
        return [Check("codex mcp", False, str(exc))]

    if proc.returncode != 0:
        return [Check("codex mcp", False, proc.stderr.strip() or proc.stdout.strip())]

    names = _mcp_names(proc.stdout)
    detail = ", ".join(names) if names else "no MCP servers listed"
    return [Check("codex mcp", True, detail)]


def _integration_checks() -> List[Check]:
    checks = []
    for status in list_integrations():
        checks.append(
            Check(
                f"optional {status.name}",
                True,
                "installed: " + status.detail if status.installed else "missing: " + status.install_hint,
            )
        )
    return checks


def _mcp_names(output: str) -> List[str]:
    names = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Name ") or stripped.startswith("-"):
            continue
        first = stripped.split()[0]
        if first not in ("Name", "Command"):
            names.append(first)
    return names
