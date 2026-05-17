from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
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
        "use_for": "动态任务图、状态机、human-in-the-loop、长任务恢复。",
    },
    "openai-agents": {
        "module": "agents",
        "install": "pip install openai-agents",
        "use_for": "handoff、MCP、tracing、guardrails 和轻量 agent 协议层。",
    },
    "openhands-sdk": {
        "module": "openhands.sdk",
        "install": "pip install openhands-sdk",
        "use_for": "把成熟软件工程 agent 作为 worker 接入，后续可接 agent-server/REST。",
    },
    "openhands-agent-server": {
        "module": "openhands.agent_server",
        "install": "pip install openhands-sdk",
        "use_for": "本地/远程 agent server，供前端或远程 worker 复用。",
    },
}

OPTIONAL_CLIS: Dict[str, Dict[str, str]] = {
    "aider": {
        "command": "aider",
        "install": "pip install aider-chat",
        "use_for": "单仓库代码修改 worker，可作为 coder runner。",
    },
    "swe-agent": {
        "command": "sweagent",
        "alt_command": "swe-agent",
        "install": "pip install sweagent",
        "use_for": "GitHub issue / bugfix 型专项 worker。",
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
    raise ValueError(f"Unknown integration spike: {name}")


def _run_langgraph_spike(goal: str) -> str:
    if not _module_exists("langgraph"):
        raise RuntimeError("LangGraph is not installed. Run: pip install -U langgraph")

    from typing import List as TypingList
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class SpikeState(TypedDict):
        goal: str
        steps: TypingList[str]
        status: str

    def plan_node(state: SpikeState) -> Dict[str, object]:
        return {
            "steps": [
                "master 生成结构化任务图",
                "worker 在独立 worktree 执行",
                "reviewer 审核并触发返工或等待用户确认",
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
            "本 spike 只验证 SDK 可导入和 agent 对象可构造，不调用模型。"
        ),
    )
    return (
        "OpenAI Agents SDK spike ok.\n"
        f"agent: {agent.name}\n"
        f"goal: {goal}\n"
        "next: 可用 handoffs/MCP/tracing 替换 agentsCluster 的内部 agent 协议层。"
    )


def _run_openhands_spike(goal: str) -> str:
    if not _module_exists("openhands.sdk"):
        raise RuntimeError("OpenHands SDK is not installed. Run: pip install openhands-sdk")

    import openhands.sdk as sdk

    version = getattr(sdk, "__version__", "unknown")
    return (
        "OpenHands SDK spike ok.\n"
        f"openhands.sdk version: {version}\n"
        f"goal: {goal}\n"
        "next: 新增 openhands runner，在 agentsCluster worktree 内启动 SDK/agent-server worker。"
    )
