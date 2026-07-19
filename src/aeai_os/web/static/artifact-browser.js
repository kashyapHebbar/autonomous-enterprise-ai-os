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
};

const els = {
  runSelect: document.querySelector("#runSelect"),
  refreshArtifacts: document.querySelector("#refreshArtifacts"),
  artifactCount: document.querySelector("#artifactCount"),
  artifactGroups: document.querySelector("#artifactGroups"),
  previewTitle: document.querySelector("#previewTitle"),
  previewType: document.querySelector("#previewType"),
  previewActions: document.querySelector("#previewActions"),
  previewSurface: document.querySelector("#previewSurface"),
  lineageView: document.querySelector("#lineageView"),
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

function renderRunSelect() {
  els.runSelect.innerHTML = state.runs.length
    ? state.runs
        .map(
          (run) => `
            <option value="${escapeHtml(run.id)}"${run.id === state.selectedRunId ? " selected" : ""}>
              ${escapeHtml(run.id)} - ${escapeHtml(titleLabel(run.status))}
            </option>`
        )
        .join("")
    : '<option value="">No runs</option>';
}

function renderArtifactGroups() {
  const artifacts = state.selectedRun ? state.selectedRun.artifacts : [];
  els.artifactCount.textContent = `${artifacts.length} artifact${artifacts.length === 1 ? "" : "s"}`;

  if (!state.selectedRun) {
    els.artifactGroups.innerHTML = '<p class="empty">No run selected.</p>';
    return;
  }
  if (!artifacts.length) {
    els.artifactGroups.innerHTML = '<p class="empty">This run has no artifacts yet.</p>';
    return;
  }

  const groups = groupedArtifacts(artifacts);
  els.artifactGroups.innerHTML = Object.entries(groups)
    .map(
      ([producer, groupArtifacts]) => `
        <section class="artifact-group">
          <h3>${escapeHtml(titleLabel(producer))}</h3>
          <div class="artifact-list">
            ${groupArtifacts.map(renderArtifactButton).join("")}
          </div>
        </section>`
    )
    .join("");
}

function renderArtifactButton(artifact) {
  const selected = state.selectedArtifact && state.selectedArtifact.id === artifact.id;
  const previewLabel = PREVIEWABLE_TYPES.has(artifact.type) ? "previewable" : "unavailable";
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
      <span class="artifact-id">${escapeHtml(artifact.id)}</span>
      <span class="meta-line">
        <span>${escapeHtml(previewLabel)}</span>
        <span>${escapeHtml(titleLabel(artifact.producer_node_id || "input"))}</span>
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

  els.previewActions.innerHTML = `
    <a class="link-button" href="${inspectorPath(artifact.run_id)}">Run Inspector</a>
    ${
      canPreview
        ? `<a class="link-button" href="${artifactContentPath(artifact, true)}">Download</a>
           <button class="artifact-button" type="button" data-copy-url="${escapeHtml(absoluteUrl)}">
             Copy Link
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

async function renderTextPreview(artifact) {
  try {
    const text = await requestText(artifactContentPath(artifact));
    if (artifact.type === "report") {
      els.previewSurface.innerHTML = `<article class="markdown-preview">${renderMarkdown(text)}</article>`;
      return;
    }
    els.previewSurface.innerHTML = `<pre class="json-preview">${escapeHtml(formatTextPayload(text))}</pre>`;
  } catch (error) {
    els.previewSurface.innerHTML = `<p class="error-panel">${escapeHtml(error.message)}</p>`;
  }
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
              <article class="lineage-item">
                <strong>${escapeHtml(item.metadata.title || item.id)}</strong>
                <div class="meta-line">
                  <span>${escapeHtml(titleLabel(item.type))}</span>
                  <span>${escapeHtml(titleLabel(item.producer_node_id || "input"))}</span>
                  <span>${escapeHtml(item.id)}</span>
                </div>
              </article>`
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
    state.runs = await requestJson("/runs");
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
els.previewActions.addEventListener("click", handleCopyLink);
els.runSelect.addEventListener("change", handleRunChange);
els.refreshArtifacts.addEventListener("click", loadRuns);

loadRuns();
