const state = {
  runs: [],
  dataSources: [],
  loadingRuns: false,
  creatingRun: false,
  searchQuery: "",
  statusFilter: "all",
};

const els = {
  refreshRuns: document.querySelector("#refreshRuns"),
  runsList: document.querySelector("#runsList"),
  runCount: document.querySelector("#runCount"),
  sourceStatus: document.querySelector("#sourceStatus"),
  createRunForm: document.querySelector("#createRunForm"),
  createRunButton: document.querySelector("#createRunButton"),
  taskInput: document.querySelector("#taskInput"),
  sourceField: document.querySelector("#sourceField"),
  uriField: document.querySelector("#uriField"),
  dataSourceSelect: document.querySelector("#dataSourceSelect"),
  datasetUriInput: document.querySelector("#datasetUriInput"),
  formStatus: document.querySelector("#formStatus"),
  createdRun: document.querySelector("#createdRun"),
  totalWorkflowCount: document.querySelector("#totalWorkflowCount"),
  completedWorkflowCount: document.querySelector("#completedWorkflowCount"),
  activeWorkflowCount: document.querySelector("#activeWorkflowCount"),
  attentionWorkflowCount: document.querySelector("#attentionWorkflowCount"),
  runSearch: document.querySelector("#runSearch"),
  runStatusFilter: document.querySelector("#runStatusFilter"),
};

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(formatErrorDetail(body.detail) || `Request failed: ${response.status}`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function formatErrorDetail(detail) {
  if (!detail) {
    return "";
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map(formatErrorDetail).filter(Boolean).join(" ");
  }
  if (typeof detail === "object") {
    return detail.message || detail.msg || JSON.stringify(detail);
  }
  return String(detail);
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
  }).format(new Date(value));
}

function label(value) {
  return String(value ?? "unknown")
    .replaceAll("_", " ")
    .replaceAll("-", " ");
}

function titleLabel(value) {
  const acronyms = {
    api: "API",
    csv: "CSV",
    github: "GitHub",
    id: "ID",
    json: "JSON",
    kpi: "KPI",
    mlflow: "MLflow",
    sqlite: "SQLite",
    sql: "SQL",
    uri: "URI",
  };
  return label(value)
    .split(" ")
    .filter(Boolean)
    .map((word) => {
      const key = word.toLowerCase();
      return acronyms[key] || key[0].toUpperCase() + key.slice(1);
    })
    .join(" ");
}

function statusClass(status) {
  return `status-pill status-${String(status || "")
    .toLowerCase()
    .replaceAll("_", "-")
    .replaceAll(" ", "-")}`;
}

function inspectorUrl(runId) {
  return `/run-inspector/runs/${encodeURIComponent(runId)}`;
}

function shortId(value) {
  const text = String(value || "");
  return text.length > 16 ? `${text.slice(0, 8)}...${text.slice(-5)}` : text;
}

function workflowTitle(task) {
  const text = String(task || "Untitled workflow").trim();
  return text.length > 86 ? `${text.slice(0, 83).trimEnd()}...` : text;
}

function visibleRuns() {
  const query = state.searchQuery.trim().toLowerCase();
  return state.runs.filter((run) => {
    const matchesStatus = state.statusFilter === "all" || run.status === state.statusFilter;
    const matchesQuery = !query || `${run.task} ${run.id}`.toLowerCase().includes(query);
    return matchesStatus && matchesQuery;
  });
}

function renderWorkflowSummary() {
  const activeStatuses = new Set(["running", "queued", "pending", "waiting_for_approval"]);
  const attentionStatuses = new Set(["failed", "dead_letter", "denied"]);
  els.totalWorkflowCount.textContent = state.runs.length;
  els.completedWorkflowCount.textContent = state.runs.filter(
    (run) => run.status === "completed"
  ).length;
  els.activeWorkflowCount.textContent = state.runs.filter((run) =>
    activeStatuses.has(run.status)
  ).length;
  els.attentionWorkflowCount.textContent = state.runs.filter((run) =>
    attentionStatuses.has(run.status)
  ).length;
}

function setFormStatus(message, kind = "") {
  els.formStatus.textContent = message;
  els.formStatus.className = `action-text${kind ? ` action-${kind}` : ""}`;
}

function selectedDatasetMode() {
  const selected = els.createRunForm.querySelector('input[name="datasetMode"]:checked');
  return selected ? selected.value : "none";
}

function updateDatasetFields() {
  const mode = selectedDatasetMode();
  els.sourceField.hidden = mode !== "source";
  els.uriField.hidden = mode !== "uri";
  els.dataSourceSelect.disabled = mode !== "source";
  els.datasetUriInput.disabled = mode !== "uri";
}

function renderSources() {
  const sources = state.dataSources;
  els.dataSourceSelect.innerHTML = sources.length
    ? sources
        .map(
          (source) => `
            <option value="${escapeHtml(source.id)}">
              ${escapeHtml(source.name)} (${escapeHtml(titleLabel(source.source_type))})
            </option>`
        )
        .join("")
    : '<option value="">No registered sources</option>';
  els.sourceStatus.textContent = sources.length
    ? `${sources.length} source${sources.length === 1 ? "" : "s"}`
    : "Demo ready";
}

