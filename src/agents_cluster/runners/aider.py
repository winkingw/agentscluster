from __future__ import annotations

from pathlib import Path

from .base import RunnerResult
from .subprocess_runner import SubprocessAgentRunner


class AiderRunner(SubprocessAgentRunner):
    def run(self, prompt: str, cwd: Path, output_dir: Path) -> RunnerResult:
        raw = self.config.raw.get("aider", {}) or {}
        resolved = raw.get("command")
        if not resolved:
            # Prefer a repo-local tool install if present (vendor/tools/aider/.venv),
            # so users don't have to put it on PATH.
            try:
                from agents_cluster.core.tools import get_tool_status

                status = get_tool_status("aider")
                resolved = status.local_command_path or status.command_path
            except Exception:
                resolved = None
        command = [str(resolved or "aider"), "--yes", "--no-auto-commits"]
        if self.config.model:
            command.extend(["--model", str(self.config.model)])
        if raw.get("architect"):
            command.append("--architect")
        if raw.get("read"):
            reads = raw["read"]
            if not isinstance(reads, list):
                reads = [reads]
            for item in reads:
                command.extend(["--read", str(item)])
        extra_args = raw.get("extra_args") or []
        if isinstance(extra_args, list):
            command.extend(str(item) for item in extra_args)
        command.extend(["--message", prompt])
        return self._run_command(command, "", cwd, output_dir)
