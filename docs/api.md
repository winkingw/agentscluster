# agentsCluster 对外接口（CLI + HTTP）

本文档记录当前 `agentsCluster` 的 CLI 与 HTTP JSON API。后续做前端时，建议直接以这里的 HTTP 协议为准。

## CLI 接口

环境检测：

```powershell
agentsCluster doctor
.\agentsCluster.ps1 doctor
```

可选底座/依赖检测与试跑（不改变默认调度路径）：

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

单独测试某个 agent（便于排查 runner/model/key 配置）：

```powershell
agentsCluster test-agent master --dry-run
agentsCluster test-agent master
```

运行与产物：

```powershell
agentsCluster run --project your-project --goal "实现某个功能"
agentsCluster runs list
agentsCluster runs show <run_id>
```

应用结果（需要确认的操作会要求 `confirm=true`）：

```powershell
agentsCluster apply <run_id> --mode diff
agentsCluster apply <run_id> --mode patch
agentsCluster apply <run_id> --mode merge
agentsCluster apply <run_id> --mode discard
```

## 运行产物（runs 目录协议）

每个 run 会生成在：

```text
runs\<run_id>\
```

常见文件：

```text
runs\<run_id>\plan.md
runs\<run_id>\task-plan.json
runs\<run_id>\worker-log.md
runs\<run_id>\review.md
runs\<run_id>\summary.md
runs\<run_id>\diff.patch
runs\<run_id>\agent_outputs\*.result.json
```

`task-plan.json` 和 `*.result.json` 是后续前端/可视化以及 LangGraph/其他底座适配会复用的结构化协议。

## HTTP 服务

启动本地 HTTP API：

```powershell
agentsCluster serve --host 127.0.0.1 --port 8765
```

默认地址：

```text
http://127.0.0.1:8765
```

响应均为 JSON，并附带基础 CORS 头，方便本地前端直接访问。

## Run 生命周期（面向前端的状态机）

典型流程：

1. `POST /api/runs` 创建 run 并在后台开始 planning。
2. 前端轮询 `GET /api/runs/{run_id}`，直到 `status=waiting_approval`（或 `failed/cancelled/interrupted`）。
3. 用户审阅 planning 产物后，`POST /api/runs/{run_id}/approve-plan`（需 `confirm=true`）进入执行阶段。
4. 继续轮询直到 `status=reviewed`（或 `failed/cancelled/interrupted`）。
5. 用户在 `POST /api/runs/{run_id}/apply` 里选择 `diff/patch/merge/discard`。

常见状态值（不是严格枚举，前端以实际返回为准）：

- `planning`：规划中（后台执行）。
- `queued`：已进入后台队列，等待 planning 或 execute 开始。
- `waiting_approval`：规划完成，等待用户确认是否执行。
- `running`：执行中（后台执行）。
- `reviewed`：完成并产出最终 summary。
- `cancel_requested`：取消已请求（运行中时触发，下一次取消检查点会生效）。
- `cancelled`：已取消。
- `interrupted`：服务重启后发现旧 run 未正常收尾，系统已保守停止，不会自动继续调用模型。
- `failed`：失败。
- `merged`：已合并到项目仓库（apply=merge 后）。
- `discarded`：已丢弃 worktree（apply=discard 后）。

事件流（`GET /api/runs/{run_id}` 的 `events` 字段）会包含更细的阶段点，例如：

- `run_created`
- `planning_started` / `planning_completed`
- `queue_started` / `queue_completed` / `queue_failed`
- `execution_completed`
- `retry_plan_requested` / `retry_execute_requested`
- `run_recovered` / `run_interrupted`
- `cancel_requested` / `run_cancelled`
- `run_failed`

## HTTP Endpoints

### GET /health

健康检查：

```json
{
  "ok": true,
  "service": "agentsCluster"
}
```

### GET /api/projects

查询已注册项目：

```json
{
  "projects": [
    {
      "name": "my-app",
      "path": "D:\\\\programs\\\\my-app"
    }
  ]
}
```

### POST /api/projects

注册项目（只写入 `config/agents.yaml`，不修改项目仓库内容）：

```json
{
  "name": "my-app",
  "path": "D:\\\\programs\\\\my-app"
}
```

### DELETE /api/projects/{selector}

取消项目注册。`selector` 可以是项目名，也可以是 URL 编码后的项目路径。

### GET /api/agents

查询 agent 配置摘要（只返回 env key 名称，不返回密钥值）：

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

查询单个 agent 摘要。

### POST /api/agents/{name}/test

测试单个 agent。默认 `dry_run=true`，不真实调用模型。

```json
{
  "dry_run": true,
  "cwd": "D:\\\\programs\\\\your-project"
}
```

