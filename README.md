# agentsCluster

`agentsCluster` 是一个本地多 agent 编程调度器。它用 Python 做总控 CLI，可以调用 Codex CLI、Claude Code、OpenAI-compatible API worker，也预留了 LangGraph、OpenAI Agents SDK、OpenHands、aider、SWE-agent 等开源底座的集成位置。

当前目标是保守可控：

- 每次任务创建独立 `git worktree`。
- worker 执行期间不直接修改原项目主工作区。
- 总控先规划，再分派 worker，再审核结果。
- 审核不通过时可自动回派 worker 返工。
- 完成后由你选择 `merge`、`diff`、`patch` 或 `discard`。
- 真实配置、数据库、运行日志、worktree、patch 和所有敏感文件默认不上传 GitHub。

## 环境安装

推荐使用独立 conda 环境：

```powershell
cd D:\programs\agentsCluster
conda env create -f environment.yml
conda activate agentsCluster
agentsCluster init
```

如果环境已经存在：

```powershell
conda activate agentsCluster
pip install -e D:\programs\agentsCluster
agentsCluster init
```

如果 PowerShell 提示找不到 `agentsCluster`，可以先用任意一种方式运行：

```powershell
conda run -n agentsCluster agentsCluster doctor
.\agentsCluster.ps1 doctor
$env:PYTHONPATH="D:\programs\agentsCluster\src"; python -m agents_cluster.cli doctor
```

常见原因是当前 PowerShell 没把 conda 环境的 `Scripts` 目录加入 `PATH`。可执行：

```powershell
conda init powershell
```

然后重开 PowerShell，再运行：

```powershell
conda activate agentsCluster
agentsCluster doctor
```

## 配置文件

真实本地配置：

```text
D:\programs\agentsCluster\config\agents.yaml
```

GitHub 模板配置：

```text
D:\programs\agentsCluster\config\agents.example.yaml
```

密钥放在：

```text
D:\programs\agentsCluster\.env
```

`.env`、`config\agents.yaml`、数据库、运行日志、worktree、patch 和常见密钥文件都已加入 `.gitignore`。

## API Key 数量

不需要每个 agent 单独一个 key。通常按 provider 配置即可：

- Codex/OpenAI：一个 `OPENAI_API_KEY`
- DeepSeek：一个 `DEEPSEEK_API_KEY`

多个 agent 可以共用同一个 provider key。例如 `architect`、`coder`、`tester` 都可以共用 `DEEPSEEK_API_KEY`。

当前默认配置：

- `master`：`codex`，模型 `gpt-5.5`，推理强度 `xhigh`
- `reviewer`：`codex`，模型 `gpt-5.5`，推理强度 `xhigh`
- `architect`：`claude`，模型 `deepseek-v4-flash`
- `coder`：`claude`，模型 `deepseek-v4-flash`
- `tester`：`claude`，模型 `deepseek-v4-flash`
- `cheap_worker`：`direct_llm`，模型 `deepseek-chat`

注意：`runner: codex` 和 `runner: claude` 是调用你本机安装的 CLI。它们能否直接使用某个第三方 API，取决于对应 CLI 自身支持。DeepSeek 这类 OpenAI-compatible API 最稳的通用路径是 `runner: direct_llm`，或者通过 CLI 自己的 provider 配置实现。

## 可选开源集成

当前默认调度器仍是 `builtin`。后续可逐步接入：

- LangGraph：动态任务图、状态机、human-in-the-loop、长任务恢复。
- OpenAI Agents SDK：handoff、MCP、tracing、guardrails、sessions。
- OpenHands SDK：成熟编码 agent、REST/API、Docker 工作区。
- aider：轻量代码修改 worker。
- SWE-agent：issue/bugfix 型专项 worker。

检测本机是否已具备这些能力：

```powershell
agentsCluster integrations list
```

运行无模型 spike：

```powershell
agentsCluster integrations spike langgraph
agentsCluster integrations spike openai-agents
agentsCluster integrations spike openhands
```

详细审查见：

```text
D:\programs\agentsCluster\docs\architecture-comparison.md
```

