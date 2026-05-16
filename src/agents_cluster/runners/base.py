from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from agents_cluster.core.config import AgentConfig


@dataclass
class RunnerResult:
    agent: str
    command: List[str]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str
    output_file: Path

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class AgentRunner:
    def __init__(self, config: AgentConfig, env: Optional[Dict[str, str]] = None) -> None:
        self.config = config
        self.env = env or {}

    def run(self, prompt: str, cwd: Path, output_dir: Path) -> RunnerResult:
        raise NotImplementedError