如果需要真实调用模型，必须显式确认：

```json
{
  "dry_run": false,
  "confirm": true,
  "cwd": "D:\\\\programs\\\\your-project",
  "prompt": "只检查当前目录，不要修改文件。"
}
```

### GET /api/runs?limit=20

查询最近 runs 列表（默认 20）。

### POST /api/runs

创建 run 并在后台开始 planning（异步）。请求体：

```json
{
  "project": "my-app",
  "goal": "实现某个功能",
  "workers": ["architect", "coder", "tester"],
  "max_rework_rounds": 2
}
```

返回：

```json
{
  "run_id": "run_20260518_120000_abcdef",
  "status": "planning"
}
```

### GET /api/runs/{run_id}

查询 run 详情与事件列表：

```json
{
  "run": {
    "id": "run_20260518_120000_abcdef",
    "status": "waiting_approval"
  },
  "events": []
}
```

### GET /api/runs/{run_id}/events

只查询事件列表。支持增量查询：

```text
GET /api/runs/{run_id}/events?after_id=120&limit=200
```

返回中的每个 event 都包含：

- `id`
- `created_at`
- `agent`
- `kind`
- `message`
- `metadata`

### GET /api/runs/{run_id}/events/stream

SSE 事件流接口，适合前端做实时订阅。支持参数：

```text
GET /api/runs/{run_id}/events/stream?after_id=120&timeout=25&limit=500
```

说明：

- `after_id`：只推送指定 event id 之后的新事件。
- `timeout`：服务端这次连接最长保持的秒数；超时后前端应自动重连。
- `limit`：单轮轮询最多返回的事件数。

SSE 事件类型：

- `ready`
- `run-state`
- `run-event`
- `done`

### GET /api/runs/{run_id}/artifacts

列出当前 run 目录下可直接给前端读取的产物文件，例如：

- `plan.md`
- `task-plan.json`
- `worker-log.md`
- `review.md`
- `summary.md`
- `status.txt`
- `diff.patch`
- `agent_outputs/...`

返回示例：

```json
{
  "run_id": "run_20260518_120000_abcdef",
  "artifacts": [
    {
      "name": "plan.md",
      "bytes": 1234
    }
  ]
}
```

### GET /api/runs/{run_id}/artifacts/{path}

读取单个产物内容。

- `.json` 文件会返回 `type=json` 和已解析的 `data`
- 其它文本文件返回 `type=text` 和 `text`

例如：

```text
GET /api/runs/{run_id}/artifacts/plan.md
GET /api/runs/{run_id}/artifacts/task-plan.json
GET /api/runs/{run_id}/artifacts/agent_outputs/final/master.result.json
```

### POST /api/runs/{run_id}/approve-plan

用户确认计划并开始执行（异步）。必须传：

```json
{
  "confirm": true
}
```

返回：

```json
{
  "run_id": "run_20260518_120000_abcdef",
  "status": "running"
}
```

### POST /api/runs/{run_id}/retry-plan

对已有 run 重新执行 planning。适合 `cancelled`、`failed`、`interrupted` 等状态下继续使用同一个 worktree 重做计划。

```json
{
  "confirm": true
}
```

返回：

```json
{
  "run_id": "run_20260518_120000_abcdef",
  "status": "planning"
}
```

### POST /api/runs/{run_id}/retry-execute

对已有 run 基于现有 `plan.md + task-plan.json` 重新执行 worker / reviewer / final summary。适合 `interrupted` 或执行失败后继续跑。

```json
{
  "confirm": true
}
```

返回：

```json
{
  "run_id": "run_20260518_120000_abcdef",
  "status": "running"
}
```

### POST /api/runs/{run_id}/cancel

请求取消（异步）。必须传：

```json
{
  "confirm": true
}
```

返回示例（如果 run 正在运行，可能先变为 `cancel_requested`）：

```json
{
  "run_id": "run_20260518_120000_abcdef",
  "status": "cancel_requested"
}
```

### GET /api/runs/{run_id}/diff

查询 worktree 相对原项目仓库的 diff：

```json
{
  "run_id": "run_20260518_120000_abcdef",
  "diff": "..."
}
```

### POST /api/runs/{run_id}/apply

对 run 的 worktree 进行结果应用。请求体：

```json
{
  "mode": "diff"
}
```

支持：

- `diff`：只返回 diff，不修改文件。
- `patch`：写出 `patches\\<run_id>.patch`。
- `merge`：合并 worktree 分支到项目仓库，需要 `confirm=true`。
- `discard`：删除 worktree，需要 `confirm=true`。

`merge` 示例：

```json
{
  "mode": "merge",
  "confirm": true
}
```
