# agentsCluster 开源底座审查

本文总结了前期讨论过的几个开源或半开源方案，并说明为什么 `agentsCluster` 当前采用“本地总控壳 + 可替换底层 runner / orchestrator”的路线。

## 初始目标回顾

目标不是单纯跑一个 agent，而是做一套可控的本地多 agent 集群：

- 用户和总控 agent 直接交流
- 总控负责拆任务、派 worker、汇总结果、审核质量
- 不同 agent 可以绑定不同模型 / API
- 每次任务能明确工作目录
- 使用 `git worktree` 隔离修改
- 最终由用户确认 `diff / patch / merge / discard`
- 后续能挂前端，直接查询项目、run、事件和产物

## 方案对比

| 方案 | 适合做什么 | 优点 | 局限 | 在 agentsCluster 中的定位 |
| --- | --- | --- | --- | --- |
| LangGraph | 编排多阶段流程、状态机、人工确认 | 适合做复杂 orchestration | 需要重写当前 controller 逻辑 | 作为可插拔 orchestrator |
| OpenAI Agents SDK | handoff、tool/MCP、session、tracing | 协议层成熟，适合多 agent 协作 | 不负责 git/worktree/apply 边界 | 作为 agent 协议层候选 |
| OpenHands | 编码 agent、容器 / Docker 工作区 | 对真实编码任务比较强 | 依赖较重，Windows/Docker 兼容要单独验证 | 作为重型 worker 候选 |
| aider | 单仓库代码修改 worker | 轻量、成熟、适合 coder 角色 | 不适合做总控和完整编排 | 作为 `coder` 类 worker 候选 |
| SWE-agent | issue / bugfix 型自动修复 | 对缺陷修复工作流成熟 | 不适合通用多 agent 主控 | 作为专项 worker 候选 |
| CrewAI | 角色式多 agent 组织 | 上手快 | 对 git/worktree/人工确认这类工程边界不够强 | 不作为主路线 |
| Codex CLI | 高质量代码主控 / 审核 | 适合作 master / reviewer | 是否继承本机 skills / MCP 取决于 CLI 配置 | 当前默认总控 |
| Claude Code | worker 执行、工具调用 | 适合作 architect / coder / tester | 同样受 CLI 配置和 provider 约束 | 当前默认 worker |

## 当前路线为什么成立

核心思路是：

- `agentsCluster` 自己负责工程边界和运行记录
- `Codex / Claude / direct_llm / 未来的 OpenHands / aider` 只负责执行 agent 本身

这样拆分有几个好处：

1. 不把整个系统绑死在某一个框架上  
2. `git worktree`、事件流、人工确认、API 接口这些关键边界由我们自己掌控  
3. 以后切换模型、CLI、MCP、skills 或底层编排框架时，不需要推翻整个系统  

## 当前结论

最适合你的不是“直接用某一个现成框架替代全部系统”，而是：

- 保留 `agentsCluster` 作为本地总控壳
- 默认用 `Codex CLI` 做 `master / reviewer`
- 默认用 `Claude Code` 做 `architect / coder / tester`
- 按需接入 `LangGraph`、`OpenAI Agents SDK`、`OpenHands`、`aider`

这比直接押注某一个单一框架稳得多，也更符合你一开始的要求：可切模型、可控工作区、可审核、可恢复、可接前端。

## 已落地部分

当前仓库已经具备这些能力：

- 项目注册与删除注册
- `doctor` 环境检查
- `test-agent` 单 agent 检测
- 主控规划 / worker 执行 / reviewer 审核 / summary 汇总
- 自动返工
- `resume / retry-plan / retry-execute`
- 项目级串行队列
- HTTP API 与 SSE
- `diff / patch / merge / discard`

## 建议的后续扩展顺序

### 1. LangGraph 编排替换 builtin controller

目标：

- 复用当前 run/event/artifact 协议
- 把当前线性流程表达成图
- 为后面更复杂的 worker 协作、分支重试、人工节点做准备

### 2. OpenAI Agents SDK 接入总控链路

目标：

- 用更标准的 handoff / tool / tracing 协议替换部分手写 prompt 协议
- 继续保留 `agentsCluster` 的 worktree / apply / queue / API 外壳

### 3. OpenHands / aider 作为可选 worker（非必需）

目标：

- 把 `coder` 角色做成可切换 runner
- 在复杂编码任务上比较 `claude`、`aider`、`openhands` 的效果和成本

### 4. 前端

有了当前稳定 HTTP API 后，前端可以直接实现：

- 项目选择
- 新建 run
- 事件时间线
- 计划预览
- 产物查看
- diff / merge / discard 确认

## 最终建议

继续沿着下面的架构演进：

- `agentsCluster` 负责工程控制面
- `Codex / Claude / direct_llm` 负责主执行面（核心）
- `OpenHands / aider` 仅作为可选扩展（对比与补强，不是必要条件）
- `LangGraph / OpenAI Agents SDK` 负责编排与协议增强

这条路线最符合你要的“像 cc cli / codex cli 那样交流，但背后是多 agent 协作”的目标。
