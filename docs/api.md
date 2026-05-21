# agentsCluster 对外接口文档

本文档描述当前 `agentsCluster` 的 CLI 和 HTTP JSON API。后续前端可以直接以这里的 HTTP 协议为准。

## 1. 总览

本地服务启动后，前端或脚本主要通过以下资源交互：

- `projects`
- `agents`
- `runs`
- `events`
- `artifacts`
- `diff`
- `apply`

默认地址：

```text
http://127.0.0.1:8765
```

启动命令：

```powershell
agentsCluster serve --host 127.0.0.1 --port 8765
```

所有响应均为 JSON。SSE 事件流除外。

## 2. 运行状态机

常见状态：

- `queued`：已进入后台队列，等待开始 `planning` 或 `execute`
- `planning`：主控正在生成计划
- `waiting_approval`：计划已生成，等待用户确认是否执行
- `running`：worker / reviewer / master summary 正在执行
- `reviewed`：运行完成，已有总结
- `cancel_requested`：已请求取消，等待后台任务到达取消检查点
- `cancelled`：已取消
- `failed`：运行失败
- `interrupted`：服务重启后发现旧 run 未正常收尾，已保守中断
- `merged`：结果已合并回原仓库
- `discarded`：worktree 已被丢弃

## 3. 项目级串行队列

同一个 `project_path` 支持连续提交多个 run，但它们不会并发执行模型调用。

规则如下：

- `POST /api/runs` 会把 `plan` 阶段入队
- `POST /api/runs/{run_id}/approve-plan` 会把 `execute` 阶段入队
- `retry-plan`、`retry-execute`、`resume` 也会进入同一套队列
- 同项目下的 `planning` 和 `execute` 按提交顺序串行执行
- 这意味着你可以连续创建多个 run，但第二个 run 通常会先看到 `status=queued`

## 4. CLI 接口

### 环境检查

```powershell
agentsCluster doctor
.\agentsCluster.ps1 doctor
```

### 项目注册

```powershell
agentsCluster project add D:\programs\your-project --name your-project
agentsCluster project list
agentsCluster project remove your-project
agentsCluster project remove D:\programs\your-project
```

### 单独测试 agent

```powershell
agentsCluster test-agent master --dry-run
agentsCluster test-agent master
```

### 创建和查看运行

```powershell
agentsCluster run --project your-project --goal "实现某个功能"
agentsCluster runs list
agentsCluster runs show <run_id>
agentsCluster runs resume <run_id> --yes
agentsCluster runs artifacts <run_id>
```

### 处理结果

```powershell
agentsCluster apply <run_id> --mode diff
agentsCluster apply <run_id> --mode patch
agentsCluster apply <run_id> --mode merge
agentsCluster apply <run_id> --mode discard
```

## 5. HTTP Endpoints

### GET /health

健康检查：

```json
{
  "ok": true,
  "service": "agentsCluster"
}
```

### GET /api/config

返回当前全局配置：

```json
{
  "config": {
    "settings": {},
    "agents": {},
    "projects": []
  }
}
```

### PUT /api/config

保存全局配置，支持直接提交整个 `config` 对象：

```json
{
  "config": {
    "settings": {
      "orchestrator": "builtin"
    },
    "agents": {},
    "projects": []
  }
}
```

### GET /api/env

返回当前 `.env` 键值对：

```json
{
  "env": {
    "OPENAI_API_KEY": "sk-...",
    "OPENAI_BASE_URL": "https://..."
  }
}
```

### PUT /api/env

保存 `.env`。未提交的键会从文件和当前进程环境中删除：

```json
{
  "env": {
    "OPENAI_API_KEY": "sk-...",
    "OPENAI_BASE_URL": "https://..."
  }
}
```

### GET /api/integrations

返回可插拔底座集成的探测结果（是否已安装、安装提示、用途说明等）：

```json
{
  "integrations": [
    {
      "name": "langgraph",
      "installed": true,
      "detail": "installed: langgraph",
      "install_hint": "pip install langgraph",
      "use_for": "用于可插拔的规划/执行图（graph）编排层。"
    }
  ]
}
```

### GET /api/tools

返回可选 CLI 工具的探测结果。注意：`agentsCluster` 默认不会把这些工具装进主 conda env，
而是建议以“独立 venv / 独立工具环境”方式安装（例如 `vendor/tools/aider/.venv`）：

```json
{
  "tools": [
    {
      "name": "aider",
      "installed": false,
      "command": "aider",
      "command_path": null,
      "local_root": "D:\\\\programs\\\\agentsCluster\\\\vendor\\\\tools\\\\aider",
      "local_command_path": null,
      "install_hint": "agentsCluster tools install aider"
    }
  ]
}
```

### GET /api/projects

返回已注册项目：

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

注册项目，不修改项目仓库内容。

请求：

```json
{
  "name": "my-app",
  "path": "D:\\programs\\my-app"
}
```

响应：

```json
{
  "project": {
    "name": "my-app",
    "path": "D:\\programs\\my-app"
  }
}
```

### DELETE /api/projects/{selector}

删除项目注册，不删除磁盘文件。

`selector` 可以是项目名，也可以是项目路径。

### GET /api/agents

返回 agent 摘要。只暴露环境变量名，不暴露密钥值。

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

返回单个 agent 摘要。

### POST /api/agents/{name}/test

测试某个 agent。

仅校验 runner / 模型 / 配置，不真实调用模型：

```json
{
  "dry_run": true,
  "cwd": "D:\\programs\\your-project"
}
```

真实调用模型时必须显式确认：

```json
{
  "dry_run": false,
  "confirm": true,
  "cwd": "D:\\programs\\your-project",
  "prompt": "只检查当前目录，不要修改文件。"
}
```

### GET /api/runs?limit=20

