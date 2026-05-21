# vendor 本地依赖区

这个目录用于放 agentsCluster 的可选依赖清单、pip 缓存、安装日志和可选源码仓库。Python 包依赖仍由独立 conda 环境 `agentsCluster` 管理，不安装到 base 或全局 Python。

## 目录约定

- `vendor/cache/`：pip 下载缓存，不提交 GitHub。
- `vendor/logs/`：安装和验证日志，不提交 GitHub。
- `vendor/tools/`：可选 CLI 工具的独立安装目录（独立 venv/工具环境），不提交 GitHub。
- `vendor/repos/`：后续如需克隆 OpenHands、SWE-agent 等源码仓库，可放这里，不提交 GitHub。
- `vendor/requirements-optional.txt`：可提交的可选依赖清单。
- `vendor/requirements-workers.txt`：可提交的 worker 依赖清单（较重）。

## 安装

```powershell
cd D:\programs\agentsCluster
.\scripts\install_optional_deps.ps1
```

推荐先执行：

```powershell
conda activate agentsCluster
```

如果当前没有激活 `agentsCluster`，脚本会自动尝试：

```powershell
conda run -n agentsCluster python -m pip install ...
```

## 当前默认安装

- `langgraph`
- `openai-agents`

`aider-chat` 不建议装进主 conda env（可能与 `openai-agents` 的 `openai` 版本约束冲突）。推荐用工具安装器装到独立 venv：

```powershell
cd D:\programs\agentsCluster
agentsCluster tools install aider
```

OpenHands 和 SWE-agent 依赖较重，先通过 `agentsCluster integrations list` 检测和记录；后续按验证结果决定是加入工具环境，还是克隆到 `vendor/repos`。

如果需要安装 worker 相关依赖（OpenHands / SWE-agent / aider），执行：

```powershell
cd D:\programs\agentsCluster
.\scripts\install_worker_deps.ps1
```
