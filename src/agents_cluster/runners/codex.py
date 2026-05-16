from __future__ import annotations

from pathlib import Path

from .base import RunnerResult
from .subprocess_runner import SubprocessAgentRunner


class CodexRunner(SubprocessAgentRunner):
    def run(self, prompt: str, cwd: Path, output_dir: Path) -> RunnerResult:
        raw = self.config.raw.get("codex", {}) or {}
        command = ["codex", "exec", "-C", str(cwd), "--color", "never"]
        if self.config.model:
            command.extend(["-m", str(self.config.model)])
        if raw.get("profile"):
            command.extend(["-p", str(raw["profile"])])
        sandbox = raw.get("sandbox")
        if sandbox:
            command.extend(["-s", str(sandbox)])
        approval_policy = raw.get("approval_policy")
        if approval_policy:
            command.extend(["-c", f"approval_policy=\"{approval_policy}\""])
        reasoning_effort = raw.get("model_reasoning_effort")
        if reasoning_effort:
            command.extend(["-c", f"model_reasoning_effort=\"{reasoning_effort}\""])
        if raw.get("skip_git_repo_check", False):
            command.append("--skip-git-repo-check")
        if raw.get("ephemeral", True):
            command.append("--ephemeral")
        command.append("-")
        return self._run_command(command, prompt, cwd, output_dir)
