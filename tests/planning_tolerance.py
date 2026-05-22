from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from agents_cluster.core import db
from agents_cluster.core.paths import RUNS_DIR
from agents_cluster.orchestrator import controller
from agents_cluster.workspace import git_ops


def run(cmd, cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())


def main() -> None:
    db.init_db()
    original_run_agent = controller._run_agent

    try:
        def fake_run_agent(_config, agent_name, prompt, _cwd, _output_dir):
            lower = str(prompt or "").lower()
            # Fail exactly one planner; master should still be able to synthesize using the others.
            if agent_name == "coder" and ("planning agent" in lower or "planning stage" in lower):
                raise RuntimeError("planner failed intentionally (coder)")
            if agent_name in ("architect", "tester") and ("planning agent" in lower or "planning stage" in lower):
                return (
                    "## 对需求的理解\n- ok\n\n"
                    "## 推荐方案\n- ok\n\n"
                    "## 需要修改/新增的文件\n- README.md\n\n"
                    "## 风险与依赖\n- none\n\n"
                    "## 验收标准\n- ok\n"
                )
            if agent_name == "master" and ("planner outputs" in prompt or "synthesize" in lower):
                return "plan ok (synthesized)"
            return f"{agent_name} ok"

        controller._run_agent = fake_run_agent

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            run(["git", "init"], repo)
            run(["git", "config", "user.email", "agentsCluster@example.local"], repo)
            run(["git", "config", "user.name", "agentsCluster Planning Test"], repo)
            (repo / "README.md").write_text("# planning tolerance\n", encoding="utf-8")
            run(["git", "add", "README.md"], repo)
            run(["git", "commit", "-m", "init"], repo)

            config = {
                "settings": {
                    "orchestrator": "builtin",
                    "default_timeout_seconds": 60,
                    "max_rework_rounds": 0,
                    # default planners (architect/coder/tester) should apply without explicit config
                },
                "agents": {
                    # runner values are irrelevant because we monkeypatch controller._run_agent
                    "master": {"runner": "fake", "model": "fake", "role": "orchestrator", "timeout_seconds": 60, "fake": {}},
                    "architect": {"runner": "fake", "model": "fake", "role": "architect", "timeout_seconds": 60, "fake": {}},
                    "coder": {"runner": "fake", "model": "fake", "role": "coder", "timeout_seconds": 60, "fake": {}},
                    "tester": {"runner": "fake", "model": "fake", "role": "tester", "timeout_seconds": 60, "fake": {}},
                    "reviewer": {"runner": "fake", "model": "fake", "role": "reviewer", "timeout_seconds": 60, "fake": {}},
                },
                "projects": [],
            }

            project = {"name": "planning-tolerance", "path": str(repo)}
            run_record = controller.create_run(config, project, "planning tolerance goal", workers=["architect", "coder", "tester"])
            run_id = str(run_record["id"])

            result = controller.plan_run(config, run_id)
            assert result["status"] == "waiting_approval"
            assert "plan ok" in result["plan"]

            task_plan = json.loads((RUNS_DIR / run_id / "task-plan.json").read_text(encoding="utf-8"))
            assert task_plan.get("planning_mode") == "multi-agent"
            outputs = task_plan.get("planner_outputs") or []
            assert len(outputs) >= 2
            assert any(item.get("agent") == "coder" and item.get("status") == "failed" for item in outputs)
            assert any(item.get("status") == "completed" for item in outputs)

            # Cleanup: remove worktree to avoid accumulating during repeated test runs.
            worktree = Path(controller._require_run(run_id)["worktree_path"])
            if worktree.exists():
                git_ops.remove_worktree(repo, worktree, force=True)

        print("planning tolerance ok")
    finally:
        controller._run_agent = original_run_agent


if __name__ == "__main__":
    main()