返回最近的 runs 列表。

### POST /api/runs

创建 run，并把 `plan` 阶段放入后台队列。

请求：

```json
{
  "project": "my-app",
  "goal": "实现某个功能",
  "workers": ["architect", "coder", "tester"],
  "max_rework_rounds": 2
}
```

响应：

```json
{
  "run_id": "run_20260519_120000_abcdef",
  "status": "queued",
  "phase": "plan"
}
```

### GET /api/runs/{run_id}

返回 run 详情和事件列表：

```json
{
  "run": {
    "id": "run_20260519_120000_abcdef",
    "status": "waiting_approval"
  },
  "events": []
}
```

### GET /api/runs/{run_id}/events

只返回事件列表。支持增量拉取：

```text
GET /api/runs/{run_id}/events?after_id=120&limit=200
```

每个事件对象包含：

- `id`
- `created_at`
- `agent`
- `kind`
- `message`
- `metadata`

### GET /api/runs/{run_id}/events/stream

SSE 事件流接口，适合前端实时订阅。

示例：

```text
GET /api/runs/{run_id}/events/stream?after_id=120&timeout=25&limit=500
```

SSE 事件类型：

- `ready`
- `run-state`
- `run-event`
- `done`

### GET /api/runs/{run_id}/artifacts

列出当前 run 目录下可直接读取的产物文件，例如：

- `plan.md`
- `task-plan.json`
- `worker-log.md`
- `review.md`
- `summary.md`
- `status.txt`
- `diff.patch`
- `agent_outputs/...`

### GET /api/runs/{run_id}/artifacts/{path}

读取单个产物。

- `.json` 文件返回 `type=json` 和 `data`
- 其他文本文件返回 `type=text` 和 `text`

示例：

```text
GET /api/runs/{run_id}/artifacts/plan.md
GET /api/runs/{run_id}/artifacts/task-plan.json
GET /api/runs/{run_id}/artifacts/agent_outputs/final/master.result.json
```

### GET /api/runs/{run_id}/diff

返回 worktree 相对原项目仓库的 diff。

### POST /api/runs/{run_id}/approve-plan

用户确认计划后，把 `execute` 阶段放入后台队列。

请求：

```json
{
  "confirm": true
}
```

响应：

```json
{
  "run_id": "run_20260519_120000_abcdef",
  "status": "queued",
  "phase": "execute"
}
```

### POST /api/runs/{run_id}/retry-plan

基于当前 worktree 重新执行 `planning`。

```json
{
  "confirm": true
}
```

响应：

```json
{
  "run_id": "run_20260519_120000_abcdef",
  "status": "queued",
  "phase": "plan"
}
```

### POST /api/runs/{run_id}/retry-execute

基于现有 `plan.md + task-plan.json` 重新执行 worker / reviewer / summary。

```json
{
  "confirm": true
}
```

响应：

```json
{
  "run_id": "run_20260519_120000_abcdef",
  "status": "queued",
  "phase": "execute"
}
```

### POST /api/runs/{run_id}/resume

自动恢复入口。

逻辑：

- 如果已有 `summary.md`，返回 `mode=noop`
- 如果已有 `plan.md + task-plan.json`，入队 `execute`
- 否则入队 `plan`

请求：

```json
{
  "confirm": true
}
```

可能响应：

```json
{
  "run_id": "run_20260519_120000_abcdef",
  "status": "queued",
  "phase": "execute",
  "mode": "execute"
}
```

### POST /api/runs/{run_id}/cancel

请求取消。

```json
{
  "confirm": true
}
```

响应示例：

```json
{
  "run_id": "run_20260519_120000_abcdef",
  "status": "cancel_requested"
}
```

如果该 run 还没真正开始执行，也可能直接变成 `cancelled`。

### POST /api/runs/{run_id}/apply

处理 run 结果。

请求：

```json
{
  "mode": "diff"
}
```

支持：

- `diff`：只返回 diff
- `patch`：写出 `patches/<run_id>.patch`，并把同一份内容存为 run artifact：`runs/<run_id>/changes.patch`
- `merge`：把 worktree 分支合并回项目仓库，需要 `confirm=true`
- `discard`：删除 worktree，需要 `confirm=true`

`merge` 示例：

```json
{
  "mode": "merge",
  "confirm": true
}
```

注意：

- 当 run 仍处于 `queued / planning / waiting_approval / running / cancel_requested` 等活跃状态时，`apply` 会返回 `409`
- 这样可以避免后台任务还在执行时被提前 `merge` 或 `discard`
- `merge` 会做保守检查：要求项目仓库当前 worktree 干净，并且处于该 run 的 `base_branch`；否则会返回 `409`，建议改用 `patch`

## 6. 产物目录约定

每个 run 默认写入：

```text
runs/<run_id>/
```

常见文件：

```text
runs/<run_id>/plan.md
runs/<run_id>/task-plan.json
runs/<run_id>/worker-log.md
runs/<run_id>/review.md
runs/<run_id>/summary.md
runs/<run_id>/diff.patch
runs/<run_id>/changes.patch
runs/<run_id>/agent_outputs/*.result.json
```

其中：

- `task-plan.json` 适合作为前端结构化展示的数据源
- `agent_outputs/*.result.json` 适合作为 agent 结果明细
- `events` 适合作为时间线

## 7. 前端接入建议

前端第一版建议直接围绕以下流程实现：

1. 读取 `/api/projects`
2. 调用 `POST /api/runs`
3. 轮询 `/api/runs/{run_id}` 或订阅 `/events/stream`
4. 读取 `/artifacts`
5. 用户确认后调用 `/approve-plan`
6. 运行结束后通过 `/diff` 或 `/apply`

这样前端不需要直接理解底层 CLI，只需要跟 HTTP API 对接。
