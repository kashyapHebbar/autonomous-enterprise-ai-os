const PREVIEWABLE_TYPES = new Set([
  "schema_profile",
  "quality_report",
  "kpi_table",
  "chart",
  "dashboard",
  "report",
  "code",
  "evaluation",
  "deployment",
]);

const state = {
  runs: [],
  selectedRunId: new URLSearchParams(window.location.search).get("run_id") || "",
  selectedArtifactId: new URLSearchParams(window.location.search).get("artifact_id") || "",
  selectedRun: null,
  selectedArtifact: null,
  connectors: [],
  searchQuery: "",
  typeFilter: "all",
};

const els = {
  runSelect: document.querySelector("#runSelect"),
  refreshArtifacts: document.querySelector("#refreshArtifacts"),
  artifactCount: document.querySelector("#artifactCount"),
  artifactGroups: document.querySelector("#artifactGroups"),
  artifactSearch: document.querySelector("#artifactSearch"),
  artifactTypeFilter: document.querySelector("#artifactTypeFilter"),
  previewTitle: document.querySelector("#previewTitle"),
  previewType: document.querySelector("#previewType"),
  previewActions: document.querySelector("#previewActions"),
  previewSurface: document.querySelector("#previewSurface"),
  selectedArtifactMeta: document.querySelector("#selectedArtifactMeta"),
  lineageView: document.querySelector("#lineageView"),
  runSummary: document.querySelector("#runSummary"),
  runtimeSource: document.querySelector("#runtimeSource"),
  runtimeSourceDetail: document.querySelector("#runtimeSourceDetail"),
  runtimeStorage: document.querySelector("#runtimeStorage"),
  runtimeStorageDetail: document.querySelector("#runtimeStorageDetail"),
  runtimeSnowflake: document.querySelector("#runtimeSnowflake"),
  runtimeSnowflakeDetail: document.querySelector("#runtimeSnowflakeDetail"),
  runtimeCloud: document.querySelector("#runtimeCloud"),
  runtimeCloudDetail: document.querySelector("#runtimeCloudDetail"),
};

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(formatErrorDetail(body.detail) || `Request failed: ${response.status}`);
  }
  return response.json();
}

async function requestText(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(formatErrorDetail(body.detail) || `Request failed: ${response.status}`);
  }
  return response.text();
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

function artifactContentPath(artifact, download = false) {
  const runId = encodeURIComponent(artifact.run_id);
  const artifactId = encodeURIComponent(artifact.id);
  return `/runs/${runId}/artifacts/${artifactId}/content${download ? "?download=true" : ""}`;
}

function inspectorPath(runId) {
  return `/run-inspector/runs/${encodeURIComponent(runId)}`;
}

function statusClass(value) {
  return `status-pill status-${String(value || "")
    .toLowerCase()
    .replaceAll("_", "-")
    .replaceAll(" ", "-")}`;
}

function artifactTitle(artifact) {
  return artifact.metadata.title || artifact.metadata.filename || titleLabel(artifact.type);
}

function groupedArtifacts(artifacts) {
  return artifacts.reduce((groups, artifact) => {
    const group = artifact.producer_node_id || "input";
    groups[group] = groups[group] || [];
    groups[group].push(artifact);
    return groups;
  }, {});
}

function shortId(value) {
  const text = String(value || "");
  return text.length > 14 ? `${text.slice(0, 9)}...${text.slice(-5)}` : text;
}

function workflowTitle(task) {
  const text = String(task || "Untitled workflow").trim().replace(/[.]+$/, "");
  return text.length > 58 ? `${text.slice(0, 55).trimEnd()}...` : text;
}

function filteredArtifacts() {
  const artifacts = state.selectedRun?.artifacts || [];
  const query = state.searchQuery.trim().toLowerCase();
  return artifacts.filter((artifact) => {
    const matchesType = state.typeFilter === "all" || artifact.type === state.typeFilter;
    const haystack = [
      artifactTitle(artifact),
      artifact.type,
      artifact.producer_node_id,
      artifact.id,
    ]
      .join(" ")
      .toLowerCase();
    return matchesType && (!query || haystack.includes(query));
  });
}

