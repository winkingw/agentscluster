# agentsCluster

`agentsCluster` 是一个本地多 agent 编程调度器。它负责管理项目注册、`git worktree` 隔离、运行队列、产物落盘、人工确认以及最终的 `diff / patch / merge / discard` 处理。

当前默认形态是：

- `master` / `reviewer` 走 `codex`
- `architect` / `coder` / `tester` 走 `claude`
- 也支持 `direct_llm` 直连 OpenAI-compatible API
- 每次运行都在独立 `worktree` 内完成，不直接污染原仓库工作区
- 规划、执行、重试、恢复都能通过 CLI 或 HTTP API 驱动
- 同一项目支持连续提交多个 run，系统会按项目维度串行排队执行

## 当前已实现

- 项目注册、列出、删除注册
- `doctor` 环境检查
- `test-agent <name>` 单独测试某个 agent
- 主控规划 -> worker 执行 -> reviewer 审核 -> master 总结
- reviewer 不通过时自动回派 `coder` 返工，并可追加 `tester`
- `runs resume / retry-plan / retry-execute`
- `runs artifacts`、HTTP artifacts 查询
- SSE 事件流
- `apply` 支持 `diff`、`patch`、`merge`、`discard`
- 面向前端的稳定 HTTP API

## 环境安装

推荐使用独立 conda 环境：

```powershell
cd D:\programs\agentsCluster
.\scripts\install.ps1
```

或手动安装：

```powershell
cd D:\programs\agentsCluster
conda env create -f environment.yml
conda activate agentsCluster
pip install -e .
agentsCluster init
```

如果命令未进入 PATH，可用以下方式运行：

```powershell
conda run -n agentsCluster agentsCluster doctor
.\agentsCluster.ps1 doctor
$env:PYTHONPATH="D:\programs\agentsCluster\src"; python -m agents_cluster.cli doctor
```

## 配置文件

真实本地配置：

```text
D:\programs\agentsCluster\config\agents.yaml
```

示例配置：

```text
D:\programs\agentsCluster\config\agents.example.yaml
```

密钥文件：

```text
D:\programs\agentsCluster\.env
```

以下内容默认不上传 GitHub：

- `.env`
- `config/agents.yaml`
- `agentsCluster.db`
- `runs/`
- `worktrees/`
- `patches/`
- 其他常见敏感文件

## API Key 需要几个

通常按 provider 计，不需要每个 agent 单独一套。

- OpenAI / Codex 路线：1 个 `OPENAI_API_KEY`
- DeepSeek 路线：1 个 `DEEPSEEK_API_KEY`

多个 agent 可以共享同一个 provider key，只是在配置里引用不同模型名。

## 默认 agent 建议

当前默认建议：

- `master`: `runner=codex`, `model=gpt-5.5`
- `reviewer`: `runner=codex`, `model=gpt-5.5`
- `architect`: `runner=claude`, `model=deepseek-v4-flash`
- `coder`: `runner=claude`, `model=deepseek-v4-flash`
- `tester`: `runner=claude`, `model=deepseek-v4-flash`
- `cheap_worker`: `runner=direct_llm`, `model=deepseek-chat`

每个 agent 都可以单独改：

- `runner`
- `model`
- `reasoning_effort`
- 环境变量映射
- `preferred_skills`
- `preferred_mcp`

示例：

```yaml
agents:
  master:
    runner: codex
    model: gpt-5.5
    preferred_skills: [bulletproof, github]
    preferred_mcp: [context-mode, letta]
```

## 常用命令

```powershell
agentsCluster init
agentsCluster doctor
agentsCluster config open

agentsCluster project add D:\programs\your-project --name your-project
agentsCluster project list
agentsCluster project remove your-project

agentsCluster test-agent master --dry-run
agentsCluster test-agent master

agentsCluster serve --host 127.0.0.1 --port 8765

agentsCluster run --project your-project --goal "实现某个功能"
agentsCluster runs list
agentsCluster runs show <run_id>
agentsCluster runs resume <run_id> --yes
agentsCluster runs artifacts <run_id>

agentsCluster apply <run_id> --mode diff
agentsCluster apply <run_id> --mode patch
agentsCluster apply <run_id> --mode merge
agentsCluster apply <run_id> --mode discard
```

## 队列与 worktree 规则

- 每个 run 都会创建独立 `git worktree`
- 同一个 `project_path` 下允许连续提交多个 run
- 这些 run 的 `planning` / `execute` 会按项目维度串行排队
- 队列中的 run 状态为 `queued`
- `approve-plan`、`retry-plan`、`retry-execute`、`resume` 也会进入同一套队列
- `merge` 和 `discard` 需要显式确认

这套策略适合先做 CLI，后面前端直接读取 API 状态即可。

## HTTP API

启动本地 API：

```powershell
agentsCluster serve --host 127.0.0.1 --port 8765
```

默认地址：

```text
http://127.0.0.1:8765
```

## 本地工作台

启动本地服务后，直接打开：
```text
http://127.0.0.1:8765/
```

工作台提供：
- 项目注册与删除
- run 创建、状态、时间线、产物预览
- approve / merge / discard
- 全局配置编辑
- `.env` 编辑

详细接口见：

[`docs/api.md`](D:/programs/agentsCluster/docs/api.md)

对外主要资源包括：

- `projects`
- `agents`
- `runs`
- `events`
- `artifacts`
- `diff`
- `apply`

后续前端可以直接围绕这些接口做项目选择、任务创建、状态追踪、日志查看和结果确认。

## 可选开源集成

当前项目保留了可扩展接口，后续可逐步接入：

- LangGraph
- OpenAI Agents SDK
- OpenHands
- aider
- SWE-agent

已有本地检查与 spike：

```powershell
agentsCluster integrations list
agentsCluster integrations spike langgraph
agentsCluster integrations spike openai-agents
agentsCluster integrations spike openhands
```

选型说明见：

[`docs/architecture-comparison.md`](D:/programs/agentsCluster/docs/architecture-comparison.md)

## 自检与回归

建议至少运行：

```powershell
.\scripts\run_tests.ps1

# 或手动运行：
conda run -n agentsCluster python -m compileall src tests
conda run -n agentsCluster python -m pip check
conda run -n agentsCluster python tests\smoke.py
conda run -n agentsCluster python tests\langgraph_smoke.py
conda run -n agentsCluster python tests\integration_smoke.py
conda run -n agentsCluster python tests\api_smoke.py
```

## 当前定位

`agentsCluster` 现在不是一个“自动替你合并一切”的黑盒，而是一套本地可控的多 agent 编程调度底座：

- 你给目标
- 主控规划和分派
- worker 执行
- reviewer 审核
- 系统记录全过程
- 最后由你确认如何处理结果

这和直接把所有事情塞给单个 CLI agent 不一样，重点是可追踪、可恢复、可替换模型、可接前端。
