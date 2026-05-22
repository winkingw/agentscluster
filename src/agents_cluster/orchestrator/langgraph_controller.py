from __future__ import annotations

import operator
from pathlib import Path
from typing import Any, Annotated, Callable, Dict, List, Optional, Tuple, TypedDict

from .task_protocol import build_task_plan


PlannerRunner = Callable[[str], Dict[str, Any]]
SynthesisRunner = Callable[[List[Dict[str, Any]]], str]
WorkerAgent = Callable[[str, str, str], str]
ReviewerAgent = Callable[[int, str, str], str]
ReworkAgent = Callable[[int, str], str]
TesterReworkAgent = Callable[[int, str], Optional[str]]
SummaryAgent = Callable[[str, str, str, str], str]
RefreshRepoState = Callable[[], Tuple[str, str]]
ReviewDecision = Callable[[str], bool]


class PlanningState(TypedDict):
    goal: str
    worktree_path: str
    workers: List[str]
    planning_agents: List[str]
    planner_outputs: Annotated[List[Dict[str, Any]], operator.add]
    plan: str
    task_plan: Dict


class ExecutionState(TypedDict):
    goal: str
    plan: str
    worktree_path: str
    tasks: List[Dict]
    max_rework_rounds: int
    include_tester_rework: bool
    worker_index: int
    review_round: int
    previous_output: str
    worker_log_parts: List[str]
    status_text: str
    diff_text: str
    review: str
    needs_rework: bool
    summary: str


def plan_with_langgraph(
    goal: str,
    worktree_path: Path,
    workers: List[str],
    planning_agents: List[str],
    run_planner: PlannerRunner,
    run_synthesis: SynthesisRunner,
) -> Dict:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("LangGraph is not installed. Run: .\\scripts\\install_optional_deps.ps1") from exc

    def make_planner_node(agent_name: str):
        def planner_node(_state: PlanningState) -> Dict:
            # Never raise here: a single planner failure must not kill the whole plan graph.
            try:
                record = run_planner(agent_name)
            except Exception as exc:
                record = {
                    "agent": agent_name,
                    "status": "failed",
                    "error": str(exc),
                }
            return {"planner_outputs": [record]}

        return planner_node

    def master_synthesis_node(state: PlanningState) -> Dict:
        plan = run_synthesis(list(state.get("planner_outputs") or []))
        return {"plan": plan}

    def task_graph_node(state: PlanningState) -> Dict:
        task_plan = build_task_plan(state["goal"], state["plan"], state["workers"])
        task_plan["mode"] = "langgraph-sequential"
        return {"task_plan": task_plan}

    graph = StateGraph(PlanningState)
    planner_node_names: List[str] = []
    for planner in planning_agents:
        node_name = f"planner_{planner}"
        planner_node_names.append(node_name)
        graph.add_node(node_name, make_planner_node(planner))
        graph.add_edge(START, node_name)

    graph.add_node("master_synthesis", master_synthesis_node)
    graph.add_node("task_graph", task_graph_node)

    if planner_node_names:
        # Fan-in: wait for all planners to complete before synthesis.
        graph.add_edge(planner_node_names, "master_synthesis")
    else:
        # Defensive: if no planners were configured, still run synthesis (it should error clearly).
        graph.add_edge(START, "master_synthesis")

    graph.add_edge("master_synthesis", "task_graph")
    graph.add_edge("task_graph", END)

    compiled = graph.compile()
    initial = {
        "goal": goal,
        "worktree_path": str(worktree_path),
        "workers": workers,
        "planning_agents": planning_agents,
        "planner_outputs": [],
        "plan": "",
        "task_plan": {},
    }

    # Prefer best-effort parallelism; fall back if this LangGraph version doesn't accept the config.
    try:
        return compiled.invoke(initial, {"max_concurrency": max(1, len(planning_agents))})
    except TypeError:
        return compiled.invoke(initial)


