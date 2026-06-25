const state = {
  runId: runIdFromLocation(),
  data: null,
};

const els = {
  runTitle: document.querySelector("#runTitle"),
  runStatus: document.querySelector("#runStatus"),
  traceId: document.querySelector("#traceId"),
  datasetId: document.querySelector("#datasetId"),
  updatedAt: document.querySelector("#updatedAt"),
  artifactCount: document.querySelector("#artifactCount"),
  taskText: document.querySelector("#taskText"),
  errorText: document.querySelector("#errorText"),
  graphNodes: document.querySelector("#graphNodes"),
  workflowJobs: document.querySelector("#workflowJobs"),
  timeline: document.querySelector("#timeline"),
  artifacts: document.querySelector("#artifacts"),
  evaluations: document.querySelector("#evaluations"),
  events: document.querySelector("#events"),
};

function runIdFromLocation() {
  const match = window.location.pathname.match(/\/run-inspector\/runs\/([^/]+)\/?$/);
  if (match) {
    return decodeURIComponent(match[1]);
  }
  return new URLSearchParams(window.location.search).get("run_id") || "";
}

async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) {
    return "--";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function pillClass(status) {
  return `mini-pill status-${String(status || "").replaceAll("_", "-")}`;
}

function renderEmpty(label) {
  return `<p class="empty">${escapeHtml(label)}</p>`;
}

function renderMeta(parts) {
  return `<div class="meta-line">${parts
    .filter((part) => part !== null && part !== undefined && part !== "")
    .map((part) => `<span>${escapeHtml(part)}</span>`)
    .join("")}</div>`;
}

function renderRun() {
  const { run } = state.data;
  document.title = `${run.id} | Run Inspector`;
  els.runTitle.textContent = run.id;
  els.runStatus.textContent = run.status;
  els.runStatus.className = `status-pill status-${run.status}`;
  els.traceId.textContent = run.trace_id || "--";
  els.datasetId.textContent = run.dataset_artifact_id || "--";
  els.updatedAt.textContent = formatDate(run.updated_at);
  els.artifactCount.textContent = String(run.artifacts.length);
  els.taskText.textContent = run.task;
  els.errorText.textContent = run.error_summary || "";
}

function renderNodes() {
  const nodes = state.data.graphNodes;
  els.graphNodes.innerHTML = nodes.length
    ? nodes
        .map(
          (node) => `
            <article class="node-item">
              <div class="node-main">
                <strong>${escapeHtml(node.id)}</strong>
                <span class="${pillClass(node.status)}">${escapeHtml(node.status)}</span>
              </div>
              ${renderMeta([
                node.agent_type,
                `retries ${node.retry_count}`,
                `updated ${formatDate(node.updated_at)}`,
              ])}
              ${renderMeta([
                `depends: ${node.depends_on.join(", ") || "none"}`,
                `tools: ${node.required_tools.join(", ") || "none"}`,
              ])}
              ${renderMeta([`expects: ${node.expected_artifacts.join(", ") || "none"}`])}
            </article>`
        )
        .join("")
    : renderEmpty("No graph nodes recorded.");
}

function renderJobs() {
  const jobs = state.data.jobs;
  els.workflowJobs.innerHTML = jobs.length
    ? jobs
        .map(
          (job) => `
            <article class="compact-item">
              <div class="compact-main">
                <strong>${escapeHtml(job.workflow_name)}</strong>
                <span class="${pillClass(job.status)}">${escapeHtml(job.status)}</span>
              </div>
              ${renderMeta([
                job.id,
                `attempts ${job.attempt_count}/${job.max_attempts}`,
                job.worker_id ? `worker ${job.worker_id}` : null,
              ])}
              ${job.error_summary ? renderMeta([job.error_summary]) : ""}
            </article>`
        )
        .join("")
    : renderEmpty("No workflow jobs recorded.");
}

function renderTimeline() {
  const items = state.data.timeline;
  els.timeline.innerHTML = items.length
    ? items
        .map(
          (item) => `
            <article class="timeline-item">
              <div class="timeline-main">
                <strong>${escapeHtml(item.title)}</strong>
                <span>${escapeHtml(formatDate(item.timestamp))}</span>
              </div>
              ${renderMeta([
                item.kind,
                item.status,
                item.node_id ? `node ${item.node_id}` : null,
                item.artifact_id ? `artifact ${item.artifact_id}` : null,
                item.workflow_job_id ? `job ${item.workflow_job_id}` : null,
              ])}
              ${item.summary ? renderMeta([item.summary]) : ""}
            </article>`
        )
        .join("")
    : renderEmpty("No timeline entries recorded.");
}

function renderArtifacts() {
  const artifacts = state.data.run.artifacts;
  els.artifacts.innerHTML = artifacts.length
    ? artifacts
        .map(
          (artifact) => `
            <article class="compact-item">
              <div class="compact-main">
                <strong>${escapeHtml(artifact.type)}</strong>
                <span class="mini-pill">${escapeHtml(artifact.producer_node_id || "input")}</span>
              </div>
              ${renderMeta([artifact.id, artifact.uri])}
            </article>`
        )
        .join("")
    : renderEmpty("No artifacts recorded.");
}

function renderEvaluations() {
  const evaluations = state.data.run.evaluations;
  els.evaluations.innerHTML = evaluations.length
    ? evaluations
        .map(
          (evaluation) => `
            <article class="compact-item">
              <div class="compact-main">
                <strong>${escapeHtml(evaluation.id)}</strong>
                <span class="${pillClass(evaluation.passed ? "passed" : "failed")}">
                  ${evaluation.passed ? "passed" : "failed"}
                </span>
              </div>
              ${renderMeta([
                `score ${evaluation.score}`,
                evaluation.target_artifact_id ? `artifact ${evaluation.target_artifact_id}` : null,
                `${evaluation.checks.length} checks`,
              ])}
            </article>`
        )
        .join("")
    : renderEmpty("No evaluations recorded.");
}

function renderEvents() {
  const events = state.data.events;
  els.events.innerHTML = events.length
    ? events
        .slice()
        .reverse()
        .map(
          (event) => `
            <article class="event-item">
              <div class="compact-main">
                <strong>${escapeHtml(event.event_type)}</strong>
                <span>${escapeHtml(formatDate(event.created_at))}</span>
              </div>
              ${renderMeta([event.node_id, event.id])}
              <pre class="event-payload">${escapeHtml(JSON.stringify(event.payload, null, 2))}</pre>
            </article>`
        )
        .join("")
    : renderEmpty("No events recorded.");
}

function renderAll() {
  renderRun();
  renderNodes();
  renderJobs();
  renderTimeline();
  renderArtifacts();
  renderEvaluations();
  renderEvents();
}

async function loadRun() {
  if (!state.runId) {
    els.taskText.textContent = "Run ID missing.";
    return;
  }

  try {
    const [run, jobs, graphNodes, events, timeline] = await Promise.all([
      fetchJson(`/runs/${encodeURIComponent(state.runId)}`),
      fetchJson(`/runs/${encodeURIComponent(state.runId)}/workflow-jobs`),
      fetchJson(`/runs/${encodeURIComponent(state.runId)}/graph-nodes`),
      fetchJson(`/runs/${encodeURIComponent(state.runId)}/events`),
      fetchJson(`/runs/${encodeURIComponent(state.runId)}/timeline`),
    ]);
    state.data = { run, jobs, graphNodes, events, timeline };
    renderAll();
  } catch (error) {
    els.runTitle.textContent = state.runId;
    els.runStatus.textContent = "Error";
    els.runStatus.className = "status-pill status-failed";
    els.errorText.textContent = error.message;
    els.taskText.textContent = "Unable to load run inspection data.";
  }
}

loadRun();
