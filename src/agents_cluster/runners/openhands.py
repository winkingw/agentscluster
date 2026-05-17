from __future__ import annotations

from pathlib import Path

from .base import RunnerResult
from .subprocess_runner import SubprocessAgentRunner


class OpenHandsRunner(SubprocessAgentRunner):
    def run(self, prompt: str, cwd: Path, output_dir: Path) -> RunnerResult:
        raw = self.config.raw.get("openhands", {}) or {}
        command = [str(raw.get("command") or "openhands")]
        if self.config.model:
            command.extend(["--model", str(self.config.model)])
        if raw.get("workspace"):
            command.extend(["--workspace", str(raw["workspace"])])
        elif raw.get("workspace_arg", True):
            command.extend(["--workspace", str(cwd)])
        extra_args = raw.get("extra_args") or []
        if isinstance(extra_args, list):
            command.extend(str(item) for item in extra_args)
        command.extend(["--task", prompt])
        return self._run_command(command, "", cwd, output_dir)