def execute_with_langgraph(
    *,
    goal: str,
    plan: str,
    worktree_path: Path,
    task_plan: Dict,
    max_rework_rounds: int,
    include_tester_rework: bool,
    run_worker: WorkerAgent,
    run_reviewer: ReviewerAgent,
    run_rework: ReworkAgent,
    run_tester_rework: TesterReworkAgent,
    summarize: SummaryAgent,
    refresh_repo_state: RefreshRepoState,
    review_requests_changes: ReviewDecision,
) -> Dict:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("LangGraph is not installed. Run: .\\scripts\\install_optional_deps.ps1") from exc

    tasks = [
        task
        for task in task_plan.get("tasks", [])
        if isinstance(task, dict) and str(task.get("agent", "")).strip()
    ]

    def worker_node(state: ExecutionState) -> Dict:
        index = int(state["worker_index"])
        if index >= len(state["tasks"]):
            return {}
        task = state["tasks"][index]
        agent_name = str(task.get("agent") or "")
        task_id = str(task.get("id") or "")
        output = run_worker(agent_name, task_id, state["previous_output"])
        return {
            "worker_index": index + 1,
            "previous_output": output[-6000:],
            "worker_log_parts": [*state["worker_log_parts"], f"## {agent_name}\n\n{output}"],
        }

    def refresh_state_node(_state: ExecutionState) -> Dict:
        status_text, diff_text = refresh_repo_state()
        return {"status_text": status_text, "diff_text": diff_text}

    def review_node(state: ExecutionState) -> Dict:
        review = run_reviewer(int(state["review_round"]), state["diff_text"], state["status_text"])
        return {
            "review": review,
            "needs_rework": bool(review_requests_changes(review)),
        }

    def rework_node(state: ExecutionState) -> Dict:
        next_round = int(state["review_round"]) + 1
        output = run_rework(next_round, state["review"])
        return {
            "review_round": next_round,
            "previous_output": output[-6000:],
            "worker_log_parts": [*state["worker_log_parts"], f"## coder rework {next_round}\n\n{output}"],
        }

    def tester_rework_node(state: ExecutionState) -> Dict:
        round_id = int(state["review_round"])
        output = run_tester_rework(round_id, state["review"])
        if not output:
            return {}
        return {
            "previous_output": output[-6000:],
            "worker_log_parts": [*state["worker_log_parts"], f"## tester rework {round_id}\n\n{output}"],
        }

    def summary_node(state: ExecutionState) -> Dict:
        worker_log = "\n\n".join(state["worker_log_parts"])
        summary = summarize(worker_log, state["review"], state["diff_text"], state["status_text"])
        return {"summary": summary}

    def route_after_workers(state: ExecutionState) -> str:
        return "worker" if int(state["worker_index"]) < len(state["tasks"]) else "refresh"

    def route_after_review(state: ExecutionState) -> str:
        if not state["needs_rework"]:
            return "summary"
        if int(state["review_round"]) >= int(state["max_rework_rounds"]):
            return "summary"
        return "rework"

    def route_after_rework(state: ExecutionState) -> str:
        return "tester_rework" if state["include_tester_rework"] else "refresh"

    graph = StateGraph(ExecutionState)
    graph.add_node("worker", worker_node)
    graph.add_node("refresh", refresh_state_node)
    graph.add_node("review", review_node)
    graph.add_node("rework", rework_node)
    graph.add_node("tester_rework", tester_rework_node)
    graph.add_node("summary", summary_node)

    graph.add_edge(START, "worker")
    graph.add_conditional_edges("worker", route_after_workers, {"worker": "worker", "refresh": "refresh"})
    graph.add_edge("refresh", "review")
    graph.add_conditional_edges("review", route_after_review, {"summary": "summary", "rework": "rework"})
    graph.add_conditional_edges(
        "rework",
        route_after_rework,
        {"tester_rework": "tester_rework", "refresh": "refresh"},
    )
    graph.add_edge("tester_rework", "refresh")
    graph.add_edge("summary", END)

    compiled = graph.compile()
    return compiled.invoke(
        {
            "goal": goal,
            "plan": plan,
            "worktree_path": str(worktree_path),
            "tasks": tasks,
            "max_rework_rounds": max(0, int(max_rework_rounds)),
            "include_tester_rework": bool(include_tester_rework),
            "worker_index": 0,
            "review_round": 0,
            "previous_output": "",
            "worker_log_parts": [],
            "status_text": "",
            "diff_text": "",
            "review": "",
            "needs_rework": False,
            "summary": "",
        }
    )
