from __future__ import annotations

from pathlib import Path
from typing import Optional

from agents_cluster.core.config import AgentConfig


def agent_capability_hint(agent: AgentConfig) -> str:
    skills = _as_list(agent.raw.get("preferred_skills"))
    mcp = _as_list(agent.raw.get("preferred_mcp"))
    lines = []
    if skills:
        lines.append("Preferred skills available to this agent: " + ", ".join(skills))
    if mcp:
        lines.append("Preferred MCP servers/tools for this agent: " + ", ".join(mcp))
    if not lines:
        return "Preferred skills/MCP: none configured."
    return "\n".join(lines)


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def master_plan_prompt(project_path: Path, goal: str, capability_hint: str = "") -> str:
    return f"""You are the master orchestrator for agentsCluster.

Project path:
{project_path}

User goal:
{goal}

{capability_hint}

Create a concise implementation plan for worker agents.

Rules:
- Do not modify files in this step.
- Inspect the repository only as needed.
- Identify likely commands to verify the work.
- Return sections: Task Breakdown, Worker Instructions, Verification Plan, Risks.
"""


def planner_prompt(planner_name: str, project_path: Path, goal: str, capability_hint: str = "") -> str:
    """
    A planning prompt for non-master agents. Each planner must produce an independent view.
    """
    return f"""You are the {planner_name} planning agent in agentsCluster.

Project path:
{project_path}

User goal:
{goal}

{capability_hint}

You are in the PLANNING stage.

Rules:
- Do NOT modify any files in this step.
- You may inspect the repository as needed.
- Be concrete: name specific files/commands, avoid generic advice.

Output format (required sections, in Chinese):
## 对需求的理解
## 推荐方案
## 需要修改/新增的文件
## 风险与依赖
## 验收标准
"""


def planner_synthesis_prompt(
    project_path: Path,
    goal: str,
    planner_outputs: str,
    capability_hint: str = "",
) -> str:
    """
    Master-only synthesis prompt: merge multiple planner outputs into a single executable plan.
    """
    return f"""You are the master orchestrator for agentsCluster.

Project path:
{project_path}

User goal:
{goal}

Planner outputs (multiple agents, may conflict):
{planner_outputs}

{capability_hint}

Your task:
- Synthesize a single final plan from the planners' independent proposals.
- De-duplicate, resolve conflicts, and make explicit tradeoffs/decisions.
- The final plan must be actionable by worker agents.

Rules:
- Do NOT modify files in this step.
- Prefer repository conventions and minimal-risk changes.

Return sections (in Chinese):
## Task Breakdown
## Worker Instructions
## Verification Plan
## Risks
"""


def worker_prompt(
    role: str,
    project_path: Path,
    goal: str,
    plan: str,
    previous_output: Optional[str] = None,
    capability_hint: str = "",
) -> str:
    prior = f"\nPrevious agent output:\n{previous_output}\n" if previous_output else ""
    return f"""You are the {role} worker in agentsCluster.

Project path:
{project_path}

User goal:
{goal}

Master plan:
{plan}
{prior}
{capability_hint}

Instructions:
- Work only inside the current repository/worktree.
- Make focused changes that directly serve the goal.
- Prefer the repository's existing patterns.
- Run relevant validation commands if you change code.
- At the end, summarize files changed, commands run, results, and unresolved issues.
"""


def review_prompt(
    project_path: Path,
    goal: str,
    plan: str,
    diff_text: str,
    status_text: str,
    capability_hint: str = "",
) -> str:
    return f"""You are the reviewer agent in agentsCluster.

Project path:
{project_path}

User goal:
{goal}

Master plan:
{plan}

Git status:
{status_text or "(clean)"}

Git diff:
{diff_text or "(no diff)"}

{capability_hint}

Review the work as a code reviewer.
Prioritize correctness, regressions, missing tests, and risky assumptions.
Return sections: Decision, Findings, Verification, Recommendation.
Decision must be exactly one of:
- APPROVE
- REQUEST_CHANGES
"""


def master_summary_prompt(
    project_path: Path,
    goal: str,
    plan: str,
    worker_log: str,
    review: str,
    diff_text: str,
    status_text: str,
    capability_hint: str = "",
) -> str:
    return f"""You are the master orchestrator producing the final report for the user.

Project path:
{project_path}

User goal:
{goal}

Plan:
{plan}

Worker log:
{worker_log}

Reviewer output:
{review}

Git status:
{status_text or "(clean)"}

Git diff:
{diff_text or "(no diff)"}

{capability_hint}

Return a concise Chinese final report with:
- 完成了什么
- 修改了哪些文件
- 验证结果
- 发现的问题或风险
- 建议用户选择 merge/diff/patch/discard 的依据

Do not claim the original project has been changed; this work is in an isolated worktree.
"""
