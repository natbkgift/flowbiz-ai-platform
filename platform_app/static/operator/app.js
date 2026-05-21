"use strict";

const state = {
  token: "",
  view: "dashboard",
  projects: [],
  policy: null,
  selectedTaskId: null,
};

const $ = (sel, parent = document) => parent.querySelector(sel);
const $$ = (sel, parent = document) => Array.from(parent.querySelectorAll(sel));

function setView(name) {
  state.view = name;
  $$(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === name);
  });
  $$(".pane").forEach((pane) => {
    const expected =
      name === "task-detail" ? "task-detail" : name;
    pane.classList.toggle("hidden", pane.dataset.pane !== expected);
  });
  if (name === "dashboard") loadDashboard();
  else if (name === "projects") loadProjects();
  else if (name === "tasks") loadTasks();
  else if (name === "approvals") loadApprovals();
  else if (name === "workers") loadWorkers();
  else if (name === "audit") loadAudit();
  else if (name === "reports") loadReports();
  else if (name === "health") loadHealth();
}

async function api(path, options = {}) {
  if (!state.token) throw new Error("missing operator token");
  const headers = Object.assign(
    {
      Accept: "application/json",
      Authorization: `Bearer ${state.token}`,
    },
    options.headers || {}
  );
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`/internal/operator${path}`, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
    credentials: "omit",
  });
  if (res.status === 401 || res.status === 403) {
    state.token = "";
    showAuthPane();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`api ${path} -> ${res.status}: ${text.slice(0, 200)}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

function showAuthPane() {
  $$(".pane").forEach((pane) => pane.classList.add("hidden"));
  $('section[data-pane="auth"]').classList.remove("hidden");
}

function setLastRefresh() {
  $("#last-refresh").textContent = `updated ${new Date().toLocaleTimeString()}`;
}

function fmtTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch (_) {
    return value;
  }
}

function pillForStatus(status) {
  const cls = {
    queued: "pill-info",
    claimed: "pill-info",
    running: "pill-info",
    requires_approval: "pill-warn",
    approved: "pill-info",
    rejected: "pill-bad",
    completed: "pill-ok",
    failed: "pill-bad",
    cancelled: "pill-muted",
  }[status] || "pill-muted";
  return `<span class="pill ${cls}">${status}</span>`;
}

function pillForHealth(value) {
  const cls = {
    healthy: "pill-ok",
    stale: "pill-warn",
    offline: "pill-bad",
    unknown: "pill-muted",
  }[value] || "pill-muted";
  return `<span class="pill ${cls}">${value}</span>`;
}

function renderTable(target, columns, rows, opts = {}) {
  const head = columns
    .map((col) => `<th>${col.label}</th>`)
    .join("");
  if (!rows.length) {
    target.innerHTML =
      `<thead><tr>${head}</tr></thead>` +
      `<tbody><tr><td colspan="${columns.length}" class="muted">No records.</td></tr></tbody>`;
    return;
  }
  const body = rows
    .map((row) => {
      const cells = columns
        .map((col) => `<td>${col.render(row)}</td>`)
        .join("");
      const onClick = opts.onRowClick ? ` data-row-id="${row.id || ""}"` : "";
      const cls = opts.onRowClick ? ' class="clickable"' : "";
      return `<tr${cls}${onClick}>${cells}</tr>`;
    })
    .join("");
  target.innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;
  if (opts.onRowClick) {
    $$("tr.clickable", target).forEach((tr) => {
      tr.addEventListener("click", () => {
        const rowId = tr.dataset.rowId;
        const row = rows.find((r) => (r.id || "") === rowId);
        if (row) opts.onRowClick(row);
      });
    });
  }
}

async function loadDashboard() {
  setLastRefresh();
  try {
    const summary = await api("/api/dashboard/summary");
    const cards = [
      { label: "Projects", value: summary.project_count },
      { label: "Tasks", value: summary.task_count },
      { label: "Queued", value: summary.queued, cls: summary.queued ? "ok" : "" },
      { label: "Claimed", value: summary.claimed },
      { label: "Running", value: summary.running },
      { label: "Approval pending", value: summary.requires_approval, cls: summary.requires_approval ? "warn" : "" },
      { label: "Approved", value: summary.approved },
      { label: "Rejected", value: summary.rejected },
      { label: "Completed", value: summary.completed, cls: "ok" },
      { label: "Failed", value: summary.failed, cls: summary.failed ? "alert" : "" },
      { label: "Recent denials (24h)", value: summary.recent_policy_denials, cls: summary.recent_policy_denials ? "warn" : "" },
      { label: "Healthy workers", value: summary.healthy_workers, cls: summary.healthy_workers ? "ok" : "" },
      { label: "Stale workers", value: summary.stale_workers, cls: summary.stale_workers ? "warn" : "" },
    ];
    $("#dashboard-cards").innerHTML = cards
      .map(
        (c) =>
          `<div class="metric ${c.cls || ""}"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`
      )
      .join("");

    const events = await api("/api/events?limit=10");
    renderTable(
      $("#dashboard-recent"),
      [
        { label: "When", render: (e) => fmtTime(e.created_at) },
        { label: "Event", render: (e) => `<code>${e.event_type}</code>` },
        { label: "Status", render: (e) => pillForStatus(e.status) },
        { label: "Actor", render: (e) => `${e.actor_type}:${e.actor_id}` },
        { label: "Task", render: (e) => `<code>${e.task_id}</code>` },
      ],
      events.events
    );
  } catch (err) {
    console.warn(err);
  }
}

async function loadProjects() {
  setLastRefresh();
  try {
    const data = await api("/api/projects");
    state.projects = data.projects || [];
    refreshProjectFilter();
    renderTable(
      $("#projects-table"),
      [
        { label: "Name", render: (p) => p.name },
        { label: "Description", render: (p) => p.description || "—" },
        {
          label: "Repo targets",
          render: (p) =>
            (p.repo_targets || [])
              .map((r) => `<code>${r.name}</code>`)
              .join(", ") || "—",
        },
        { label: "Created", render: (p) => fmtTime(p.created_at) },
        { label: "ID", render: (p) => `<code>${p.id}</code>` },
      ],
      state.projects
    );
  } catch (err) {
    console.warn(err);
  }
}

function refreshProjectFilter() {
  const sel = $("#task-project-filter");
  const current = sel.value;
  sel.innerHTML =
    '<option value="">all</option>' +
    state.projects
      .map((p) => `<option value="${p.id}">${p.name}</option>`)
      .join("");
  sel.value = current;
}

async function loadTasks() {
  setLastRefresh();
  if (!state.projects.length) {
    try {
      const data = await api("/api/projects");
      state.projects = data.projects || [];
      refreshProjectFilter();
    } catch (_) {}
  }
  const status = $("#task-status-filter").value;
  const projectId = $("#task-project-filter").value;
  const search = $("#task-search").value.trim().toLowerCase();
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (projectId) params.set("project_id", projectId);
  try {
    const data = await api(`/api/tasks?${params.toString()}`);
    let rows = data.tasks || [];
    if (search) {
      rows = rows.filter(
        (t) =>
          (t.title || "").toLowerCase().includes(search) ||
          (t.id || "").toLowerCase().includes(search)
      );
    }
    rows.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    renderTable(
      $("#tasks-table"),
      [
        { label: "Created", render: (t) => fmtTime(t.created_at) },
        { label: "Title", render: (t) => t.title },
        { label: "Project", render: (t) => `<code>${t.project_id}</code>` },
        { label: "Action", render: (t) => `<code>${t.action}</code>` },
        { label: "Status", render: (t) => pillForStatus(t.status) },
        { label: "Worker", render: (t) => t.claimed_by || "—" },
        { label: "Updated", render: (t) => fmtTime(t.updated_at) },
        { label: "ID", render: (t) => `<code>${t.id}</code>` },
      ],
      rows,
      { onRowClick: (row) => openTaskDetail(row.id) }
    );
  } catch (err) {
    console.warn(err);
  }
}

async function openTaskDetail(taskId) {
  state.selectedTaskId = taskId;
  setView("task-detail");
  setLastRefresh();
  try {
    const task = await api(`/api/tasks/${taskId}`);
    const events = await api(`/api/events?task_id=${taskId}&limit=200`);
    const audit = await api(`/api/audit?task_id=${taskId}&limit=200`);
    $("#task-detail-title").textContent = `Task: ${task.title}`;
    const result = task.result || {};
    const resultText = JSON.stringify(result, null, 2);
    $("#task-detail-body").innerHTML = `
      <div class="card">
        <div class="kv">
          <div class="k">ID</div><div class="v"><code>${task.id}</code></div>
          <div class="k">Project</div><div class="v"><code>${task.project_id}</code></div>
          <div class="k">Action</div><div class="v"><code>${task.action}</code></div>
          <div class="k">Status</div><div class="v">${pillForStatus(task.status)}</div>
          <div class="k">Approval required</div><div class="v">${task.approval_required ? "yes" : "no"}</div>
          <div class="k">Policy</div><div class="v">${task.policy_decision?.effect || "—"} — ${task.policy_decision?.reason || ""}</div>
          <div class="k">Claimed by</div><div class="v">${task.claimed_by || "—"}</div>
          <div class="k">Heartbeat</div><div class="v">${fmtTime(task.heartbeat_at)}</div>
          <div class="k">Completed</div><div class="v">${fmtTime(task.completed_at)}</div>
          <div class="k">Failed</div><div class="v">${fmtTime(task.failed_at)}</div>
          <div class="k">Error</div><div class="v">${task.error || "—"}</div>
          <div class="k">Target paths</div><div class="v"><code>${(task.target_paths || []).join(", ") || "—"}</code></div>
          <div class="k">Instructions</div><div class="v">${task.instructions || "—"}</div>
        </div>
      </div>

      ${task.status === "requires_approval" ? renderApproveControls(task) : ""}

      <div class="card">
        <h3>Hermes / deterministic output</h3>
        <p class="muted">Hermes used: <strong>${result.hermes_used ? "yes" : "no"}</strong>${result.hermes_skipped_reason ? ` — ${result.hermes_skipped_reason}` : ""}</p>
        <pre class="code">${escapeHtml(resultText)}</pre>
      </div>

      <div class="card">
        <h3>Events</h3>
        ${tableHtml(events.events || [], [
          { label: "When", get: (e) => fmtTime(e.created_at) },
          { label: "Event", get: (e) => `<code>${e.event_type}</code>` },
          { label: "Status", get: (e) => pillForStatus(e.status) },
          { label: "Actor", get: (e) => `${e.actor_type}:${e.actor_id}` },
          { label: "Message", get: (e) => e.message || "—" },
        ])}
      </div>

      <div class="card">
        <h3>Audit</h3>
        ${tableHtml(audit.logs || [], [
          { label: "When", get: (l) => fmtTime(l.created_at) },
          { label: "Event", get: (l) => `<code>${l.event_type}</code>` },
          { label: "Actor", get: (l) => `${l.actor_type}:${l.actor_id}` },
          { label: "Action", get: (l) => l.action || "—" },
          { label: "Data", get: (l) => `<code>${escapeHtml(JSON.stringify(l.data || {}))}</code>` },
        ])}
      </div>
    `;
    bindApprovalButtons(task);
  } catch (err) {
    console.warn(err);
  }
}

function renderApproveControls(task) {
  return `
    <div class="card warn-card">
      <strong>Operator decision required.</strong>
      Approving updates state in core only. The current Hermes worker is read-only and
      will not execute write/deploy/restart actions even after approval.
      <div class="row" style="margin-top:10px;">
        <input id="approve-operator-id" placeholder="operator id (e.g. ops-1)" value="ops-console" />
        <input id="approve-reason" placeholder="reason (optional)" />
        <button id="approve-btn" class="btn btn-primary" data-task="${task.id}">Approve</button>
        <button id="reject-btn" class="btn btn-danger" data-task="${task.id}">Reject</button>
      </div>
      <p id="approve-error" class="error"></p>
    </div>
  `;
}

function bindApprovalButtons(task) {
  const approve = $("#approve-btn");
  const reject = $("#reject-btn");
  if (!approve || !reject) return;
  const handler = async (decisionPath) => {
    const operatorId = $("#approve-operator-id").value.trim() || "ops-console";
    const reason = $("#approve-reason").value.trim() || null;
    try {
      await api(`/api/tasks/${task.id}/${decisionPath}`, {
        method: "POST",
        body: { operator_id: operatorId, reason },
      });
      openTaskDetail(task.id);
    } catch (err) {
      $("#approve-error").textContent = err.message;
    }
  };
  approve.addEventListener("click", () => handler("approve"));
  reject.addEventListener("click", () => handler("reject"));
}

function tableHtml(rows, columns) {
  if (!rows.length) {
    return `<table class="data-table"><thead><tr>${columns
      .map((c) => `<th>${c.label}</th>`)
      .join("")}</tr></thead><tbody><tr><td colspan="${columns.length}" class="muted">No records.</td></tr></tbody></table>`;
  }
  const head = columns.map((c) => `<th>${c.label}</th>`).join("");
  const body = rows
    .map(
      (row) =>
        `<tr>${columns.map((c) => `<td>${c.get(row)}</td>`).join("")}</tr>`
    )
    .join("");
  return `<table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function loadApprovals() {
  setLastRefresh();
  try {
    const data = await api("/api/tasks?status=requires_approval");
    renderTable(
      $("#approvals-pending-table"),
      [
        { label: "Created", render: (t) => fmtTime(t.created_at) },
        { label: "Title", render: (t) => t.title },
        { label: "Action", render: (t) => `<code>${t.action}</code>` },
        { label: "Project", render: (t) => `<code>${t.project_id}</code>` },
        { label: "ID", render: (t) => `<code>${t.id}</code>` },
      ],
      data.tasks || [],
      { onRowClick: (row) => openTaskDetail(row.id) }
    );
    const history = await api("/api/approvals?limit=100");
    renderTable(
      $("#approvals-history-table"),
      [
        { label: "When", render: (a) => fmtTime(a.created_at) },
        { label: "Decision", render: (a) => pillForStatus(a.decision) },
        { label: "Operator", render: (a) => a.operator_id },
        { label: "Reason", render: (a) => a.reason || "—" },
        { label: "Task", render: (a) => `<code>${a.task_id}</code>` },
      ],
      history.approvals || []
    );
  } catch (err) {
    console.warn(err);
  }
}

async function loadWorkers() {
  setLastRefresh();
  try {
    const data = await api("/api/workers/summary");
    const c = data.constraints || {};
    $("#worker-constraints").innerHTML = `
      <h3>Runtime constraints (enforced)</h3>
      <div class="kv">
        <div class="k">No public port</div><div class="v">${c.no_public_port ? "yes" : "no"}</div>
        <div class="k">Read-only</div><div class="v">${c.read_only ? "yes" : "no"}</div>
        <div class="k">No docker socket</div><div class="v">${c.no_docker_socket ? "yes" : "no"}</div>
        <div class="k">No SSH</div><div class="v">${c.no_ssh ? "yes" : "no"}</div>
        <div class="k">No secrets mounted</div><div class="v">${c.no_secrets_mounted ? "yes" : "no"}</div>
        <div class="k">Allowed modes</div><div class="v"><code>${(c.allowed_modes || []).join(", ")}</code></div>
      </div>
    `;
    renderTable(
      $("#workers-table"),
      [
        { label: "Worker", render: (w) => `<code>${w.worker_id}</code>` },
        { label: "Health", render: (w) => pillForHealth(w.health) },
        { label: "Last heartbeat", render: (w) => fmtTime(w.last_heartbeat_at) },
        { label: "Last claimed", render: (w) => fmtTime(w.last_claimed_at) },
        { label: "Current task", render: (w) => w.current_task_id ? `<code>${w.current_task_id}</code> ${pillForStatus(w.current_task_status)}` : "—" },
        { label: "Mode", render: () => `<span class="pill pill-info">read-only</span>` },
      ],
      data.workers || []
    );
  } catch (err) {
    console.warn(err);
  }
}

async function loadAudit() {
  setLastRefresh();
  const eventType = $("#audit-event-filter").value.trim();
  try {
    const audit = await api(
      `/api/audit?limit=200${eventType ? `&event_type=${encodeURIComponent(eventType)}` : ""}`
    );
    renderTable(
      $("#audit-table"),
      [
        { label: "When", render: (l) => fmtTime(l.created_at) },
        { label: "Event", render: (l) => `<code>${l.event_type}</code>` },
        { label: "Actor", render: (l) => `${l.actor_type}:${l.actor_id}` },
        { label: "Task", render: (l) => l.task_id ? `<code>${l.task_id}</code>` : "—" },
        { label: "Action", render: (l) => l.action || "—" },
      ],
      audit.logs || []
    );
    const events = await api("/api/events?limit=200");
    renderTable(
      $("#events-table"),
      [
        { label: "When", render: (e) => fmtTime(e.created_at) },
        { label: "Event", render: (e) => `<code>${e.event_type}</code>` },
        { label: "Status", render: (e) => pillForStatus(e.status) },
        { label: "Actor", render: (e) => `${e.actor_type}:${e.actor_id}` },
        { label: "Task", render: (e) => `<code>${e.task_id}</code>` },
      ],
      events.events || []
    );
  } catch (err) {
    console.warn(err);
  }
}

async function loadReports() {
  setLastRefresh();
  try {
    const data = await api("/api/tasks?status=completed");
    const tasks = (data.tasks || []).filter((t) => t.result);
    renderTable(
      $("#reports-table"),
      [
        { label: "Completed", render: (t) => fmtTime(t.completed_at) },
        { label: "Title", render: (t) => t.title },
        { label: "Mode", render: (t) => `<code>${(t.result || {}).mode || (t.metadata || {}).mode || "—"}</code>` },
        { label: "Hermes used", render: (t) => (t.result || {}).hermes_used ? "yes" : "no" },
        { label: "Summary", render: (t) => `<code>${escapeHtml(JSON.stringify((t.result || {}).summary || {}).slice(0, 120))}</code>` },
        { label: "ID", render: (t) => `<code>${t.id}</code>` },
      ],
      tasks,
      { onRowClick: (row) => openTaskDetail(row.id) }
    );
  } catch (err) {
    console.warn(err);
  }
}

async function loadHealth() {
  setLastRefresh();
  try {
    const data = await api("/api/health");
    const cards = [
      { label: "Platform", value: data.platform?.status || "?", cls: data.platform?.reachable ? "ok" : "alert" },
      { label: "Core", value: data.core?.status || "?", cls: data.core?.reachable ? "ok" : "alert" },
      { label: "Public canary", value: data.public_canary?.status || "?", cls: data.public_canary?.status === "ok" ? "ok" : (data.public_canary?.status === "not_configured" ? "" : "warn") },
      { label: "Legacy upstream", value: data.legacy_upstream?.status || "?", cls: data.legacy_upstream?.status === "ok" ? "ok" : (data.legacy_upstream?.status === "not_configured" ? "" : "warn") },
    ];
    $("#health-cards").innerHTML = cards
      .map(
        (c) =>
          `<div class="metric ${c.cls}"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`
      )
      .join("");
    const warnings = data.warnings || [];
    $("#health-warnings").innerHTML = warnings.length
      ? `<strong>Warnings</strong><ul>${warnings.map((w) => `<li>${w}</li>`).join("")}</ul>`
      : '<span class="muted">No warnings.</span>';
    const pill = $("#health-pill");
    if (data.core?.reachable && data.platform?.reachable) {
      pill.className = "pill pill-ok";
      pill.textContent = "health: ok";
    } else {
      pill.className = "pill pill-bad";
      pill.textContent = "health: degraded";
    }
  } catch (err) {
    console.warn(err);
  }
}

async function authenticate() {
  const token = $("#operator-token").value.trim();
  if (!token) {
    $("#auth-error").textContent = "Token required.";
    return;
  }
  state.token = token;
  try {
    state.policy = await api("/api/policy");
    $("#auth-error").textContent = "";
    $('section[data-pane="auth"]').classList.add("hidden");
    setView("dashboard");
  } catch (err) {
    state.token = "";
    $("#auth-error").textContent = err.message;
  }
}

function bindUI() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => setView(tab.dataset.view));
  });
  $("#refresh-btn").addEventListener("click", () => setView(state.view));
  $("#auth-btn").addEventListener("click", authenticate);
  $("#operator-token").addEventListener("keydown", (e) => {
    if (e.key === "Enter") authenticate();
  });
  $("#task-status-filter").addEventListener("change", loadTasks);
  $("#task-project-filter").addEventListener("change", loadTasks);
  $("#task-search").addEventListener("input", () => {
    clearTimeout(window.__taskSearchTimer);
    window.__taskSearchTimer = setTimeout(loadTasks, 200);
  });
  $("#audit-event-filter").addEventListener("input", () => {
    clearTimeout(window.__auditTimer);
    window.__auditTimer = setTimeout(loadAudit, 250);
  });
  $("#task-detail-back").addEventListener("click", () => setView("tasks"));
}

document.addEventListener("DOMContentLoaded", () => {
  bindUI();
  showAuthPane();
});
