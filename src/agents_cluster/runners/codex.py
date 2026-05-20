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
        last_message_path = output_dir / f"{self.config.name}.last_message.txt"
        command.extend(["-o", str(last_message_path)])
        command.append("-")
        result = self._run_command(command, prompt, cwd, output_dir)

        if last_message_path.exists():
            message = last_message_path.read_text(encoding="utf-8", errors="replace").strip()
            if message:
                result.stdout = message
                result.output_file.write_text(
                    "\n".join(
                        [
                            f"# Agent: {result.agent}",
                            f"# Command: {' '.join(result.command)}",
                            f"# CWD: {result.cwd}",
                            f"# Return code: {result.returncode}",
                            "",
                            "## STDOUT",
                            result.stdout,
                            "",
                            "## STDERR",
                            result.stderr,
                        ]
                    ),
                    encoding="utf-8",
                )

        return result
