from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .base import AgentRunner, RunnerResult


@dataclass(frozen=True)
class FakeRunnerConfig:
    """
    A deterministic runner for E2E dry tests.

    It can optionally mutate files under the provided cwd to simulate code edits.
    """

    files_to_touch: Optional[List[str]] = None


class FakeRunner(AgentRunner):
    def __init__(self, config, env: Optional[Dict[str, str]] = None) -> None:
        super().__init__(config, env)
        raw = (config.raw or {}).get("fake", {}) if isinstance(config.raw, dict) else {}
        files = raw.get("files_to_touch")
        if files and not isinstance(files, list):
            files = [str(files)]
        self.fake = FakeRunnerConfig(files_to_touch=[str(x) for x in files] if files else None)

    def run(self, prompt: str, cwd: Path, output_dir: Path) -> RunnerResult:
        output_dir.mkdir(parents=True, exist_ok=True)

        stdout = self._produce_output(prompt, cwd)
        output_file = output_dir / f"{self.config.name}.txt"
        output_file.write_text(stdout + "\n", encoding="utf-8")
        return RunnerResult(
            agent=self.config.name,
            command=["fake-runner", self.config.name],
            cwd=cwd,
            returncode=0,
            stdout=stdout,
            stderr="",
            output_file=output_file,
        )

    def _produce_output(self, prompt: str, cwd: Path) -> str:
        name = (self.config.name or "").lower()
        lower = prompt.lower()

        # Master summary: produce a short report.
        if name == "master" and ("final report" in lower or "final summary" in lower):
            return (
                "## Summary (dry-e2e)\n\n"
                "- 已完成：生成计划、执行 worker、review approve、生成 summary。\n"
                "- 产物：plan.md / task-plan.json / diff.patch / status.txt / summary.md\n"
            )

        # Master planning / synthesis prompts.
        if name == "master" and (
            "planner outputs" in prompt
            or "synthesize" in lower
            or "planning stage" in lower
            or "master plan" in lower
        ):
            return (
                "# Plan (dry-e2e)\n\n"
                "## Task Breakdown\n"
                "1. 变更一个文件，产出可见 diff。\n"
                "2. 记录改动与验证点。\n\n"
                "## Worker Instructions\n"
                "- architect/coder/tester: 各自完成一部分变更并记录结果。\n\n"
                "## Verification Plan\n"
                "- git status / git diff\n\n"
                "## Risks\n"
                "- dry-e2e\n"
            )

        # Planners: return structured planning output, but do NOT touch files.
        if name in ("architect", "coder", "tester") and ("planning agent" in lower or "planning stage" in lower):
            return (
                "## 对需求的理解\n"
                f"- planner={name}\n\n"
                "## 推荐方案\n"
                "- dry-e2e planner proposal\n\n"
                "## 需要修改/新增的文件\n"
                "- README.md\n\n"
                "## 风险与依赖\n"
                "- none (dry-e2e)\n\n"
                "## 验收标准\n"
                "- 能看到 diff.patch 里出现 touched by 标记\n"
            )

        # Workers: touch file(s) to generate a diff.
        if name in ("architect", "coder", "tester"):
            self._touch_files(cwd, name)
            return f"{name}: completed (dry-e2e)\nchanged_files: {', '.join(self.fake.files_to_touch or ['README.md'])}"

        # Reviewer: always approve for dry E2E.
        if name == "reviewer":
            return "DECISION: APPROVE\n\nnotes: dry-e2e reviewer approved."

        # Default.
        return f"{self.config.name}: ok (dry-e2e)"

    def _touch_files(self, cwd: Path, agent_name: str) -> None:
        paths = self.fake.files_to_touch or ["README.md"]
        for rel in paths:
            target = (cwd / rel).resolve()
            if cwd.resolve() not in target.parents and cwd.resolve() != target:
                # Safety: never write outside worktree cwd.
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
            marker = f"\n\n# touched by {agent_name}\n"
            if marker.strip() not in existing:
                target.write_text(existing + marker, encoding="utf-8")