function renderRuns() {
  const filteredRuns = visibleRuns();
  els.runCount.textContent = state.loadingRuns
    ? "Loading"
    : state.searchQuery || state.statusFilter !== "all"
      ? `${filteredRuns.length} of ${state.runs.length}`
      : `${state.runs.length} workflow${state.runs.length === 1 ? "" : "s"}`;

  if (state.loadingRuns) {
    els.runsList.innerHTML = '<p class="empty">Loading recent runs.</p>';
    return;
  }
  if (!filteredRuns.length) {
    els.runsList.innerHTML = '<p class="empty">No workflows match the current view.</p>';
    return;
  }

  const runs = [...filteredRuns].sort(
    (left, right) => new Date(right.updated_at) - new Date(left.updated_at)
  );
  els.runsList.innerHTML = runs.map(renderRunItem).join("");
}

function renderRunItem(run) {
  const outputCount = Array.isArray(run.artifacts)
    ? run.artifacts.length
    : run.status === "completed"
      ? "Ready"
      : "--";
  const sourceLabel = run.dataset_artifact_id ? "Dataset attached" : "No dataset";
  return `
    <article class="run-item">
      <a class="run-row-link" href="${inspectorUrl(run.id)}">
        <div class="run-identity">
          <span class="workflow-title">${escapeHtml(
            workflowTitle(run.task)
          )}</span>
          <span class="run-subline">
            <code title="${escapeHtml(run.id)}">${escapeHtml(shortId(run.id))}</code>
            <span>${escapeHtml(sourceLabel)}</span>
          </span>
        </div>
        <span class="${statusClass(run.status)}">${escapeHtml(titleLabel(run.status))}</span>
        <span class="run-output-count">${escapeHtml(outputCount)}</span>
        <time datetime="${escapeHtml(run.updated_at || "")}">${escapeHtml(
          formatDate(run.updated_at)
        )}</time>
        <span class="row-arrow" aria-hidden="true">&#8594;</span>
      </a>
    </article>`;
}

function renderCreatedRun(run) {
  els.createdRun.hidden = false;
  els.createdRun.innerHTML = `
    <span class="status-pill ${statusClass(run.status)}">${escapeHtml(
      titleLabel(run.status)
    )}</span>
    <strong>${escapeHtml(workflowTitle(run.task))}</strong>
    <code title="${escapeHtml(run.id)}">${escapeHtml(shortId(run.id))}</code>
    <a class="run-link" href="${inspectorUrl(run.id)}">Open workflow</a>`;
}

async function loadRuns() {
  state.loadingRuns = true;
  renderRuns();
  try {
    state.runs = await requestJson("/runs");
  } catch (error) {
    els.runCount.textContent = "Error";
    els.runsList.innerHTML = `<p class="error-panel">${escapeHtml(error.message)}</p>`;
  } finally {
    state.loadingRuns = false;
    renderWorkflowSummary();
    renderRuns();
    els.refreshRuns.disabled = false;
  }
}

async function loadSources() {
  try {
    state.dataSources = await requestJson("/data-sources");
  } catch {
    state.dataSources = [];
    els.sourceStatus.textContent = "Sources unavailable";
  }
  renderSources();
}

function buildCreatePayload() {
  const payload = {
    task: els.taskInput.value.trim(),
    metadata: { source: "control-plane-ui" },
  };
  const mode = selectedDatasetMode();
  if (mode === "demo") {
    payload.dataset_uri = "examples/procurement_demo.csv";
    payload.metadata.dataset_origin = "demo";
  }
  if (mode === "source") {
    const dataSourceId = els.dataSourceSelect.value.trim();
    if (!dataSourceId) {
      throw new Error("Select a data source.");
    }
    payload.data_source_id = dataSourceId;
  }
  if (mode === "uri") {
    const datasetUri = els.datasetUriInput.value.trim();
    if (!datasetUri) {
      throw new Error("Enter a dataset URI.");
    }
    payload.dataset_uri = datasetUri;
  }
  return payload;
}

async function handleCreateRun(event) {
  event.preventDefault();
  setFormStatus("", "");

  let payload;
  try {
    payload = buildCreatePayload();
  } catch (error) {
    setFormStatus(error.message, "error");
    return;
  }

  state.creatingRun = true;
  els.createRunButton.disabled = true;
  setFormStatus("Preparing workflow.", "");

  try {
    const run = await requestJson("/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setFormStatus("Running five agent stages.", "");
    await requestJson(`/runs/${encodeURIComponent(run.id)}/execute/procurement`, {
      method: "POST",
    });
    const completedRun = await requestJson(`/runs/${encodeURIComponent(run.id)}`);
    setFormStatus(
      completedRun.status === "completed" ? "Workflow completed." : "Workflow submitted.",
      "success"
    );
    renderCreatedRun(completedRun);
    els.taskInput.value = "";
    els.datasetUriInput.value = "";
    await loadRuns();
  } catch (error) {
    setFormStatus(error.message, "error");
  } finally {
    state.creatingRun = false;
    els.createRunButton.disabled = false;
  }
}

function handleRunFilters() {
  state.searchQuery = els.runSearch.value;
  state.statusFilter = els.runStatusFilter.value;
  renderRuns();
}

function handleRefreshRuns() {
  els.refreshRuns.disabled = true;
  loadRuns();
}

els.createRunForm.addEventListener("change", updateDatasetFields);
els.createRunForm.addEventListener("submit", handleCreateRun);
els.refreshRuns.addEventListener("click", handleRefreshRuns);
els.runSearch.addEventListener("input", handleRunFilters);
els.runStatusFilter.addEventListener("change", handleRunFilters);

updateDatasetFields();
loadSources();
loadRuns();
