from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .base import AgentRunner, RunnerResult


class DirectLLMRunner(AgentRunner):
    def run(self, prompt: str, cwd: Path, output_dir: Path) -> RunnerResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        raw = self.config.raw.get("direct_llm", {}) or {}
        base_url = str(raw.get("base_url", "")).rstrip("/")
        api_key_env = str(raw.get("api_key_env", ""))
        api_key = self.env.get(api_key_env) or os.environ.get(api_key_env, "")

        command = ["direct_llm", base_url, str(self.config.model or "")]
        if not base_url or not api_key:
            message = (
                f"Direct LLM runner is not configured for {self.config.name}. "
                f"base_url={base_url!r}, api_key_env={api_key_env!r}."
            )
            return self._write_result(command, cwd, output_dir, 2, "", message)

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": f"You are the {self.config.role} worker."},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(raw.get("temperature", 0.2)),
        }
        request = urllib.request.Request(
            f"{base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            text = data["choices"][0]["message"]["content"]
            return self._write_result(command, cwd, output_dir, 0, text, "")
        except (urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
            return self._write_result(command, cwd, output_dir, 1, "", str(exc))

    def _write_result(
        self,
        command,
        cwd: Path,
        output_dir: Path,
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> RunnerResult:
        output_file = output_dir / f"{self.config.name}.txt"
        output_file.write_text(
            "\n".join(
                [
                    f"# Agent: {self.config.name}",
                    f"# Command: {' '.join(command)}",
                    f"# CWD: {cwd}",
                    f"# Return code: {returncode}",
                    "",
                    "## STDOUT",
                    stdout,
                    "",
                    "## STDERR",
                    stderr,
                ]
            ),
            encoding="utf-8",
        )
        return RunnerResult(self.config.name, command, cwd, returncode, stdout, stderr, output_file)
