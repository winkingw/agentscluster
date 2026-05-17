# agentsCluster 开源底座审查

本文记录 agentsCluster 后续扩展时可复用的开源项目，以及它们与最初目标的匹配程度。

## 最初目标

- 用户和总控 agent 交流编程想法。
- 总控拆分任务、分派 worker、检查 worker 成果。
- worker 可以使用不同模型/API，并且后续可在配置中切换。
- 每次项目运行时选择目标项目目录。
- 使用 git worktree 隔离修改。
- 总控汇总“做了什么、有什么问题、如何处理”，再让用户确认 diff/patch/merge/discard。
- 后续有前端，前端通过稳定 API 查询项目、任务、运行状态和结果。

## 候选项目结论

| 项目 | 适配点 | 局限 | agentsCluster 用法 |
| --- | --- | --- | --- |
| LangGraph | 动态任务图、状态机、human-in-the-loop、长期任务恢复 | 引入新调度模型，需要把当前 controller 拆成节点 | 作为 `orchestrator: langgraph` 的候选实现 |
| OpenAI Agents SDK | handoff、MCP、tracing、guardrails、sessions | 更偏 agent 协议层，不直接解决 git/worktree/apply | 作为 agent 协议层，替代手写 prompt/runner 协议 |
| OpenHands / Software Agent SDK | 成熟编码 agent、REST/API、Docker 工作区、GUI | 依赖较重，Windows/Docker/模型兼容需要验证 | 作为 `runner: openhands` worker 接入 |
| SWE-agent | issue/bugfix 型自动修复，patch 工作流成熟 | 不适合作总控，也不适合通用交互式任务 | 作为专项 worker 候选 |
| aider | 轻量、成熟、适合单仓库代码修改 | 多 agent 调度和审核要由 agentsCluster 负责 | 作为 `runner: aider` coder worker |
| Codex CLI | 高质量代码总控/审核，已在本机配置 | CLI 子进程是否继承 Desktop 当前技能/MCP 取决于 Codex CLI 配置 | 继续作为 master/reviewer 默认 runner |
| Claude Code | 适合 worker，支持 MCP/skills | 产品/API 依赖，不是完全免费本地开源底座 | 继续作为 worker 默认 runner |
| CrewAI | 角色型 multi-agent 流程简单 | 对 git worktree、diff、merge、代码审核没有原生优势 | 暂不作为主路线 |
| GitHub Copilot coding agent / Agent HQ | 产品形态值得参考 | 不是免费开源，本地可控性弱 | 只参考交互和异步任务体验 |

## 推荐路线

保留 agentsCluster 作为本地总控壳：

- 配置、密钥、项目注册、doctor、运行记录由 agentsCluster 管。
- git worktree、diff、patch、merge/discard 的安全边界由 agentsCluster 管。
- 总控/worker/reviewer 的底层实现逐步适配 LangGraph、OpenAI Agents SDK、OpenHands、aider 等。

这样做的好处是不会把项目绑死到单一框架上，也不会破坏当前已经可用的 Codex/Claude CLI 流程。

## 当前已落地

- `settings.orchestrator: builtin` 配置位。
- `agentsCluster integrations list` 检查可选框架是否安装。
- `agentsCluster integrations spike langgraph` 做 LangGraph 本地无模型验证。
- `agentsCluster integrations spike openai-agents` 做 OpenAI Agents SDK 本地无模型验证。
- `agentsCluster integrations spike openhands` 做 OpenHands SDK 本地无模型验证。
- 新增 `runner: aider` 和 `runner: openhands` 的适配入口。
- 当前 builtin 流程会写出 `runs/<run_id>/task-plan.json` 和 `agent_outputs/*.result.json`，给后续前端和状态图调度复用。

## 下一步实现顺序

1. 用 LangGraph 复刻当前 builtin 流程，输出同样的 run/event/task/result 文件。
2. 给 OpenAI Agents SDK 增加真实 runner，优先验证 MCP、handoff 和 tracing。
3. 验证 OpenHands SDK 在 agentsCluster worktree 内完成一个小任务，确认模型配置和 Windows/Docker 兼容性。
4. 扩展 HTTP API：启动任务、确认计划、取消任务、查看事件、查看 diff、apply。
5. 前端接 API，做项目选择、任务输入、agent 时间线、日志和 diff 查看。
