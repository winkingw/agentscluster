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
        permission_mode = raw.get("permission_mode", "acceptEdits")
        if permission_mode:
            command.extend(["--permission-mode", str(permission_mode)])
        output_format = raw.get("output_format")
        if output_format:
            command.extend(["--output-format", str(output_format)])
        if raw.get("dangerously_skip_permissions", False):
            command.append("--dangerously-skip-permissions")
        allowed_tools = raw.get("allowed_tools")
        if isinstance(allowed_tools, list) and allowed_tools:
            command.extend(["--allowed-tools", ",".join(str(item) for item in allowed_tools if str(item).strip())])
        if raw.get("bare", False):
            command.append("--bare")
        if raw.get("append_system_prompt"):
            command.extend(["--append-system-prompt", str(raw["append_system_prompt"])])
        return self._run_command(command, prompt, cwd, output_dir)
