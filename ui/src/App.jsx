import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clipboard,
  FileDiff,
  FileDown,
  FolderOpen,
  GitMerge,
  Plus,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Settings2,
  ShieldAlert,
  Trash2,
  Workflow,
} from "lucide-react";

const EMPTY_CONFIG = { settings: {}, agents: {}, projects: [] };
const DEFAULT_RUN_FORM = {
  project: "",
  goal: "",
  workers: "architect,coder,tester",
  maxRework: "1",
};

function createId(prefix = "row") {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}_${Math.random().toString(16).slice(2)}`;
  return `${prefix}_${suffix}`;
}

function clone(value) {
  if (typeof globalThis.structuredClone === "function") {
    return globalThis.structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value ?? null));
}

function createEmptyConfig() {
  return clone(EMPTY_CONFIG);
}

function parseCsv(text) {
  return String(text || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatCsv(value) {
  return Array.isArray(value) ? value.join(", ") : "";
}

function parseKeyValueLines(text) {
  const result = {};
  String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const index = line.indexOf("=");
      if (index < 0) {
        return;
      }
      const key = line.slice(0, index).trim();
      const value = line.slice(index + 1).trim();
      if (key) {
        result[key] = value;
      }
    });
  return result;
}

function formatKeyValueLines(map) {
  return Object.entries(map || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
}

function envRowsFromObject(map) {
  return Object.entries(map || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => ({
      id: createId("env"),
      key,
      value: String(value ?? ""),
    }));
}

function envObjectFromRows(rows) {
  const result = {};
  for (const row of rows || []) {
    const key = String(row.key || "").trim();
    if (!key) {
      continue;
    }
    result[key] = String(row.value ?? "");
  }
  return result;
}

function encodePath(value) {
  return String(value || "")
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function humanBytes(bytes) {
  const size = Number(bytes || 0);
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

async function requestJson(path, options = {}) {
  const init = { ...options };
  const headers = { ...(options.headers || {}) };
  if (init.body && !(init.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  init.headers = headers;
  const response = await fetch(path, init);
  const text = await response.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { raw: text };
    }
  }
  if (!response.ok) {
    throw new Error(body?.error || body?.raw || `${response.status} ${response.statusText}`);
  }
  return body;
}

function IconButton({ title, onClick, icon: Icon, className = "", disabled = false }) {
  return (
    <button
      type="button"
      className={`icon-btn ${className}`.trim()}
      title={title}
      aria-label={title}
      onClick={onClick}
      disabled={disabled}
    >
      <Icon size={16} aria-hidden="true" />
    </button>
  );
}

function ActionButton({ icon: Icon, children, className = "secondary", ...props }) {
  return (
    <button
      type="button"
      className={className}
      {...props}
      style={{ display: "inline-flex", alignItems: "center", gap: 6, justifyContent: "center", ...(props.style || {}) }}
    >
      <Icon size={14} aria-hidden="true" />
      <span>{children}</span>
    </button>
  );
}

function Field({ label, children, hint, full = false }) {
  return (
    <label className={full ? "full" : undefined}>
      <span>{label}</span>
      {children}
      {hint ? <div className="panel-hint" style={{ marginTop: 4 }}>{hint}</div> : null}
    </label>
  );
}

function App() {
  const [health, setHealth] = useState("loading");
  const [config, setConfig] = useState(createEmptyConfig());
  const [configDraft, setConfigDraft] = useState(createEmptyConfig());
  const [envRows, setEnvRows] = useState([]);
  const [agentEnvTexts, setAgentEnvTexts] = useState({});
  const [projects, setProjects] = useState([]);
  const [runs, setRuns] = useState([]);
  const [agents, setAgents] = useState([]);
  const [doctor, setDoctor] = useState({ checks: [], summary: { total: 0, passed: 0, failed: 0 } });
  const [integrations, setIntegrations] = useState([]);
  const [tools, setTools] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runDetail, setRunDetail] = useState(null);
  const [selectedArtifact, setSelectedArtifact] = useState(null);
  const [tab, setTab] = useState("workbench");
  const [projectForm, setProjectForm] = useState({ name: "", path: "" });
  const [runForm, setRunForm] = useState(DEFAULT_RUN_FORM);
  const [toast, setToast] = useState({ visible: false, text: "", kind: "ok" });
  const eventSourceRef = useRef(null);
  const toastTimerRef = useRef(null);

  const showToast = useCallback((text, kind = "ok") => {
    if (toastTimerRef.current) {
      clearTimeout(toastTimerRef.current);
    }
    setToast({ visible: true, text, kind });
    toastTimerRef.current = window.setTimeout(() => {
      setToast((current) => ({ ...current, visible: false }));
    }, 2600);
  }, []);

  const refreshCore = useCallback(async () => {
    const [configRes, envRes, projectsRes, agentsRes, doctorRes, integrationsRes, toolsRes, healthRes] = await Promise.all([
      requestJson("/api/config"),
      requestJson("/api/env"),
      requestJson("/api/projects"),
      requestJson("/api/agents"),
      requestJson("/api/doctor"),
      requestJson("/api/integrations"),
      requestJson("/api/tools"),
      requestJson("/health"),
    ]);

    const nextConfig = configRes.config || createEmptyConfig();
    const nextProjects = projectsRes.projects || [];
    const nextEnv = envRes.env || {};

    setConfig(nextConfig);
    setConfigDraft(clone(nextConfig));
    setEnvRows(envRowsFromObject(nextEnv));
    setAgentEnvTexts(
      Object.fromEntries(
        Object.entries(nextConfig.agents || {}).map(([name, agent]) => [
          name,
          formatKeyValueLines(agent?.env || {}),
        ]),
      ),
    );
    setProjects(nextProjects);
    setAgents(agentsRes.agents || []);
    setDoctor(doctorRes || { checks: [], summary: { total: 0, passed: 0, failed: 0 } });
    setIntegrations(integrationsRes.integrations || []);
    setTools(toolsRes.tools || []);
    setHealth(healthRes.ok ? "ok" : "bad");

    const nextProjectValues = nextProjects.map((project) => project.name || project.path);
    setRunForm((current) => {
      const currentProject = String(current.project || "").trim();
      if (currentProject && nextProjectValues.includes(currentProject)) {
        return current;
      }
      if (nextProjectValues.length) {
        return { ...current, project: nextProjectValues[0] };
      }
      return current;
    });
  }, []);

  const refreshRuns = useCallback(async (preferRunId = "") => {
    const res = await requestJson("/api/runs?limit=50");
    const nextRuns = res.runs || [];
    setRuns(nextRuns);
    setSelectedRunId((current) => {
      const target = preferRunId || current;
      if (target && nextRuns.some((run) => run.id === target)) {
        return target;
      }
      if (current && nextRuns.some((run) => run.id === current)) {
        return current;
      }
      return nextRuns[0]?.id || "";
    });
  }, []);

  const refreshAll = useCallback(async () => {
    setHealth("loading");
    try {
      await Promise.all([refreshCore(), refreshRuns()]);
      showToast("数据已刷新", "ok");
    } catch (error) {
      setHealth("bad");
      showToast(error.message, "error");
    }
  }, [refreshCore, refreshRuns, showToast]);

  const refreshRunDetail = useCallback(
    async (runId = selectedRunId) => {
      if (!runId) {
        setRunDetail(null);
        return;
      }
      const detail = await requestJson(`/api/runs/${encodeURIComponent(runId)}`);
      setRunDetail(detail);
    },
    [selectedRunId],
  );

  useEffect(() => {
    refreshAll().catch((error) => showToast(error.message, "error"));
    return () => {
      if (toastTimerRef.current) {
        clearTimeout(toastTimerRef.current);
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [refreshAll, showToast]);

  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null);
      return undefined;
    }

    let active = true;
    refreshRunDetail(selectedRunId).catch((error) => {
      if (active) {
        showToast(error.message, "error");
      }
    });

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const source = new EventSource(`/api/runs/${encodeURIComponent(selectedRunId)}/events/stream?timeout=60`);
    eventSourceRef.current = source;

    const reloadRun = () => {
      if (!active) return;
      refreshRunDetail(selectedRunId).catch((error) => showToast(error.message, "error"));
    };

    source.addEventListener("run-event", reloadRun);
    source.addEventListener("run-state", reloadRun);
    source.addEventListener("done", async () => {
      if (!active) return;
      try {
        await refreshRuns(selectedRunId);
        await refreshRunDetail(selectedRunId);
      } catch (error) {
        showToast(error.message, "error");
      }
    });
    source.onerror = () => {
      source.close();
    };

    return () => {
      active = false;
      source.close();
      if (eventSourceRef.current === source) {
        eventSourceRef.current = null;
      }
    };
  }, [refreshRunDetail, refreshRuns, selectedRunId, showToast]);

  const selectedRun = useMemo(() => {
    if (!selectedRunId) return null;
    return runs.find((run) => run.id === selectedRunId) || runDetail?.run || null;
  }, [runDetail?.run, runs, selectedRunId]);

  const healthLabel = health === "ok" ? "在线" : health === "bad" ? "离线" : "检查中";

  function updateEnvRow(rowId, field, value) {
    setEnvRows((current) =>
      current.map((row) =>
        row.id === rowId ? { ...row, [field]: value } : row,
      ),
    );
  }

  function addEnvRow() {
    setEnvRows((current) => [
      ...current,
      { id: createId("env"), key: `KEY_${current.length + 1}`, value: "" },
    ]);
  }

  function removeEnvRow(rowId) {
    setEnvRows((current) => current.filter((row) => row.id !== rowId));
  }

  function updateSetting(field, value) {
    setConfigDraft((current) => {
      const next = clone(current);
      next.settings = next.settings || {};
      next.settings[field] = value;
      return next;
    });
  }

  function updateAgent(name, updater) {
    setConfigDraft((current) => {
      const next = clone(current);
      next.agents = next.agents || {};
      const agent = next.agents[name] || {};
      next.agents[name] = agent;
      updater(agent);
      return next;
    });
  }

  function updateAgentField(name, field, value) {
    updateAgent(name, (agent) => {
      if (field === "enabled") {
        agent.enabled = Boolean(value);
        return;
      }
      if (field === "timeout_seconds") {
        agent.timeout_seconds = Number.parseInt(String(value), 10) || 0;
        return;
      }
      if (field === "preferred_skills" || field === "preferred_mcp") {
        agent[field] = parseCsv(value);
        return;
      }
      agent[field] = value;
    });
  }

  function updateAgentEnvText(name, text) {
    setAgentEnvTexts((current) => ({ ...current, [name]: text }));
  }

  function materializeConfig() {
    const next = clone(configDraft);
    next.settings = next.settings || {};
    next.agents = next.agents || {};
    for (const [name, text] of Object.entries(agentEnvTexts)) {
      if (!next.agents[name]) {
        continue;
      }
      next.agents[name].env = parseKeyValueLines(text);
    }
    return next;
  }

  async function saveConfig() {
    try {
      const nextConfig = materializeConfig();
      await requestJson("/api/config", {
        method: "PUT",
        body: JSON.stringify({ config: nextConfig }),
      });
      await requestJson("/api/env", {
        method: "PUT",
        body: JSON.stringify({ env: envObjectFromRows(envRows) }),
      });
      await refreshCore();
      showToast("配置已保存", "ok");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function addProject(event) {
    event.preventDefault();
    const path = String(projectForm.path || "").trim();
    if (!path) {
      showToast("请先填写项目路径", "error");
      return;
    }
    try {
      await requestJson("/api/projects", {
        method: "POST",
        body: JSON.stringify({ path, name: String(projectForm.name || "").trim() || undefined }),
      });
      setProjectForm({ name: "", path: "" });
      await refreshCore();
      showToast("项目已添加", "ok");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function removeProject(project) {
    const selector = project.name || project.path;
    if (!window.confirm(`删除项目注册：${selector} ?`)) {
      return;
    }
    try {
      await requestJson(`/api/projects/${encodeURIComponent(selector)}`, { method: "DELETE" });
      await refreshCore();
      showToast("项目注册已删除", "ok");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  function selectProject(project) {
    const selector = project.name || project.path;
    setRunForm((current) => ({ ...current, project: selector }));
    setTab("workbench");
    showToast(`已选择项目：${selector}`, "ok");
  }

  async function createRun(event) {
    event.preventDefault();
    const project = String(runForm.project || "").trim();
    const goal = String(runForm.goal || "").trim();
    if (!project) {
      showToast("请选择项目", "error");
      return;
    }
    if (!goal) {
      showToast("请填写目标", "error");
      return;
    }

    try {
      const payload = {
        project,
        goal,
      };
      const workers = parseCsv(runForm.workers);
      if (workers.length) {
        payload.workers = workers;
      }
      const maxRework = Number.parseInt(String(runForm.maxRework), 10);
      if (!Number.isNaN(maxRework)) {
        payload.max_rework_rounds = maxRework;
      }
      const res = await requestJson("/api/runs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await refreshRuns(res.run_id);
      setSelectedRunId(res.run_id);
      setSelectedArtifact(null);
      await refreshRunDetail(res.run_id);
      showToast(`Run 已创建：${res.run_id}`, "ok");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function selectRun(runId) {
    setSelectedRunId(runId);
    setSelectedArtifact(null);
    setTab("workbench");
    try {
      await refreshRunDetail(runId);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function approveRun(runId) {
    try {
      const res = await requestJson(`/api/runs/${encodeURIComponent(runId)}/approve-plan`, {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      showToast(`已进入 ${res.phase || res.status}`, "ok");
      await refreshRuns(runId);
      await refreshRunDetail(runId);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function retryPlan(runId) {
    try {
      const res = await requestJson(`/api/runs/${encodeURIComponent(runId)}/retry-plan`, {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      showToast(`已重跑 ${res.phase || "plan"}`, "ok");
      await refreshRuns(runId);
      await refreshRunDetail(runId);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function retryExecute(runId) {
    try {
      const res = await requestJson(`/api/runs/${encodeURIComponent(runId)}/retry-execute`, {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      showToast(`已重跑 ${res.phase || "execute"}`, "ok");
      await refreshRuns(runId);
      await refreshRunDetail(runId);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function resumeRun(runId) {
    try {
      const res = await requestJson(`/api/runs/${encodeURIComponent(runId)}/resume`, {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      showToast(`恢复模式：${res.mode || "unknown"}`, "ok");
      await refreshRuns(runId);
      await refreshRunDetail(runId);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function cancelRun(runId) {
    if (!window.confirm(`取消 run ${runId} ?`)) {
      return;
    }
    try {
      const res = await requestJson(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      showToast(`当前状态：${res.status}`, "ok");
      await refreshRuns(runId);
      await refreshRunDetail(runId);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function applyRun(runId, mode) {
    const needsConfirm = mode === "merge" || mode === "discard";
    if (needsConfirm && !window.confirm(`确认 ${mode} run ${runId} ?`)) {
      return;
    }
    try {
      const payload = { mode };
      if (needsConfirm) {
        payload.confirm = true;
      }
      const res = await requestJson(`/api/runs/${encodeURIComponent(runId)}/apply`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showToast(`已执行 ${res.mode || mode}`, "ok");
      await refreshRuns(runId);
      await refreshRunDetail(runId);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function viewArtifact(runId, name) {
    try {
      const res = await requestJson(`/api/runs/${encodeURIComponent(runId)}/artifacts/${encodePath(name)}`);
      const content =
        res.type === "json"
          ? JSON.stringify(res.data, null, 2)
          : String(res.text || "");
      setSelectedArtifact({
        name,
        type: res.type,
        content,
      });
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function copyArtifact() {
    if (!selectedArtifact?.content) {
      return;
    }
    try {
      await navigator.clipboard.writeText(selectedArtifact.content);
      showToast("产物内容已复制", "ok");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  const selectedRunStatus = String(selectedRun?.status || runDetail?.run?.status || "");
  const waitingApproval = selectedRunStatus === "waiting_approval";
  const activeRun = [
    "queued",
    "planning",
    "planned",
    "paused",
    "waiting_approval",
    "running",
    "cancel_requested",
  ].includes(selectedRunStatus);
  const canResume = ["interrupted", "failed", "cancelled", "reviewed"].includes(selectedRunStatus);
  const canRetry = !["merged", "discarded"].includes(selectedRunStatus);
  const canFinalize = ["reviewed", "failed", "cancelled", "interrupted"].includes(selectedRunStatus);

  const selectedRunArtifacts = runDetail?.artifacts || [];
  const selectedRunEvents = runDetail?.events || [];
  const selectedRunSummary = runDetail?.run?.summary || "未生成";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-title">agentsCluster</div>
          <div className="brand-subtitle">本地多 agent 工作台</div>
        </div>
        <div className="topbar-actions">
          <IconButton title="刷新" icon={RefreshCw} onClick={() => refreshAll()} />
          <IconButton title="保存配置" icon={Save} onClick={saveConfig} />
          <div className={`status-pill status-${health}`.trim()}>{healthLabel}</div>
        </div>
      </header>

      <main className="layout">
        <aside className="sidebar">
          <section className="panel">
            <div className="panel-header">
              <h2>项目</h2>
              <span className="panel-hint">注册 / 删除</span>
            </div>
            <form className="stack" onSubmit={addProject}>
              <Field label="名称">
                <input
                  type="text"
                  placeholder="my-app"
                  value={projectForm.name}
                  onChange={(event) => setProjectForm((current) => ({ ...current, name: event.target.value }))}
                />
              </Field>
              <Field label="路径">
                <input
                  type="text"
                  placeholder="D:\\programs\\my-app"
                  value={projectForm.path}
                  onChange={(event) => setProjectForm((current) => ({ ...current, path: event.target.value }))}
                />
              </Field>
              <div className="inline-actions">
                <ActionButton icon={Plus} className="primary" type="submit">
                  添加项目
                </ActionButton>
              </div>
            </form>
            <div className="item-list" style={{ marginTop: 12 }}>
              {projects.length ? (
                projects.map((project) => {
                  const selector = project.name || project.path;
                  return (
                    <div className="item" key={selector}>
                      <div className="item-title">{selector}</div>
                      <div className="item-sub">{project.path}</div>
                      <div className="item-actions">
                        <button type="button" className="secondary" onClick={() => selectProject(project)}>
                          <FolderOpen size={14} />
                          <span>选择</span>
                        </button>
                        <button type="button" className="danger" onClick={() => removeProject(project)}>
                          <Trash2 size={14} />
                          <span>删除</span>
                        </button>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="item muted">暂无项目</div>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>Runs</h2>
              <span className="panel-hint">最近 50 条</span>
            </div>
            <div className="item-list">
              {runs.length ? (
                runs.map((run) => (
                  <div
                    className="item"
                    key={run.id}
                    style={run.id === selectedRunId ? { borderColor: "rgba(112, 167, 255, 0.6)" } : undefined}
                  >
                    <div className="item-title">{run.goal || run.id}</div>
                    <div className="item-sub">
                      {run.status} · {run.project_name || ""}
                    </div>
                    <div className="item-actions">
                      <button type="button" className="secondary" onClick={() => selectRun(run.id)}>
                        <Activity size={14} />
                        <span>查看</span>
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="item muted">暂无 run</div>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>状态</h2>
              <span className="panel-hint">doctor / MCP</span>
            </div>
            <div className="summary-grid" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
              <div className="summary-card">
                <div className="summary-label">总计</div>
                <div className="summary-value">{doctor.summary?.total ?? 0}</div>
              </div>
              <div className="summary-card">
                <div className="summary-label">通过</div>
                <div className="summary-value">{doctor.summary?.passed ?? 0}</div>
              </div>
              <div className="summary-card">
                <div className="summary-label">失败</div>
                <div className="summary-value">{doctor.summary?.failed ?? 0}</div>
              </div>
            </div>
          </section>
        </aside>

        <section className="content">
          <div className="tabs">
            <button className={`tab ${tab === "workbench" ? "active" : ""}`} onClick={() => setTab("workbench")}>
              工作台
            </button>
            <button className={`tab ${tab === "config" ? "active" : ""}`} onClick={() => setTab("config")}>
              配置
            </button>
            <button className={`tab ${tab === "doctor" ? "active" : ""}`} onClick={() => setTab("doctor")}>
              检查
            </button>
          </div>

          {tab === "workbench" ? (
            <div className="tab-panel">
              <section className="panel">
                <div className="panel-header">
                  <h2>创建 Run</h2>
                  <span className="panel-hint">项目 + 目标 + worker</span>
                </div>
                <form className="grid-form" onSubmit={createRun}>
                  <Field label="项目">
                    <select
                      value={runForm.project}
                      onChange={(event) => setRunForm((current) => ({ ...current, project: event.target.value }))}
                    >
                      {projects.length ? (
                        projects.map((project) => {
                          const value = project.name || project.path;
                          return (
                            <option value={value} key={value}>
                              {value}
                            </option>
                          );
                        })
                      ) : (
                        <option value="">暂无项目</option>
                      )}
                    </select>
                  </Field>
                  <Field label="目标" full>
                    <textarea
                      rows={4}
                      placeholder="描述要完成的任务"
                      value={runForm.goal}
                      onChange={(event) => setRunForm((current) => ({ ...current, goal: event.target.value }))}
                    />
                  </Field>
                  <Field label="workers">
                    <input
                      type="text"
                      placeholder="architect,coder,tester"
                      value={runForm.workers}
                      onChange={(event) => setRunForm((current) => ({ ...current, workers: event.target.value }))}
                    />
                  </Field>
                  <Field label="最大返工轮数">
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={runForm.maxRework}
                      onChange={(event) => setRunForm((current) => ({ ...current, maxRework: event.target.value }))}
                    />
                  </Field>
                  <div className="inline-actions">
                    <ActionButton icon={Play} className="primary" type="submit">
                      创建 Run
                    </ActionButton>
                  </div>
                </form>
              </section>

              <section className="panel">
                <div className="panel-header">
                  <h2>Run 详情</h2>
                  <span className="panel-hint">{selectedRunId || "未选择 run"}</span>
                </div>

                {selectedRun ? (
                  <>
                    <div className="summary-grid">
                      <div className="summary-card">
                        <div className="summary-label">状态</div>
                        <div className="summary-value">{selectedRun.status || "-"}</div>
                      </div>
                      <div className="summary-card">
                        <div className="summary-label">项目</div>
                        <div className="summary-value">{selectedRun.project_name || "-"}</div>
                      </div>
                      <div className="summary-card">
                        <div className="summary-label">分支</div>
                        <div className="summary-value">{selectedRun.branch_name || "-"}</div>
                      </div>
                      <div className="summary-card">
                        <div className="summary-label">更新时间</div>
                        <div className="summary-value">{selectedRun.created_at || "-"}</div>
                      </div>
                      <div className="summary-card">
                        <div className="summary-label">目标</div>
                        <div className="summary-value">{selectedRun.goal || "-"}</div>
                      </div>
                      <div className="summary-card">
                        <div className="summary-label">总结</div>
                        <div className="summary-value">{selectedRunSummary}</div>
                      </div>
                    </div>

                    <div className="action-bar">
                      <ActionButton icon={RefreshCw} onClick={() => refreshRunDetail(selectedRunId)}>
                        刷新
                      </ActionButton>
                      <ActionButton
                        icon={CheckCircle2}
                        onClick={() => approveRun(selectedRunId)}
                        disabled={!waitingApproval}
                      >
                        Approve
                      </ActionButton>
                      <ActionButton icon={Play} onClick={() => resumeRun(selectedRunId)} disabled={!canResume}>
                        Resume
                      </ActionButton>
                      <ActionButton icon={RotateCcw} onClick={() => retryPlan(selectedRunId)} disabled={!canRetry}>
                        Retry plan
                      </ActionButton>
                      <ActionButton icon={Workflow} onClick={() => retryExecute(selectedRunId)} disabled={!canRetry}>
                        Retry execute
                      </ActionButton>
                      <ActionButton icon={ShieldAlert} onClick={() => cancelRun(selectedRunId)} disabled={activeRun === false}>
                        Cancel
                      </ActionButton>
                      <ActionButton icon={FileDiff} onClick={() => applyRun(selectedRunId, "diff")} disabled={!selectedRun}>
                        Diff
                      </ActionButton>
                      <ActionButton icon={FileDown} onClick={() => applyRun(selectedRunId, "patch")} disabled={!selectedRun}>
                        Patch
                      </ActionButton>
                      <ActionButton icon={GitMerge} onClick={() => applyRun(selectedRunId, "merge")} disabled={!canFinalize}>
                        Merge
                      </ActionButton>
                      <ActionButton icon={Trash2} onClick={() => applyRun(selectedRunId, "discard")} disabled={!canFinalize}>
                        Discard
                      </ActionButton>
                    </div>

                    <div className="split">
                      <div>
                        <h3 className="subhead">时间线</h3>
                        <div className="timeline">
                          {selectedRunEvents.length ? (
                            selectedRunEvents.map((event) => (
                              <div className="event" key={event.id}>
                                <div className="event-head">
                                  <span>
                                    {event.created_at || ""} · {event.agent || ""}
                                  </span>
                                  <span className="event-kind">{event.kind || ""}</span>
                                </div>
                                <div className="event-message">{event.message || ""}</div>
                              </div>
                            ))
                          ) : (
                            <div className="muted">暂无事件</div>
                          )}
                        </div>
                      </div>

                      <div>
                        <h3 className="subhead">产物</h3>
                        <div className="artifact-list">
                          {selectedRunArtifacts.length ? (
                            selectedRunArtifacts.map((artifact) => (
                              <div className="artifact-row" key={artifact.name}>
                                <div>
                                  <div>{artifact.name}</div>
                                  <div className="panel-hint">{humanBytes(artifact.bytes)}</div>
                                </div>
                                <button
                                  type="button"
                                  className="secondary"
                                  onClick={() => viewArtifact(selectedRunId, artifact.name)}
                                >
                                  <Activity size={14} />
                                  <span>查看</span>
                                </button>
                              </div>
                            ))
                          ) : (
                            <div className="muted">暂无产物</div>
                          )}
                        </div>

                        <div className="artifact-view">
                          <div className="artifact-view-head">
                            <span>{selectedArtifact?.name || "未选择产物"}</span>
                            <button
                              type="button"
                              className="icon-btn"
                              title="复制产物内容"
                              onClick={copyArtifact}
                              disabled={!selectedArtifact?.content}
                            >
                              <Clipboard size={14} aria-hidden="true" />
                            </button>
                          </div>
                          <pre>{selectedArtifact?.content || "选择一个产物查看内容"}</pre>
                        </div>
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="item muted">选择一个 run 查看详情</div>
                )}
              </section>
            </div>
          ) : null}

          {tab === "config" ? (
            <div className="tab-panel">
              <section className="panel">
                <div className="panel-header">
                  <h2>全局设置</h2>
                  <span className="panel-hint">保存后立即生效</span>
                </div>
                <div className="grid-form">
                  <Field label="orchestrator">
                    <select
                      value={configDraft.settings?.orchestrator || "langgraph"}
                      onChange={(event) => updateSetting("orchestrator", event.target.value)}
                    >
                      <option value="langgraph">langgraph</option>
                      <option value="builtin">builtin</option>
                    </select>
                  </Field>
                  <Field label="integration_strategy">
                    <input
                      type="text"
                      value={configDraft.settings?.integration_strategy || ""}
                      onChange={(event) => updateSetting("integration_strategy", event.target.value)}
                    />
                  </Field>
                  <Field label="default_timeout_seconds">
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={configDraft.settings?.default_timeout_seconds ?? 1800}
                      onChange={(event) => updateSetting("default_timeout_seconds", Number.parseInt(event.target.value, 10) || 1800)}
                    />
                  </Field>
                  <Field label="max_rework_rounds">
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={configDraft.settings?.max_rework_rounds ?? 1}
                      onChange={(event) => updateSetting("max_rework_rounds", Number.parseInt(event.target.value, 10) || 0)}
                    />
                  </Field>
                </div>
              </section>

              <section className="panel">
                <div className="panel-header">
                  <h2>.env</h2>
                  <span className="panel-hint">本地编辑，保存时写回进程环境</span>
                </div>
                <div className="inline-actions">
                  <ActionButton icon={Plus} className="secondary" onClick={addEnvRow}>
                    添加变量
                  </ActionButton>
                </div>
                <div className="env-list" style={{ marginTop: 12 }}>
                  {envRows.length ? (
                    envRows.map((row) => (
                      <div className="env-row" key={row.id}>
                        <input
                          type="text"
                          value={row.key}
                          onChange={(event) => updateEnvRow(row.id, "key", event.target.value)}
                          placeholder="KEY"
                        />
                        <input
                          type="text"
                          value={row.value}
                          onChange={(event) => updateEnvRow(row.id, "value", event.target.value)}
                          placeholder="VALUE"
                        />
                        <button type="button" className="danger" onClick={() => removeEnvRow(row.id)}>
                          <Trash2 size={14} />
                          <span>删除</span>
                        </button>
                      </div>
                    ))
                  ) : (
                    <div className="muted">暂无 .env 变量</div>
                  )}
                </div>
              </section>

              <section className="panel">
                <div className="panel-header">
                  <h2>Agents</h2>
                  <span className="panel-hint">runner / model / skills / MCP</span>
                </div>
                <div className="agent-list">
                  {Object.entries(configDraft.agents || {}).length ? (
                    Object.entries(configDraft.agents || {}).map(([name, agent]) => (
                      <div className="agent-card" key={name}>
                        <div className="agent-head">
                          <div className="agent-name">{name}</div>
                          <label className="inline-actions" style={{ margin: 0 }}>
                            <input
                              type="checkbox"
                              checked={agent.enabled !== false}
                              onChange={(event) => updateAgentField(name, "enabled", event.target.checked)}
                            />
                            <span>启用</span>
                          </label>
                        </div>

                        <div className="agent-grid">
                          <Field label="runner">
                            <select
                              value={agent.runner || "direct_llm"}
                              onChange={(event) => updateAgentField(name, "runner", event.target.value)}
                            >
                              <option value="codex">codex</option>
                              <option value="claude">claude</option>
                              <option value="direct_llm">direct_llm</option>
                              <option value="aider">aider</option>
                              <option value="openhands">openhands</option>
                            </select>
                          </Field>
                          <Field label="model">
                            <input
                              type="text"
                              value={agent.model || ""}
                              onChange={(event) => updateAgentField(name, "model", event.target.value)}
                            />
                          </Field>
                          <Field label="role">
                            <input
                              type="text"
                              value={agent.role || ""}
                              onChange={(event) => updateAgentField(name, "role", event.target.value)}
                            />
                          </Field>
                          <Field label="timeout_seconds">
                            <input
                              type="number"
                              min="1"
                              step="1"
                              value={agent.timeout_seconds ?? 1800}
                              onChange={(event) => updateAgentField(name, "timeout_seconds", event.target.value)}
                            />
                          </Field>
                          <Field label="preferred_skills">
                            <input
                              type="text"
                              value={formatCsv(agent.preferred_skills || [])}
                              onChange={(event) => updateAgentField(name, "preferred_skills", event.target.value)}
                            />
                          </Field>
                          <Field label="preferred_mcp">
                            <input
                              type="text"
                              value={formatCsv(agent.preferred_mcp || [])}
                              onChange={(event) => updateAgentField(name, "preferred_mcp", event.target.value)}
                            />
                          </Field>
                          <Field
                            label="env 映射"
                            full
                            hint="每行一个 KEY=VALUE。常见的 API key/base_url 都放这里。"
                          >
                            <textarea
                              rows={3}
                              value={agentEnvTexts[name] ?? formatKeyValueLines(agent.env || {})}
                              onChange={(event) => updateAgentEnvText(name, event.target.value)}
                            />
                          </Field>
                        </div>

                        <div className="panel-hint" style={{ marginTop: 8 }}>
                          env keys: {(agent.env_keys || []).join(", ") || "-"}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="muted">暂无 agent 配置</div>
                  )}
                </div>
              </section>
            </div>
          ) : null}

          {tab === "doctor" ? (
            <div className="tab-panel">
              <section className="panel">
                <div className="panel-header">
                  <h2>Doctor</h2>
                  <span className="panel-hint">Codex / Claude / MCP / 配置 / key</span>
                </div>
                <div className="summary-grid">
                  <div className="summary-card">
                    <div className="summary-label">总计</div>
                    <div className="summary-value">{doctor.summary?.total ?? 0}</div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-label">通过</div>
                    <div className="summary-value">{doctor.summary?.passed ?? 0}</div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-label">失败</div>
                    <div className="summary-value">{doctor.summary?.failed ?? 0}</div>
                  </div>
                </div>
                <div className="timeline" style={{ marginTop: 12 }}>
                  {(doctor.checks || []).map((check) => (
                    <div className="event" key={check.name}>
                      <div className="event-head">
                        <span>{check.name}</span>
                        <span className={`event-kind ${check.ok ? "status-ok" : "status-bad"}`}>{check.ok ? "OK" : "FAIL"}</span>
                      </div>
                      <div className="event-message">{check.detail || "-"}</div>
                      {check.hint ? <div className="panel-hint" style={{ marginTop: 6 }}>{check.hint}</div> : null}
                    </div>
                  ))}
                </div>
              </section>

              <section className="panel">
                <div className="panel-header">
                  <h2>Integrations</h2>
                  <span className="panel-hint">可插拔执行器 / worker（OpenHands 非必需）</span>
                </div>
                <div className="panel-hint" style={{ marginTop: 6 }}>
                  主流程只依赖 Codex / Claude / DeepSeek / LangGraph / OpenAI Agents SDK；OpenHands 仅用于对比和扩展。
                </div>
                <div className="item-list">
                  {integrations.length ? (
                    integrations.map((integration) => (
                      <div className="item" key={integration.name}>
                        <div className="item-title">
                          {integration.name} {integration.installed ? "(installed)" : "(missing)"}
                        </div>
                        <div className="item-sub">{integration.detail}</div>
                        <div className="panel-hint" style={{ marginTop: 6 }}>
                          {integration.use_for}
                        </div>
                        {!integration.installed ? (
                          <div className="panel-hint" style={{ marginTop: 6 }}>
                            {integration.install_hint}
                          </div>
                        ) : null}
                      </div>
                    ))
                  ) : (
                    <div className="muted">暂无集成信息</div>
                  )}
                </div>
              </section>

              <section className="panel">
                <div className="panel-header">
                  <h2>Tools</h2>
                  <span className="panel-hint">可选 CLI 工具（建议独立安装，不污染主环境）</span>
                </div>
                <div className="item-list">
                  {tools.length ? (
                    tools.map((tool) => (
                      <div className="item" key={tool.name}>
                        <div className="item-title">
                          {tool.name} {tool.installed ? "(installed)" : "(missing)"}
                        </div>
                        <div className="item-sub">
                          cmd: {tool.command}
                          {tool.command_path ? ` | path: ${tool.command_path}` : ""}
                          {!tool.command_path && tool.local_command_path ? ` | local: ${tool.local_command_path}` : ""}
                        </div>
                        {!tool.installed ? (
                          <div className="panel-hint" style={{ marginTop: 6 }}>
                            {tool.install_hint}
                          </div>
                        ) : null}
                      </div>
                    ))
                  ) : (
                    <div className="muted">暂无工具信息</div>
                  )}
                </div>
              </section>
            </div>
          ) : null}
        </section>
      </main>

      <div className={`toast ${toast.visible ? "show" : ""} ${toast.kind}`.trim()}>{toast.text}</div>
    </div>
  );
}

export default App;
