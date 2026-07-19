const state = {
  runs: [],
  dataSources: [],
  loadingRuns: false,
  creatingRun: false,
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
    : "No sources";
}

function renderRuns() {
  els.runCount.textContent = state.loadingRuns
    ? "Loading"
    : `${state.runs.length} run${state.runs.length === 1 ? "" : "s"}`;

  if (state.loadingRuns) {
    els.runsList.innerHTML = '<p class="empty">Loading recent runs.</p>';
    return;
  }
  if (!state.runs.length) {
    els.runsList.innerHTML = '<p class="empty">No runs have been created yet.</p>';
    return;
  }

  const runs = [...state.runs].sort(
    (left, right) => new Date(right.updated_at) - new Date(left.updated_at)
  );
  els.runsList.innerHTML = runs.map(renderRunItem).join("");
}

function renderRunItem(run) {
  return `
    <article class="run-item">
      <div class="run-main">
        <a class="run-link" href="${inspectorUrl(run.id)}">${escapeHtml(run.id)}</a>
        <span class="${statusClass(run.status)}">${escapeHtml(titleLabel(run.status))}</span>
      </div>
      <p class="run-task">${escapeHtml(run.task)}</p>
      <div class="meta-line">
        <span>updated ${escapeHtml(formatDate(run.updated_at))}</span>
        <span>created ${escapeHtml(formatDate(run.created_at))}</span>
        ${
          run.dataset_artifact_id
            ? `<span>dataset ${escapeHtml(run.dataset_artifact_id)}</span>`
            : ""
        }
      </div>
    </article>`;
}

function renderCreatedRun(run) {
  els.createdRun.hidden = false;
  els.createdRun.innerHTML = `
    <strong>${escapeHtml(run.id)}</strong>
    <p class="run-task">${escapeHtml(run.task)}</p>
    <a class="run-link" href="${inspectorUrl(run.id)}">Open Run Inspector</a>`;
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
  setFormStatus("Creating run.", "");

  try {
    const run = await requestJson("/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setFormStatus("Run created.", "success");
    renderCreatedRun(run);
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

function handleRefreshRuns() {
  els.refreshRuns.disabled = true;
  loadRuns();
}

els.createRunForm.addEventListener("change", updateDatasetFields);
els.createRunForm.addEventListener("submit", handleCreateRun);
els.refreshRuns.addEventListener("click", handleRefreshRuns);

updateDatasetFields();
loadSources();
loadRuns();
