from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List


def build_task_plan(goal: str, plan_text: str, workers: Iterable[str]) -> Dict:
    tasks: List[Dict] = []
    previous_id = ""
    for index, worker in enumerate(workers, start=1):
        task_id = f"task_{index:02d}_{worker}"
        tasks.append(
            {
                "id": task_id,
                "agent": worker,
                "goal": goal,
                "depends_on": [previous_id] if previous_id else [],
                "status": "pending",
                "acceptance": [
                    "仅修改当前 worktree 内的文件",
                    "遵循 master plan 和仓库既有风格",
                    "记录修改文件、验证命令、失败原因和遗留风险",
                ],
            }
        )
        previous_id = task_id
    return {
        "version": 1,
        "mode": "builtin-sequential",
        "goal": goal,
        "plan_source": "plan.md",
        "plan_excerpt": plan_text[:4000],
        "tasks": tasks,
    }


def write_task_plan(path: Path, task_plan: Dict) -> None:
    path.write_text(json.dumps(task_plan, ensure_ascii=False, indent=2), encoding="utf-8")


def write_agent_result(
    output_dir: Path,
    agent_name: str,
    output: str,
    status: str,
    task_id: str = "",
    changed_files: List[str] | None = None,
    tests_run: List[str] | None = None,
    blockers: List[str] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "version": 1,
        "agent": agent_name,
        "task_id": task_id,
        "status": status,
        "changed_files": changed_files or [],
        "tests_run": tests_run or [],
        "blockers": blockers or [],
        "summary": output[:6000],
    }
    path = output_dir / f"{agent_name}.result.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
