# vendor 本地依赖区

这个目录用于放 agentsCluster 的可选依赖清单、pip 缓存、安装日志和可选源码仓库。Python 包依赖仍由独立 conda 环境 `agentsCluster` 管理，不安装到 base 或全局 Python。

## 目录约定

- `vendor/cache/`：pip 下载缓存，不提交 GitHub。
- `vendor/logs/`：安装和验证日志，不提交 GitHub。
- `vendor/repos/`：后续如需克隆 OpenHands、SWE-agent 等源码仓库，可放这里，不提交 GitHub。
- `vendor/requirements-optional.txt`：可提交的可选依赖清单。

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

`aider-chat` 当前先不默认安装，原因是它在本机 Windows/conda 下安装阶段长时间无输出，并且会临时影响 `openai` 版本。后续单独验证后再打开。

OpenHands 和 SWE-agent 依赖较重，先通过 `agentsCluster integrations list` 检测和记录；后续按验证结果决定是加入 conda 环境，还是克隆到 `vendor/repos`。
