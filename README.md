# agentsCluster

`agentsCluster` 是一个本地多 agent 编程调度器。它用 Python 做总控 CLI，后台可以调用 Codex CLI、Claude Code 或直接调用 OpenAI-compatible API worker。

第一版的设计目标是保守可控：

- 每次任务都会创建独立 `git worktree`。
- worker 执行期间不会直接修改原项目主工作区。
- 总控会先规划、再分派 worker、再审核结果。
- 完成后由你选择 `merge`、`diff`、`patch` 或 `discard`。
- 真实配置和密钥默认不上传 GitHub。

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

如果 PowerShell 提示找不到 `agentsCluster`，可以先用下面任意一种方式运行诊断：

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

真实本地配置在：

```text
D:\programs\agentsCluster\config\agents.yaml
```

GitHub 模板配置在：

```text
D:\programs\agentsCluster\config\agents.example.yaml
```

密钥放在：

```text
D:\programs\agentsCluster\.env
```

`.env`、`config\agents.yaml`、数据库、运行日志、worktree、patch 和常见密钥文件都已加入 `.gitignore`。

## API Key 数量

不需要每个 agent 单独一个 key。通常只需要按 provider 配：

- Codex/OpenAI：一个 `OPENAI_API_KEY`。
- DeepSeek：一个 `DEEPSEEK_API_KEY`。

多个 agent 可以共用同一个 provider key。比如 `architect`、`coder`、`tester` 都可以共用 `DEEPSEEK_API_KEY`。

当前默认配置：

- `master`：`codex`，模型 `gpt-5.5`，推理强度 `xhigh`。
- `reviewer`：`codex`，模型 `gpt-5.5`，推理强度 `xhigh`。
- `architect`：`claude`，模型 `deepseek-v4-flash`。
- `coder`：`claude`，模型 `deepseek-v4-flash`。
- `tester`：`claude`，模型 `deepseek-v4-flash`。
- `cheap_worker`：`direct_llm`，模型 `deepseek-chat`。

注意：`runner: codex` 和 `runner: claude` 是调用你本机安装的 CLI。它们能否直接使用某个第三方 API，取决于对应 CLI 自身支持。DeepSeek 这类 OpenAI-compatible API 最稳的路径是 `runner: direct_llm`。

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
agentsCluster config open
agentsCluster project add D:\programs\your-project
agentsCluster project list
agentsCluster test-agent master --dry-run
agentsCluster test-agent master
agentsCluster chat
agentsCluster run --project D:\programs\your-project --goal "实现某个功能"
agentsCluster runs list
agentsCluster runs show run_YYYYMMDD_HHMMSS_xxxxxx
agentsCluster apply run_YYYYMMDD_HHMMSS_xxxxxx
agentsCluster apply run_YYYYMMDD_HHMMSS_xxxxxx --mode diff
agentsCluster apply run_YYYYMMDD_HHMMSS_xxxxxx --mode patch
agentsCluster apply run_YYYYMMDD_HHMMSS_xxxxxx --mode merge
agentsCluster apply run_YYYYMMDD_HHMMSS_xxxxxx --mode discard
```

`doctor` 会检查 Python、conda 环境、`agentsCluster` 命令入口、`git`、`codex`、`claude`、配置文件、`.env` key 是否存在，以及 `codex mcp list` 当前可见的 MCP。

`test-agent <name>` 可以单独测试某个 agent，例如 `master`。默认会调用模型；如果只想验证配置和 runner，请加 `--dry-run`。

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
