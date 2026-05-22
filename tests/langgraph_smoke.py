from __future__ import annotations

from pathlib import Path

from agents_cluster.orchestrator.langgraph_controller import plan_with_langgraph


def main() -> None:
    result = plan_with_langgraph(
        goal="验证 LangGraph 计划阶段",
        worktree_path=Path.cwd(),
        workers=["architect", "coder", "tester"],
        planning_agents=["architect", "coder", "tester"],
        run_planner=lambda name: {"agent": name, "status": "completed", "output": f"planner({name}) ok"},
        run_synthesis=lambda outputs: f"Plan for {len(outputs)} planners",
    )
    assert result["plan"].startswith("Plan for 3 planners")
    assert len(result.get("planner_outputs", [])) == 3
    assert result["task_plan"]["mode"] == "langgraph-sequential"
    assert [task["agent"] for task in result["task_plan"]["tasks"]] == ["architect", "coder", "tester"]
    print("langgraph smoke ok")


if __name__ == "__main__":
    main()
