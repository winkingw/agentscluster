from __future__ import annotations

from pathlib import Path

from agents_cluster.orchestrator.langgraph_controller import plan_with_langgraph


def main() -> None:
    result = plan_with_langgraph(
        goal="验证 LangGraph 计划阶段",
        worktree_path=Path.cwd(),
        workers=["architect", "coder", "tester"],
        plan_agent=lambda goal, worktree: f"Plan for {goal} in {worktree}",
    )
    assert result["plan"].startswith("Plan for 验证 LangGraph")
    assert result["task_plan"]["mode"] == "builtin-sequential"
    assert [task["agent"] for task in result["task_plan"]["tasks"]] == ["architect", "coder", "tester"]
    print("langgraph smoke ok")


if __name__ == "__main__":
    main()
