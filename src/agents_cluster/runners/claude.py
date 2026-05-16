from __future__ import annotations

from pathlib import Path

from .base import RunnerResult
from .subprocess_runner import SubprocessAgentRunner


class ClaudeRunner(SubprocessAgentRunner):
    def run(self, prompt: str, cwd: Path, output_dir: Path) -> RunnerResult:
        raw = self.config.raw.get("claude", {}) or {}
        command = ["claude", "--print"]
        if self.config.model:
            command.extend(["--model", str(self.config.model)])
        output_format = raw.get("output_format")
        if output_format:
            command.extend(["--output-format", str(output_format)])
        if raw.get("dangerously_skip_permissions", False):
            command.append("--dangerously-skip-permissions")
        if raw.get("bare", False):
            command.append("--bare")
        if raw.get("append_system_prompt"):
            command.extend(["--append-system-prompt", str(raw["append_system_prompt"])])
        return self._run_command(command, prompt, cwd, output_dir)
