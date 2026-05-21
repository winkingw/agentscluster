from __future__ import annotations

from agents_cluster.core.integrations import integration_status_map, list_integrations
from agents_cluster.core.config import AgentConfig
from agents_cluster.runners.factory import create_runner
from agents_cluster.runners.aider import AiderRunner
from agents_cluster.runners.openhands import OpenHandsRunner


def main() -> None:
    statuses = list_integrations()
    names = {status.name for status in statuses}
    assert {"langgraph", "openai-agents", "openhands", "aider", "swe-agent"}.issubset(names)
    status_map = integration_status_map()
    assert status_map["langgraph"].install_hint

    aider = create_runner(
        AgentConfig(
            name="aider_coder",
            runner="aider",
            model="deepseek/deepseek-chat",
            role="coder",
            timeout_seconds=10,
            raw={"aider": {"extra_args": []}},
        )
    )
    assert isinstance(aider, AiderRunner)

    openhands = create_runner(
        AgentConfig(
            name="openhands_coder",
            runner="openhands",
            model="deepseek-v4-flash",
            role="coder",
            timeout_seconds=10,
            raw={"openhands": {"workspace_arg": True}},
        )
    )
    assert isinstance(openhands, OpenHandsRunner)

    print("integration smoke ok")


if __name__ == "__main__":
    main()
