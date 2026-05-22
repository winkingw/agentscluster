from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class IntegrationStatus:
    name: str
    installed: bool
    detail: str
    install_hint: str
    use_for: str


OPTIONAL_INTEGRATIONS: Dict[str, Dict[str, str]] = {
    "langgraph": {
        "module": "langgraph",
        "install": "pip install -U langgraph",
        "use_for": "用于任务图、状态机、人工确认节点和长任务恢复。",
    },
    "openai-agents": {
        "module": "agents",
        "install": "pip install openai-agents",
        "use_for": "用于 handoff、MCP、tracing、guardrails 和轻量 agent 协作层。",
    },
}

OPTIONAL_CLIS: Dict[str, Dict[str, str]] = {
    "openhands": {
        "command": "openhands",
        "install": "(optional) uv tool install openhands --python 3.12",
        "use_for": "纯可选扩展：用于对比/扩展重型 worker。不是 agentsCluster 主流程的必要条件。",
    },
    "aider": {
        "command": "aider",
        "install": "agentsCluster tools install aider",
        "use_for": "用于单仓库代码修改型 worker，可作为 coder runner。",
    },
    "swe-agent": {
        "command": "sweagent",
        "alt_command": "swe-agent",
        "install": "Use Docker/WSL on Windows; or: pip install sweagent",
        "use_for": "用于 GitHub issue 或 bugfix 类型的专用 worker。",
    },
}


def list_integrations() -> List[IntegrationStatus]:
    statuses = []
    for name, meta in OPTIONAL_INTEGRATIONS.items():
        module = meta["module"]
        installed = _module_exists(module)
        statuses.append(
            IntegrationStatus(
                name=name,
                installed=installed,
                detail=module if installed else f"module not found: {module}",
                install_hint=meta["install"],
                use_for=meta["use_for"],
            )
        )
    for name, meta in OPTIONAL_CLIS.items():
        command = meta["command"]
        found = shutil.which(command)
        if not found and meta.get("alt_command"):
            found = shutil.which(meta["alt_command"])
        statuses.append(
            IntegrationStatus(
                name=name,
                installed=found is not None,
                detail=found or f"command not found: {name}",
                install_hint=meta["install"],
                use_for=meta["use_for"],
            )
        )
    return statuses


def _module_exists(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def integration_status_map() -> Dict[str, IntegrationStatus]:
    return {status.name: status for status in list_integrations()}


def run_spike(name: str, goal: str) -> str:
    normalized = name.lower().replace("_", "-")
    if normalized == "langgraph":
        return _run_langgraph_spike(goal)
    if normalized in ("openai-agents", "openai-agents-sdk"):
        return _run_openai_agents_spike(goal)
    if normalized in ("openhands", "openhands-sdk"):
        return _run_openhands_spike(goal)
    if normalized in ("aider", "aider-chat"):
        return _run_aider_spike(goal)
    if normalized in ("swe-agent", "sweagent", "swe"):
        return _run_swe_agent_spike(goal)
    raise ValueError(f"Unknown integration spike: {name}")


def _run_langgraph_spike(goal: str) -> str:
    if not _module_exists("langgraph"):
        raise RuntimeError("LangGraph is not installed. Run: pip install -U langgraph")

    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class SpikeState(TypedDict):
        goal: str
        steps: list[str]
        status: str

    def plan_node(state: SpikeState) -> Dict[str, object]:
        return {
            "steps": [
                "master 生成结构化任务图",
                "worker 在独立 worktree 中执行",
                "reviewer 审核并触发返工，或等待用户确认",
            ],
            "status": "planned",
        }

    def review_node(state: SpikeState) -> Dict[str, object]:
        return {"status": "review-ready"}

    graph = StateGraph(SpikeState)
    graph.add_node("plan", plan_node)
    graph.add_node("review", review_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "review")
    graph.add_edge("review", END)
    compiled = graph.compile()
    result = compiled.invoke({"goal": goal, "steps": [], "status": "created"})
    return (
        "LangGraph spike ok.\n"
        f"goal: {result.get('goal')}\n"
        f"status: {result.get('status')}\n"
        "steps:\n- " + "\n- ".join(result.get("steps", []))
    )


def _run_openai_agents_spike(goal: str) -> str:
    if not _module_exists("agents"):
        raise RuntimeError("OpenAI Agents SDK is not installed. Run: pip install openai-agents")

    from agents import Agent

    agent = Agent(
        name="agentsCluster master spike",
        instructions=(
            "你是 agentsCluster 的总控验证 agent。"
            "这个 spike 只验证 SDK 可导入、agent 对象可构造，不调用模型。"
        ),
    )
    return (
        "OpenAI Agents SDK spike ok.\n"
        f"agent: {agent.name}\n"
        f"goal: {goal}\n"
        "next: 可以用 handoffs / MCP / tracing 替换 agentsCluster 的内部 agent 协议层。"
    )


def _run_openhands_spike(goal: str) -> str:
    return _run_cli_spike("openhands", goal, "uv tool install openhands --python 3.12 (optional)")


def _run_cli_spike(command_name: str, goal: str, hint: str) -> str:
    command = shutil.which(command_name)
    if not command:
        raise RuntimeError(f"{command_name} is not installed. Run: {hint}")
    args = ["--version"]
    if os.name == "nt" and command.lower().endswith((".cmd", ".bat")):
        full = ["cmd.exe", "/c", command, *args]
    else:
        full = [command, *args]
    proc = subprocess.run(
        full,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    output = (proc.stdout.strip() or proc.stderr.strip() or "").splitlines()
    head = "\n".join(output[:6]) if output else "(no output)"
    status = "ok" if proc.returncode == 0 else f"nonzero rc={proc.returncode}"
    return f"{command_name} spike {status}.\ngoal: {goal}\noutput:\n{head}"


def _run_aider_spike(goal: str) -> str:
    return _run_cli_spike("aider", goal, "agentsCluster tools install aider")


def _run_swe_agent_spike(goal: str) -> str:
    command = shutil.which("sweagent") or shutil.which("swe-agent")
    if not command:
        raise RuntimeError("swe-agent is not installed. Run: pip install sweagent")
    name = Path(command).name
    if os.name == "nt" and command.lower().endswith((".cmd", ".bat")):
        full = ["cmd.exe", "/c", command, "--version"]
    else:
        full = [command, "--version"]
    proc = subprocess.run(
        full,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    output = (proc.stdout.strip() or proc.stderr.strip() or "").splitlines()
    head = "\n".join(output[:6]) if output else "(no output)"
    status = "ok" if proc.returncode == 0 else f"nonzero rc={proc.returncode}"
    return f"{name} spike {status}.\ngoal: {goal}\noutput:\n{head}"
