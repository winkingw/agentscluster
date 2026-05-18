# agentsCluster 对外接口

本文档记录当前 CLI 和 HTTP JSON API。后续前端可以按这里查询项目、agent、运行记录、事件、diff 和成果处理接口。

## CLI 接口

环境检测：

```powershell
agentsCluster doctor
.\agentsCluster.ps1 doctor
```

可选开源集成检测：

```powershell
agentsCluster integrations list
agentsCluster integrations spike langgraph
agentsCluster integrations spike openai-agents
agentsCluster integrations spike openhands
```

项目注册：

```powershell
agentsCluster project add D:\programs\your-project --name your-project
agentsCluster project list
agentsCluster project remove your-project
agentsCluster project remove D:\programs\your-project
```

单 agent 测试：

```powershell
agentsCluster test-agent master --dry-run
agentsCluster test-agent master
```

运行任务：

```powershell
agentsCluster run --project your-project --goal "实现某个功能"
agentsCluster run --project your-project --goal "实现某个功能" --max-rework-rounds 2
```

运行记录：

```powershell
agentsCluster runs list
agentsCluster runs show <run_id>
```

成果处理：

```powershell
agentsCluster apply <run_id> --mode diff
agentsCluster apply <run_id> --mode patch
agentsCluster apply <run_id> --mode merge
agentsCluster apply <run_id> --mode discard
```

## 运行产物

每次运行会生成：

```text
runs\<run_id>\plan.md
runs\<run_id>\task-plan.json
runs\<run_id>\worker-log.md
runs\<run_id>\review.md
runs\<run_id>\summary.md
runs\<run_id>\diff.patch
runs\<run_id>\agent_outputs\*.result.json
```

`task-plan.json` 和 `*.result.json` 是给 LangGraph 调度、HTTP API 和前端使用的结构化协议。

## HTTP 服务

启动本地接口服务：

```powershell
agentsCluster serve --host 127.0.0.1 --port 8765
```

默认地址：

```text
http://127.0.0.1:8765
```

所有响应都是 JSON，并带有基础 CORS 头，方便本地前端直接请求。

## HTTP Endpoints

### GET /health

健康检查。

```json
{
  "ok": true,
  "service": "agentsCluster"
}
```

### GET /api/projects

查询已注册项目。

```json
{
  "projects": [
    {
      "name": "my-app",
      "path": "D:\\programs\\my-app"
    }
  ]
}
```

### POST /api/projects

注册项目。只写入 `config\agents.yaml`，不会修改项目文件。

```json
{
  "name": "my-app",
  "path": "D:\\programs\\my-app"
}
```

### DELETE /api/projects/{selector}

取消项目注册。`selector` 可以是项目名或 URL 编码后的项目路径。

### GET /api/agents

查询 agent 配置摘要。响应只返回 env key 名称，不返回密钥值。

```json
{
  "agents": [
    {
      "name": "master",
      "runner": "codex",
      "model": "gpt-5.5",
      "role": "orchestrator",
      "timeout_seconds": 1800,
      "enabled": true,
      "preferred_skills": ["bulletproof", "github"],
      "preferred_mcp": ["context-mode", "letta"],
      "env_keys": ["OPENAI_API_KEY", "OPENAI_BASE_URL"]
    }
  ]
}
```

### GET /api/agents/{name}

查询单个 agent 配置摘要。

### POST /api/agents/{name}/test

测试单个 agent。默认 `dry_run=true`，不会调用模型。

```json
{
  "dry_run": true,
  "cwd": "D:\\programs\\your-project"
}
```

如果需要真实调用模型，必须传：

```json
{
  "dry_run": false,
  "confirm": true,
  "cwd": "D:\\programs\\your-project",
  "prompt": "只检查当前目录，不要修改文件。"
}
```

### GET /api/runs?limit=20

查询最近运行记录。

### GET /api/runs/{run_id}

查询单个运行记录和事件。

```json
{
  "run": {
    "id": "run_20260517_120000_abcdef",
    "status": "reviewed"
  },
  "events": []
}
```

### GET /api/runs/{run_id}/events

只查询某次运行的事件列表。

### GET /api/runs/{run_id}/diff

查询某次运行 worktree 当前 diff。

```json
{
  "run_id": "run_20260517_120000_abcdef",
  "diff": "..."
}
```

### POST /api/runs/{run_id}/apply

处理运行成果。请求体：

```json
{
  "mode": "diff"
}
```

支持：

- `diff`：返回 diff，不修改文件。
- `patch`：写入 `patches\<run_id>.patch`。
- `merge`：合并 worktree 分支到原项目，必须传 `confirm=true`。
- `discard`：删除 worktree，必须传 `confirm=true`。

`merge` 示例：

```json
{
  "mode": "merge",
  "confirm": true
}
```

## 暂不开放的接口

当前 HTTP API 仍暂不提供 `POST /api/runs` 来直接启动真实任务。原因是完整运行会触发模型调用、长时间占用请求，并修改 git worktree 状态。后续应先加异步任务队列和计划确认机制，再开放：

- `POST /api/runs`
- `POST /api/runs/{run_id}/approve-plan`
- `POST /api/runs/{run_id}/cancel`
