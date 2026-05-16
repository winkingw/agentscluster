from __future__ import annotations

import os
import re
from typing import Dict, Optional

from agents_cluster.core.config import AgentConfig

from .base import AgentRunner
from .claude import ClaudeRunner
from .codex import CodexRunner
from .direct_llm import DirectLLMRunner


def create_runner(config: AgentConfig, env: Optional[Dict[str, str]] = None) -> AgentRunner:
    resolved_env = {}
    resolved_env.update(_resolve_agent_env(config))
    if env:
        resolved_env.update(env)
    runner = config.runner.lower()
    if runner == "codex":
        return CodexRunner(config, resolved_env)
    if runner in ("claude", "claudecode", "claude_code"):
        return ClaudeRunner(config, resolved_env)
    if runner in ("direct_llm", "llm", "api"):
        return DirectLLMRunner(config, resolved_env)
    raise ValueError(f"Unsupported runner for agent {config.name}: {config.runner}")


_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _resolve_agent_env(config: AgentConfig) -> Dict[str, str]:
    env_map = config.raw.get("env", {}) or {}
    if not isinstance(env_map, dict):
        return {}
    resolved: Dict[str, str] = {}
    for key, value in env_map.items():
        if value is None:
            continue
        text = str(value)
        match = _ENV_REF.match(text)
        if match:
            env_value = os.environ.get(match.group(1))
            if env_value:
                resolved[str(key)] = env_value
        elif text:
            resolved[str(key)] = text
    return resolved