function renderTypeFilter() {
  const types = [...new Set((state.selectedRun?.artifacts || []).map((artifact) => artifact.type))]
    .sort();
  els.artifactTypeFilter.innerHTML = [
    '<option value="all">All types</option>',
    ...types.map(
      (type) => `<option value="${escapeHtml(type)}"${
        state.typeFilter === type ? " selected" : ""
      }>${escapeHtml(titleLabel(type))}</option>`
    ),
  ].join("");
}

function renderRunSelect() {
  els.runSelect.innerHTML = state.runs.length
    ? state.runs
        .map(
          (run) => `
            <option value="${escapeHtml(run.id)}"${run.id === state.selectedRunId ? " selected" : ""}>
              ${escapeHtml(workflowTitle(run.task))} - ${escapeHtml(shortId(run.id))}
            </option>`
        )
        .join("")
    : '<option value="">No runs</option>';
}

function renderArtifactGroups() {
  const allArtifacts = state.selectedRun ? state.selectedRun.artifacts : [];
  const artifacts = filteredArtifacts();
  els.artifactCount.textContent = state.searchQuery || state.typeFilter !== "all"
    ? `${artifacts.length} of ${allArtifacts.length}`
    : `${allArtifacts.length} output${allArtifacts.length === 1 ? "" : "s"}`;

  if (!state.selectedRun) {
    els.artifactGroups.innerHTML = '<p class="empty">No run selected.</p>';
    return;
  }
  if (!artifacts.length) {
    els.artifactGroups.innerHTML = '<p class="empty">No outputs match the current filters.</p>';
    return;
  }

  const groups = groupedArtifacts(artifacts);
  els.artifactGroups.innerHTML = Object.entries(groups)
    .map(
      ([producer, groupArtifacts]) => `
        <section class="artifact-group">
          <h3><span>${escapeHtml(titleLabel(producer))}</span><small>${groupArtifacts.length}</small></h3>
          <div class="artifact-list">
            ${groupArtifacts.map(renderArtifactButton).join("")}
          </div>
        </section>`
    )
    .join("");
}

function renderArtifactButton(artifact) {
  const selected = state.selectedArtifact && state.selectedArtifact.id === artifact.id;
  const previewLabel = PREVIEWABLE_TYPES.has(artifact.type) ? "Ready" : "Metadata only";
  return `
    <button
      class="artifact-item"
      type="button"
      data-artifact-id="${escapeHtml(artifact.id)}"
      aria-selected="${selected ? "true" : "false"}"
    >
      <span class="artifact-main">
        <strong>${escapeHtml(artifactTitle(artifact))}</strong>
        <span class="${statusClass(artifact.type)}">${escapeHtml(titleLabel(artifact.type))}</span>
      </span>
      <span class="meta-line">
        <span>${escapeHtml(previewLabel)}</span>
        <span title="${escapeHtml(artifact.id)}">${escapeHtml(shortId(artifact.id))}</span>
        <span>${escapeHtml(formatDate(artifact.created_at))}</span>
      </span>
    </button>`;
}

function renderPreviewShell(artifact) {
  state.selectedArtifact = artifact;
  els.previewTitle.textContent = artifactTitle(artifact);
  els.previewType.textContent = titleLabel(artifact.type);
  els.previewType.className = statusClass(artifact.type);
  const canPreview = PREVIEWABLE_TYPES.has(artifact.type);
  const contentUrl = artifactContentPath(artifact);
  const absoluteUrl = new URL(contentUrl, window.location.origin).toString();
  renderSelectedMeta(artifact);
  renderRuntimeContext();

  els.previewActions.innerHTML = `
    <a class="link-button" href="${inspectorPath(artifact.run_id)}">View workflow</a>
    ${
      canPreview
        ? `<a class="link-button" href="${artifactContentPath(artifact, true)}">Download</a>
           <button class="artifact-button" type="button" data-copy-url="${escapeHtml(absoluteUrl)}">
             Copy link
           </button>`
        : ""
    }`;

  if (!canPreview) {
    els.previewSurface.innerHTML = `
      <p class="unavailable-preview">Artifact type ${escapeHtml(titleLabel(artifact.type))} is not available for browser preview.</p>`;
    return;
  }

  if (artifact.type === "dashboard" || artifact.type === "chart") {
    els.previewSurface.innerHTML = `
      <iframe
        class="preview-frame"
        src="${contentUrl}"
        sandbox=""
        title="${escapeHtml(artifactTitle(artifact))}"
      ></iframe>`;
    return;
  }

  els.previewSurface.innerHTML = '<p class="empty">Loading preview.</p>';
  renderTextPreview(artifact);
}

