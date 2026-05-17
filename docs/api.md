# agentsCluster 对外接口

本文档记录当前 CLI 和 HTTP JSON API，后续前端可以直接按这里查询。

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

`task-plan.json` 和 `*.result.json` 是给后续 LangGraph 调度、HTTP API 和前端使用的结构化协议。

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

响应示例：

```json
{
  "ok": true,
  "service": "agentsCluster"
}
```

### GET /api/projects

查询已注册项目。

响应示例：

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

请求示例：

```json
{
  "name": "my-app",
  "path": "D:\\programs\\my-app"
}
```

响应示例：

```json
{
  "project": {
    "name": "my-app",
    "path": "D:\\programs\\my-app"
  }
}
```

### DELETE /api/projects/{selector}

取消项目注册。`selector` 可以是项目名或 URL 编码后的项目路径。

响应示例：

```json
{
  "removed": {
    "name": "my-app",
    "path": "D:\\programs\\my-app"
  }
}
```

### GET /api/runs?limit=20

查询最近运行记录。

响应示例：

```json
{
  "runs": [
    {
      "id": "run_20260517_120000_abcdef",
      "status": "reviewed",
      "project_name": "my-app",
      "project_path": "D:\\programs\\my-app",
      "worktree_path": "D:\\programs\\agentsCluster\\worktrees\\my-app\\run_...",
      "branch_name": "agentsCluster/my-app/run_...",
      "goal": "实现某个功能",
      "summary": "...",
      "metadata": {}
    }
  ]
}
```

### GET /api/runs/{run_id}

查询单个运行记录和事件。

响应示例：

```json
{
  "run": {
    "id": "run_20260517_120000_abcdef",
    "status": "reviewed"
  },
  "events": []
}
```

## 后续要开放的写接口

当前 HTTP API 暂不提供直接启动任务、merge、patch、discard 的写接口。原因是这些操作可能触发模型调用或修改 git 状态，后续做前端时应先加确认弹窗和权限边界，再开放：

- `POST /api/runs`
- `POST /api/runs/{run_id}/approve-plan`
- `POST /api/runs/{run_id}/cancel`
- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/diff`
- `POST /api/runs/{run_id}/apply`
- `GET /api/agents`
- `POST /api/agents/{name}/test`