## 工具偏好

每个 agent 可以配置工具偏好：

```yaml
preferred_skills: [bulletproof, github]
preferred_mcp: [context-mode, letta]
```

这些字段会被注入到该 agent 的 prompt 中，提醒它优先考虑可用 skill/MCP。实际能否调用仍取决于 Codex/Claude CLI 当前是否已经加载对应 skill/MCP。

## 常用命令

```powershell
agentsCluster init
agentsCluster doctor
agentsCluster integrations list
agentsCluster serve --host 127.0.0.1 --port 8765
agentsCluster config open
agentsCluster project add D:\programs\your-project
agentsCluster project list
agentsCluster project remove D:\programs\your-project
agentsCluster test-agent master --dry-run
agentsCluster test-agent master
agentsCluster chat
agentsCluster run --project D:\programs\your-project --goal "实现某个功能"
agentsCluster runs list
agentsCluster runs show run_YYYYMMDD_HHMMSS_xxxxxx
agentsCluster runs replan run_YYYYMMDD_HHMMSS_xxxxxx
agentsCluster runs execute run_YYYYMMDD_HHMMSS_xxxxxx --yes
agentsCluster runs resume run_YYYYMMDD_HHMMSS_xxxxxx --yes
agentsCluster runs artifacts run_YYYYMMDD_HHMMSS_xxxxxx
agentsCluster runs artifacts run_YYYYMMDD_HHMMSS_xxxxxx --name plan.md
agentsCluster apply run_YYYYMMDD_HHMMSS_xxxxxx --mode diff
agentsCluster apply run_YYYYMMDD_HHMMSS_xxxxxx --mode patch
agentsCluster apply run_YYYYMMDD_HHMMSS_xxxxxx --mode merge
agentsCluster apply run_YYYYMMDD_HHMMSS_xxxxxx --mode discard
```

`doctor` 会检查 Python、conda 环境、`agentsCluster` 命令入口、`git`、`codex`、`claude`、配置文件、`.env` key、可选开源集成，以及 `codex mcp list` 当前可见的 MCP。

`test-agent <name>` 可以单独测试某个 agent，例如 `master`。默认会调用模型；如果只想验证配置和 runner，请加 `--dry-run`。

`serve` 会启动本地 HTTP JSON API，后续前端可以直接请求。接口文档见 `docs\api.md`。

`runs replan` 会对已有 run 重新生成 `plan.md` 和 `task-plan.json`。

`runs execute` 会基于现有 planning 产物执行 worker / reviewer / final summary。

`runs resume` 会根据 run 当前已有产物自动判断是重新 planning 还是继续 execute。

`runs artifacts` 会列出或打印某个 run 的产物文件（`plan.md`、`task-plan.json`、`summary.md`、`agent_outputs/...` 等）。

## 运行产物

每次运行会写入：

```text
runs\<run_id>\plan.md
runs\<run_id>\task-plan.json
runs\<run_id>\worker-log.md
runs\<run_id>\review.md
runs\<run_id>\summary.md
runs\<run_id>\diff.patch
runs\<run_id>\agent_outputs\*.result.json
```

`task-plan.json` 和 `*.result.json` 是给后续 LangGraph 调度器、HTTP API 和前端复用的结构化协议。

## 自动返工

审核 agent 返回 `REQUEST_CHANGES` 时，总控默认会自动回派 `coder` 返工一轮，并在返工后再次调用 `tester` 和 `reviewer`。

默认轮数在 `settings.max_rework_rounds` 中配置：

```yaml
settings:
  max_rework_rounds: 1
```

也可以在单次运行时覆盖：

```powershell
agentsCluster run --project D:\programs\your-project --goal "实现某个功能" --max-rework-rounds 2
```

## 真实任务前检查

运行真实任务前建议确认：

- `codex` 和 `claude` 已经登录，或已经配置为可非交互运行。
- 目标项目是 git 仓库。
- 目标项目主工作区没有关键未提交改动。
- `.env` 中的 key 可用，并且没有被提交到 GitHub。