function renderSelectedMeta(artifact) {
  const storage = artifact.metadata?.storage_backend || "local";
  const size = artifact.metadata?.size_bytes;
  els.selectedArtifactMeta.innerHTML = `
    <div><span>Created by</span><strong>${escapeHtml(
      titleLabel(artifact.producer_node_id || "input")
    )}</strong></div>
    <div><span>Stored in</span><strong>${escapeHtml(titleLabel(storage))}</strong></div>
    <div><span>Format</span><strong>${escapeHtml(
      titleLabel(artifact.metadata?.format || artifact.type)
    )}</strong></div>
    <div><span>Size</span><strong>${escapeHtml(formatBytes(size))}</strong></div>`;
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "Not recorded";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function datasetArtifact() {
  return state.selectedRun?.artifacts.find((artifact) => artifact.type === "dataset") || null;
}

function connectorById(id) {
  return state.connectors.find((connector) => connector.id === id) || null;
}

function setRuntimeStatus(element, detailElement, value, detail, active) {
  element.textContent = value;
  element.className = active ? "runtime-active" : "runtime-inactive";
  detailElement.textContent = detail;
}

function renderRuntimeContext() {
  const dataset = datasetArtifact();
  const sourceConnector = dataset?.metadata?.connector_id || "local-file";
  const sourceIsRemote = /^https:\/\//i.test(dataset?.uri || "");
  const sourceIsLocal =
    !sourceIsRemote && (sourceConnector === "local-file" || dataset?.uri?.startsWith("/"));
  const storage =
    state.selectedArtifact?.metadata?.storage_backend ||
    connectorById("artifact-store")?.metadata?.backend ||
    "local";
  const storageIsCloud = ["s3", "object", "object_storage"].includes(
    String(storage).toLowerCase()
  );
  const snowflake = connectorById("snowflake-default");

  setRuntimeStatus(
    els.runtimeSource,
    els.runtimeSourceDetail,
    sourceIsRemote ? "Public URL" : sourceIsLocal ? "Local file" : titleLabel(sourceConnector),
    sourceIsRemote
      ? "HTTPS CSV dataset"
      : sourceIsLocal
        ? "CSV on this Mac"
        : "Warehouse-backed dataset",
    true
  );
  setRuntimeStatus(
    els.runtimeStorage,
    els.runtimeStorageDetail,
    titleLabel(storage),
    storageIsCloud ? "S3-compatible object storage" : "Filesystem artifacts",
    true
  );
  setRuntimeStatus(
    els.runtimeSnowflake,
    els.runtimeSnowflakeDetail,
    snowflake?.status === "ok" ? "Configured" : "Not configured",
    snowflake?.status === "ok" ? "Available for warehouse runs" : "Credentials are missing",
    snowflake?.status === "ok"
  );
  setRuntimeStatus(
    els.runtimeCloud,
    els.runtimeCloudDetail,
    storageIsCloud ? "S3 active" : "Not active",
    storageIsCloud ? "Artifacts use AWS-compatible storage" : "This run stays local",
    storageIsCloud
  );
}

async function renderTextPreview(artifact) {
  try {
    const text = await requestText(artifactContentPath(artifact));
    if (artifact.type === "report") {
      els.previewSurface.innerHTML = `<article class="markdown-preview">${renderMarkdown(text)}</article>`;
      return;
    }
    if (["schema_profile", "quality_report", "kpi_table", "evaluation", "deployment"].includes(artifact.type)) {
      els.previewSurface.innerHTML = renderStructuredPreview(text);
      return;
    }
    els.previewSurface.innerHTML = `<pre class="json-preview">${escapeHtml(formatTextPayload(text))}</pre>`;
  } catch (error) {
    els.previewSurface.innerHTML = `<p class="error-panel">${escapeHtml(error.message)}</p>`;
  }
}

function renderStructuredPreview(text) {
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    return `<pre class="json-preview">${escapeHtml(text)}</pre>`;
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return `<pre class="json-preview">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
  }
  return `<div class="structured-preview">${Object.entries(payload)
    .map(([key, value]) => renderStructuredField(key, value))
    .join("")}</div>`;
}

function renderStructuredField(key, value) {
  const heading = escapeHtml(titleLabel(key));
  if (Array.isArray(value) && value.length === 0) {
    return `<article class="data-point"><span>${heading}</span><strong>None</strong></article>`;
  }
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) {
    return `<article class="data-point"><span>${heading}</span><strong>${escapeHtml(
      formatDisplayValue(key, value)
    )}</strong></article>`;
  }
  if (Array.isArray(value) && value.every((item) => ["string", "number"].includes(typeof item))) {
    return `<article class="data-section"><h3>${heading}</h3><div class="value-chips">${value
      .map((item) => `<span>${escapeHtml(item)}</span>`)
      .join("")}</div></article>`;
  }
  return `<details class="data-section"><summary>${heading}</summary><pre>${escapeHtml(
    JSON.stringify(value, null, 2)
  )}</pre></details>`;
}

function formatDisplayValue(key, value) {
  if (value === null) {
    return "None";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "number" && key.toLowerCase().includes("spend")) {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(value);
  }
  return String(value);
}

function renderMarkdown(markdown) {
  const blocks = [];
  let listItems = [];
  function flushList() {
    if (listItems.length) {
      blocks.push(`<ul>${listItems.map((item) => `<li>${item}</li>`).join("")}</ul>`);
      listItems = [];
    }
  }
  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }
    if (line.startsWith("- ")) {
      listItems.push(escapeHtml(line.slice(2)));
      continue;
    }
    flushList();
    if (line.startsWith("### ")) {
      blocks.push(`<h3>${escapeHtml(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      blocks.push(`<h2>${escapeHtml(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      blocks.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
    } else {
      blocks.push(`<p>${escapeHtml(line)}</p>`);
    }
  }
  flushList();
  return blocks.join("");
}

function formatTextPayload(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

async function renderLineage(artifact) {
  els.lineageView.innerHTML = '<p class="empty">Loading lineage.</p>';
  try {
    const lineage = await requestJson(
      `/runs/${encodeURIComponent(artifact.run_id)}/artifacts/${encodeURIComponent(artifact.id)}/lineage`
    );
    const upstream = lineage.upstream_artifacts || [];
    if (!upstream.length) {
      els.lineageView.innerHTML = '<p class="empty">No upstream artifacts recorded.</p>';
      return;
    }
    els.lineageView.innerHTML = `
      <div class="lineage-list">
        ${upstream
          .map(
            (item) => `
              <button class="lineage-item" type="button" data-lineage-artifact-id="${escapeHtml(
                item.id
              )}">
                <strong>${escapeHtml(item.metadata.title || item.id)}</strong>
                <div class="meta-line">
                  <span>${escapeHtml(titleLabel(item.type))}</span>
                  <span>${escapeHtml(titleLabel(item.producer_node_id || "input"))}</span>
                  <span>${escapeHtml(shortId(item.id))}</span>
                </div>
              </button>`
          )
          .join("")}
      </div>`;
  } catch (error) {
    els.lineageView.innerHTML = `<p class="error-panel">${escapeHtml(error.message)}</p>`;
  }
}

function selectArtifact(artifactId) {
  if (!state.selectedRun) {
    return;
  }
  const artifact = state.selectedRun.artifacts.find((item) => item.id === artifactId);
  if (!artifact) {
    return;
  }
  state.selectedArtifactId = artifact.id;
  renderPreviewShell(artifact);
  renderLineage(artifact);
  renderArtifactGroups();
  window.history.replaceState(
    null,
    "",
    `/app/artifacts?run_id=${encodeURIComponent(artifact.run_id)}&artifact_id=${encodeURIComponent(artifact.id)}`
  );
}

async function selectRun(runId) {
  state.selectedRunId = runId;
  state.selectedArtifact = null;
  state.selectedRun = null;
  els.artifactGroups.innerHTML = '<p class="empty">Loading artifacts.</p>';
  els.previewSurface.innerHTML = '<p class="empty">Select an artifact to inspect it.</p>';
  els.lineageView.innerHTML = "";

  if (!runId) {
    renderArtifactGroups();
    return;
  }

  state.selectedRun = await requestJson(`/runs/${encodeURIComponent(runId)}`);
  els.runSummary.textContent = state.selectedRun.task;
  renderTypeFilter();
  renderRuntimeContext();
  renderArtifactGroups();
  const initialArtifact =
    state.selectedRun.artifacts.find((artifact) => artifact.id === state.selectedArtifactId) ||
    state.selectedRun.artifacts.find((artifact) => PREVIEWABLE_TYPES.has(artifact.type)) ||
    state.selectedRun.artifacts[0];
  if (initialArtifact) {
    selectArtifact(initialArtifact.id);
  }
}

async function loadRuns() {
  els.refreshArtifacts.disabled = true;
  els.artifactCount.textContent = "Loading";
  els.artifactGroups.innerHTML = '<p class="empty">Loading runs.</p>';
  try {
    [state.runs, state.connectors] = await Promise.all([
      requestJson("/runs"),
      requestJson("/connectors").catch(() => []),
    ]);
    state.runs.sort((left, right) => new Date(right.updated_at) - new Date(left.updated_at));
    if (!state.selectedRunId && state.runs.length) {
      state.selectedRunId = state.runs[0].id;
    }
    renderRunSelect();
    await selectRun(state.selectedRunId);
  } catch (error) {
    els.artifactCount.textContent = "Error";
    els.artifactGroups.innerHTML = `<p class="error-panel">${escapeHtml(error.message)}</p>`;
  } finally {
    els.refreshArtifacts.disabled = false;
  }
}

function handleArtifactClick(event) {
  const button = event.target.closest("[data-artifact-id]");
  if (!button) {
    return;
  }
  selectArtifact(button.dataset.artifactId);
}

function handleLineageClick(event) {
  const button = event.target.closest("[data-lineage-artifact-id]");
  if (button) {
    selectArtifact(button.dataset.lineageArtifactId);
  }
}

function handleLibraryFilter() {
  state.searchQuery = els.artifactSearch.value;
  state.typeFilter = els.artifactTypeFilter.value;
  renderArtifactGroups();
}

async function handleRunChange() {
  state.selectedArtifactId = "";
  await selectRun(els.runSelect.value);
}

async function handleCopyLink(event) {
  const button = event.target.closest("[data-copy-url]");
  if (!button) {
    return;
  }
  try {
    await navigator.clipboard.writeText(button.dataset.copyUrl);
    button.textContent = "Copied";
  } catch {
    button.textContent = "Copy failed";
  }
}

els.artifactGroups.addEventListener("click", handleArtifactClick);
els.lineageView.addEventListener("click", handleLineageClick);
els.previewActions.addEventListener("click", handleCopyLink);
els.artifactSearch.addEventListener("input", handleLibraryFilter);
els.artifactTypeFilter.addEventListener("change", handleLibraryFilter);
els.runSelect.addEventListener("change", handleRunChange);
els.refreshArtifacts.addEventListener("click", loadRuns);

loadRuns();
