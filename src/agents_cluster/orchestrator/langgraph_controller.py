from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, TypedDict

from .task_protocol import build_task_plan


PlanAgent = Callable[[str, Path], str]


class PlanningState(TypedDict):
    goal: str
    worktree_path: str
    workers: List[str]
    plan: str
    task_plan: Dict


def plan_with_langgraph(
    goal: str,
    worktree_path: Path,
    workers: List[str],
    plan_agent: PlanAgent,
) -> Dict:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("LangGraph is not installed. Run: .\\scripts\\install_optional_deps.ps1") from exc

    def master_plan_node(state: PlanningState) -> Dict:
        plan = plan_agent(state["goal"], Path(state["worktree_path"]))
        return {"plan": plan}

    def task_graph_node(state: PlanningState) -> Dict:
        return {"task_plan": build_task_plan(state["goal"], state["plan"], state["workers"])}

    graph = StateGraph(PlanningState)
    graph.add_node("master_plan", master_plan_node)
    graph.add_node("task_graph", task_graph_node)
    graph.add_edge(START, "master_plan")
    graph.add_edge("master_plan", "task_graph")
    graph.add_edge("task_graph", END)

    compiled = graph.compile()
    return compiled.invoke(
        {
            "goal": goal,
            "worktree_path": str(worktree_path),
            "workers": workers,
            "plan": "",
            "task_plan": {},
        }
    )
