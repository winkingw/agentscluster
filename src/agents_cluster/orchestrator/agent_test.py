from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from agents_cluster.core.config import get_agent
from agents_cluster.core.paths import RUNS_DIR
from agents_cluster.core.time import now_id
from agents_cluster.runners.factory import create_runner

from .prompts import agent_capability_hint


def test_agent(
    config: Dict,
    agent_name: str,
    cwd: Optional[Path] = None,
    prompt: Optional[str] = None,
    dry_run: bool = False,
) -> int:
    agent_config = get_agent(config, agent_name)
    cwd = (cwd or Path.cwd()).resolve()

    print(f"Agent: {agent_name}")
    print(f"Runner: {agent_config.runner}")
    print(f"Model: {agent_config.model}")
    print(f"CWD: {cwd}")
    print(agent_capability_hint(agent_config))

    if dry_run:
        print("Dry run only; no model call was made.")
        return 0

    run_dir = RUNS_DIR / f"test_agent_{now_id()}_{uuid4().hex[:6]}_{agent_name}"
    output_dir = run_dir / "agent_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    test_prompt = prompt or f"""You are being tested by agentsCluster.

Working directory:
{cwd}

Do not modify files.
Reply with:
- your role
- whether you can inspect this directory
- one sentence confirming the runner is working
"""
    runner = create_runner(agent_config)
    result = runner.run(test_prompt, cwd, output_dir)
    print(f"Return code: {result.returncode}")
    print(f"Output file: {result.output_file}")
    if result.stdout.strip():
        print("")
        print(result.stdout.strip())
    if result.stderr.strip():
        print("")
        print("STDERR:")
        print(result.stderr.strip())
    return result.returncode
