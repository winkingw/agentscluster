from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .base import AgentRunner, RunnerResult


class SubprocessAgentRunner(AgentRunner):
    def _run_command(
        self,
        command: List[str],
        prompt: str,
        cwd: Path,
        output_dir: Path,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> RunnerResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(self.env)
        if env_overrides:
            env.update(env_overrides)

        proc = subprocess.run(
            command,
            input=prompt,
            cwd=str(cwd),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.config.timeout_seconds,
        )

        output_file = output_dir / f"{self.config.name}.txt"
        output_file.write_text(
            "\n".join(
                [
                    f"# Agent: {self.config.name}",
                    f"# Command: {' '.join(command)}",
                    f"# CWD: {cwd}",
                    f"# Return code: {proc.returncode}",
                    "",
                    "## STDOUT",
                    proc.stdout,
                    "",
                    "## STDERR",
                    proc.stderr,
                ]
            ),
            encoding="utf-8",
        )

        return RunnerResult(
            agent=self.config.name,
            command=command,
            cwd=cwd,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            output_file=output_file,
        )
