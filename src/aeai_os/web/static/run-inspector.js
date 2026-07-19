const state = {
  runId: runIdFromLocation(),
  data: null,
  pendingAction: null,
  selectedNodeId: null,
};

const els = {
  runTitle: document.querySelector("#runTitle"),
  runStatus: document.querySelector("#runStatus"),
  traceId: document.querySelector("#traceId"),
  datasetId: document.querySelector("#datasetId"),
  updatedAt: document.querySelector("#updatedAt"),
  artifactCount: document.querySelector("#artifactCount"),
  taskText: document.querySelector("#taskText"),
  actionText: document.querySelector("#actionText"),
  errorText: document.querySelector("#errorText"),
  flowSteps: document.querySelector("#flowSteps"),
  flowDetail: document.querySelector("#flowDetail"),
  flowSummary: document.querySelector("#flowSummary"),
  graphNodes: document.querySelector("#graphNodes"),
  workflowJobs: document.querySelector("#workflowJobs"),
  timeline: document.querySelector("#timeline"),
  artifacts: document.querySelector("#artifacts"),
  approvalHistory: document.querySelector("#approvalHistory"),
  evaluations: document.querySelector("#evaluations"),
  deploymentHistory: document.querySelector("#deploymentHistory"),
  events: document.querySelector("#events"),
};

function runIdFromLocation() {
  const match = window.location.pathname.match(/\/run-inspector\/runs\/([^/]+)\/?$/);
  if (match) {
    return decodeURIComponent(match[1]);
  }
  return new URLSearchParams(window.location.search).get("run_id") || "";
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function fetchJson(path) {
  return requestJson(path);
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

function shortId(value) {
  const text = String(value || "");
  return text.length > 16 ? `${text.slice(0, 8)}...${text.slice(-5)}` : text;
}

function workflowTitle(task) {
  const text = String(task || "Workflow").trim().replace(/[.]+$/, "");
  return text.length > 76 ? `${text.slice(0, 73).trimEnd()}...` : text;
}

function datasetDisplayName(run) {
  const artifact = run.artifacts.find((item) => item.id === run.dataset_artifact_id);
  if (!artifact) {
    return "No dataset";
  }
  const uri = String(artifact.uri || "");
  return artifact.metadata?.title || artifact.metadata?.filename || uri.split("/").pop() || "Dataset";
}

function pillClass(status) {
  return `mini-pill status-${String(status || "")
    .toLowerCase()
    .replaceAll("_", "-")
    .replaceAll(" ", "-")}`;
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

function renderKeyValues(value, emptyLabel = "No metadata recorded.") {
  const entries = Object.entries(value || {}).filter(([, item]) => item !== null && item !== "");
  if (!entries.length) {
    return `<p class="detail-empty">${escapeHtml(emptyLabel)}</p>`;
  }
  return `<dl class="detail-grid">${entries
    .map(
      ([key, item]) => `
        <div>
          <dt>${escapeHtml(key)}</dt>
          <dd>${escapeHtml(formatDetailValue(item))}</dd>
        </div>`
    )
    .join("")}</dl>`;
}

function renderIdChips(ids, emptyLabel = "none", linkArtifacts = false) {
  if (!ids || !ids.length) {
    return `<span>${escapeHtml(emptyLabel)}</span>`;
  }
  return `<span class="chip-row">${ids
    .map((id) =>
      linkArtifacts
        ? `<a class="id-chip" href="${artifactBrowserPath(id)}" title="Open ${escapeHtml(
            titleLabel(artifactById(id)?.type || "artifact")
          )}">${escapeHtml(artifactDisplayName(id))}</a>`
        : `<code class="id-chip">${escapeHtml(id)}</code>`
    )
    .join("")}</span>`;
}

function artifactById(artifactId) {
  return state.data?.run.artifacts.find((artifact) => artifact.id === artifactId) || null;
}

function artifactDisplayName(artifactId) {
  const artifact = artifactById(artifactId);
  return artifact ? artifactTitle(artifact) : artifactId;
}

function artifactTitle(artifact) {
  return artifact.metadata?.title || artifact.metadata?.filename || titleLabel(artifact.type);
}

function artifactBrowserPath(artifactId) {
  return `/app/artifacts?run_id=${encodeURIComponent(state.runId)}&artifact_id=${encodeURIComponent(
    artifactId
  )}`;
}

function formatDetailValue(value) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value);
  }
  return value;
}

function artifactLineage(artifactId) {
  return state.data.lineageByArtifactId[artifactId] || null;
}

function artifactElementId(artifactId) {
  return `artifact-${String(artifactId).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function approvalEvents() {
  return state.data.events.filter((event) =>
    ["approval_request", "approval_decision", "tool_call"].includes(event.event_type)
  );
}

function evaluationEventById(evaluationId) {
  return state.data.events.find(
    (event) =>
      event.event_type === "evaluation" && event.payload.evaluation_id === evaluationId
  );
}

function deploymentJobs() {
  return state.data.jobs.filter((job) => job.workflow_name === "deployment");
}

function deploymentArtifacts() {
  return state.data.run.artifacts.filter((artifact) => artifact.type === "deployment");
}

function setActionStatus(message, kind = "idle") {
  els.actionText.textContent = message;
  els.actionText.className = `action-text action-${kind}`;
}

function renderRun() {
  const { run } = state.data;
  document.title = `${workflowTitle(run.task)} | Workflow`;
  els.runTitle.textContent = workflowTitle(run.task);
  els.runStatus.textContent = titleLabel(run.status);
  els.runStatus.className = `status-pill status-${run.status}`;
  els.traceId.textContent = shortId(run.id);
  els.traceId.title = run.id;
  els.datasetId.textContent = datasetDisplayName(run);
  els.datasetId.title = run.dataset_artifact_id || "";
  els.updatedAt.textContent = formatDate(run.updated_at);
  els.artifactCount.textContent = String(run.artifacts.length);
  els.taskText.textContent = run.task;
  els.errorText.textContent = run.error_summary || "";
  const passedEvaluations = run.evaluations.filter((evaluation) => evaluation.passed).length;
  els.flowSummary.textContent = `${state.data.graphNodes.length} agent stages · ${
    run.artifacts.length
  } outputs · ${passedEvaluations} quality gate${passedEvaluations === 1 ? "" : "s"} passed`;
}

function renderNodeActions(node) {
  const escapedNodeId = escapeHtml(node.id);
  const pending =
    state.pendingAction !== null && state.pendingAction.nodeId === node.id
      ? state.pendingAction.action
      : null;
  const disabled = pending ? " disabled" : "";

  if (node.status === "waiting_for_approval") {
    return `
      <div class="node-actions" aria-label="Node actions for ${escapedNodeId}">
        <button
          class="node-action action-approve"
          data-node-action="approve"
          data-node-id="${escapedNodeId}"
          type="button"${disabled}
        >${pending === "approve" ? "Approving" : "Approve"}</button>
        <button
          class="node-action action-deny"
          data-node-action="deny"
          data-node-id="${escapedNodeId}"
          type="button"${disabled}
        >${pending === "deny" ? "Denying" : "Deny"}</button>
      </div>`;
  }

  if (node.status === "failed") {
    return `
      <div class="node-actions" aria-label="Node actions for ${escapedNodeId}">
        <button
          class="node-action action-retry"
          data-node-action="retry"
          data-node-id="${escapedNodeId}"
          type="button"${disabled}
        >${pending === "retry" ? "Retrying" : "Retry"}</button>
      </div>`;
  }

  return "";
}

function renderDeploymentJobActions(job) {
  if (job.workflow_name !== "deployment" || job.status !== "waiting_for_approval") {
    return "";
  }

  const escapedJobId = escapeHtml(job.id);
  const pending =
    state.pendingAction !== null && state.pendingAction.jobId === job.id
      ? state.pendingAction.action
      : null;
  const disabled = pending ? " disabled" : "";

  return `
    <div class="node-actions" aria-label="Deployment actions for ${escapedJobId}">
      <button
        class="node-action action-approve"
        data-deployment-action="approve"
        data-job-id="${escapedJobId}"
        type="button"${disabled}
      >${pending === "approve" ? "Approving" : "Approve"}</button>
      <button
        class="node-action action-deny"
        data-deployment-action="deny"
        data-job-id="${escapedJobId}"
        type="button"${disabled}
      >${pending === "deny" ? "Denying" : "Deny"}</button>
    </div>`;
}

function renderDeadLetterJobActions(job) {
  if (job.status !== "dead_letter") {
    return "";
  }

  const escapedJobId = escapeHtml(job.id);
  const pending =
    state.pendingAction !== null && state.pendingAction.jobId === job.id
      ? state.pendingAction.action
      : null;
  const disabled = pending ? " disabled" : "";

  return `
    <div class="node-actions" aria-label="Dead-letter actions for ${escapedJobId}">
      <button
        class="node-action action-retry"
        data-job-action="retry"
        data-job-id="${escapedJobId}"
        type="button"${disabled}
      >${pending === "retry" ? "Retrying" : "Retry job"}</button>
      <button
        class="node-action action-deny"
        data-job-action="dismiss"
        data-job-id="${escapedJobId}"
        type="button"${disabled}
      >${pending === "dismiss" ? "Dismissing" : "Dismiss"}</button>
    </div>`;
}

function renderNodes() {
  const nodes = state.data.graphNodes;
  els.graphNodes.innerHTML = nodes.length
    ? nodes
        .map(
          (node) => `
            <article class="node-item${
              node.id === state.selectedNodeId ? " is-selected" : ""
            }" data-flow-node-id="${escapeHtml(node.id)}">
              <div class="node-main">
                <strong>${escapeHtml(titleLabel(node.id))}</strong>
                <span class="${pillClass(node.status)}">${escapeHtml(titleLabel(node.status))}</span>
              </div>
              ${renderMeta([
                titleLabel(node.agent_type),
                `retries ${node.retry_count}`,
                `updated ${formatDate(node.updated_at)}`,
              ])}
              ${renderMeta([
                `depends: ${node.depends_on.map(titleLabel).join(", ") || "none"}`,
                `tools: ${node.required_tools.map(titleLabel).join(", ") || "none"}`,
              ])}
              ${renderMeta([`expects: ${node.expected_artifacts.map(titleLabel).join(", ") || "none"}`])}
              ${renderNodeActions(node)}
            </article>`
        )
        .join("")
    : renderEmpty("No graph nodes recorded.");
}

const nodeDescriptions = {
  data_profile: {
    purpose: "Read the dataset and check whether it is trustworthy enough to analyze.",
    activity: "Inspected the columns, data types, missing values, and duplicate rows.",
  },
  analytics: {
    purpose: "Turn the procurement records into business metrics and findings.",
    activity: "Calculated spend totals, supplier concentration, category trends, anomalies, and savings opportunities.",
  },
  visualization: {
    purpose: "Translate the analysis into charts that an executive can scan quickly.",
    activity: "Built KPI, supplier, category, monthly trend, anomaly, and dashboard views.",
  },
  report: {
    purpose: "Create a concise decision-ready summary of the analysis.",
    activity: "Combined the findings, charts, assumptions, and recommendations into a report.",
  },
  evaluation: {
    purpose: "Verify that the requested work is complete and internally consistent.",
    activity: "Checked artifact completeness, task completion, data consistency, and assumption disclosure.",
  },
};

function artifactsForNode(nodeId) {
  return state.data.run.artifacts.filter((artifact) => artifact.producer_node_id === nodeId);
}

function nodeCompletionSummary(nodeId) {
  const event = state.data.events.find(
    (item) =>
      item.node_id === nodeId &&
      item.event_type === "log" &&
      item.payload.message === "Node execution completed."
  );
  return event?.payload?.summary || "This step completed successfully.";
}

function renderFlowDetail() {
  const node =
    state.data.graphNodes.find((item) => item.id === state.selectedNodeId) ||
    state.data.graphNodes[0];
  if (!node) {
    els.flowDetail.innerHTML = renderEmpty("No workflow steps were recorded.");
    return;
  }

  state.selectedNodeId = node.id;
  const copy = nodeDescriptions[node.id] || {
    purpose: `Complete the ${titleLabel(node.id)} stage of the workflow.`,
    activity: `Used ${node.required_tools.map(titleLabel).join(", ") || "the configured tools"}.`,
  };
  const inputs = node.depends_on.flatMap((dependencyId) => artifactsForNode(dependencyId));
  const outputs = artifactsForNode(node.id);

  els.flowDetail.innerHTML = `
    <div class="flow-detail-copy">
      <div class="flow-detail-title">
        <span class="flow-step-number">${state.data.graphNodes.indexOf(node) + 1}</span>
        <div>
          <p class="eyebrow">${escapeHtml(titleLabel(node.agent_type))} agent</p>
          <h3>${escapeHtml(titleLabel(node.id))}</h3>
        </div>
        <span class="${pillClass(node.status)}">${escapeHtml(titleLabel(node.status))}</span>
      </div>
      <p class="flow-purpose">${escapeHtml(copy.purpose)}</p>
      <p>${escapeHtml(copy.activity)}</p>
      <div class="flow-result">
        <span>Result</span>
        <strong>${escapeHtml(nodeCompletionSummary(node.id))}</strong>
      </div>
    </div>
    <div class="flow-io">
      <div>
        <span class="flow-io-label">Received</span>
        <p>${
          inputs.length
            ? [...new Set(inputs.map((artifact) => artifactTitle(artifact)))]
                .map(escapeHtml)
                .join(", ")
            : node.depends_on.length
              ? node.depends_on.map(titleLabel).join(", ")
              : "Uploaded dataset"
        }</p>
      </div>
      <div>
        <span class="flow-io-label">Produced</span>
        <div class="output-actions">
          ${
            outputs.length
              ? outputs
                  .map(
                    (artifact) => `<a class="output-link" href="${artifactBrowserPath(artifact.id)}">
                      <span>${escapeHtml(artifactTitle(artifact))}</span>
                      <small>View output</small>
                    </a>`
                  )
                  .join("")
              : `<span class="detail-empty">No artifact output recorded.</span>`
          }
        </div>
      </div>
    </div>`;
}

function renderFlowStory() {
  const nodes = state.data.graphNodes;
  if (!nodes.length) {
    els.flowSteps.innerHTML = renderEmpty("No workflow steps were recorded.");
    renderFlowDetail();
    return;
  }
  if (!state.selectedNodeId || !nodes.some((node) => node.id === state.selectedNodeId)) {
    state.selectedNodeId = nodes[0].id;
  }
  els.flowSteps.innerHTML = nodes
    .map(
      (node, index) => `<button
        class="flow-step${node.id === state.selectedNodeId ? " is-active" : ""}"
        type="button"
        role="tab"
        aria-selected="${node.id === state.selectedNodeId}"
        data-flow-node-id="${escapeHtml(node.id)}"
      >
        <span class="flow-step-number">${index + 1}</span>
        <span><strong>${escapeHtml(titleLabel(node.id))}</strong><small>${escapeHtml(
          titleLabel(node.status)
        )}</small></span>
      </button>`
    )
    .join("");
  renderFlowDetail();
}

function renderJobs() {
  const jobs = state.data.jobs;
  els.workflowJobs.innerHTML = jobs.length
    ? jobs
        .map(
          (job) => `
            <article class="compact-item">
              <div class="compact-main">
                <strong>${escapeHtml(titleLabel(job.workflow_name))}</strong>
                <span class="${pillClass(job.status)}">${escapeHtml(titleLabel(job.status))}</span>
              </div>
              ${renderMeta([
                job.id,
                `attempts ${job.attempt_count}/${job.max_attempts}`,
                job.worker_id ? `worker ${job.worker_id}` : null,
              ])}
              ${job.error_summary ? renderMeta([job.error_summary]) : ""}
              ${renderDeploymentJobActions(job)}
              ${renderDeadLetterJobActions(job)}
            </article>`
        )
        .join("")
    : renderEmpty("This run executed immediately in local mode, so no Redis worker queue job was created.");
}

function renderTimeline() {
  const items = state.data.timeline.filter((item) => item.kind !== "agent_event");
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
                titleLabel(item.kind),
                titleLabel(item.status),
                item.node_id ? `node ${titleLabel(item.node_id)}` : null,
                item.artifact_id ? `artifact ${item.artifact_id}` : null,
                item.workflow_job_id ? `job ${item.workflow_job_id}` : null,
              ])}
              ${item.summary ? renderMeta([item.summary]) : ""}
            </article>`
        )
        .join("")
    : renderEmpty("No key milestones recorded. Open Diagnostics to inspect technical events.");
}

function renderArtifacts() {
  const artifacts = state.data.run.artifacts;
  els.artifacts.innerHTML = artifacts.length
    ? artifacts
        .map(
          (artifact) => {
            const lineage = artifactLineage(artifact.id);
            const upstream = lineage ? lineage.upstream_artifacts.map((item) => item.id) : [];
            return `
            <article class="compact-item" id="${artifactElementId(artifact.id)}">
              <div class="compact-main">
                <strong>${escapeHtml(artifactTitle(artifact))}</strong>
                <span class="mini-pill">${escapeHtml(titleLabel(artifact.producer_node_id || "input"))}</span>
              </div>
              ${renderMeta([
                artifact.uri,
                `created ${formatDate(artifact.created_at)}`,
              ])}
              <a class="output-link compact-output-link" href="${artifactBrowserPath(artifact.id)}">
                <span>Open ${escapeHtml(artifactTitle(artifact))}</span>
                <small>Preview and inspect lineage</small>
              </a>
              <div class="detail-block">
                <strong>Source artifacts</strong>
                ${renderIdChips(artifact.source_artifact_ids, "none", true)}
              </div>
              <div class="detail-block">
                <strong>Lineage</strong>
                ${renderIdChips(upstream, "none", true)}
              </div>
              <details>
                <summary>Metadata</summary>
                ${renderKeyValues(artifact.metadata)}
              </details>
            </article>`;
          }
        )
        .join("")
    : renderEmpty("No artifacts recorded.");
}

function renderApprovalHistory() {
  const approvals = approvalEvents();
  els.approvalHistory.innerHTML = approvals.length
    ? approvals
        .slice()
        .reverse()
        .map((event) => {
          const decision =
            event.payload.decision || (event.event_type === "approval_request" ? "pending" : "");
          const actor = event.payload.approver || event.payload.requested_by || "system";
          const policyBits = [
            event.payload.tool ? `tool ${event.payload.tool}` : null,
            event.payload.policy_rule_id ? `rule ${event.payload.policy_rule_id}` : null,
            event.payload.escalation_target
              ? `escalate to ${event.payload.escalation_target}`
              : null,
          ];
          return `
            <article class="compact-item">
              <div class="compact-main">
                <strong>${escapeHtml(event.payload.message || titleLabel(event.event_type))}</strong>
                <span class="${pillClass(decision || event.event_type)}">
                  ${escapeHtml(titleLabel(decision || event.event_type))}
                </span>
              </div>
              ${renderMeta([
                `actor ${actor}`,
                event.node_id ? `node ${event.node_id}` : null,
                event.payload.workflow_job_id ? `job ${event.payload.workflow_job_id}` : null,
                formatDate(event.created_at),
              ])}
              ${policyBits.some(Boolean) ? renderMeta(policyBits) : ""}
              ${event.payload.reason ? renderMeta([event.payload.reason]) : ""}
              ${event.payload.rationale ? renderMeta([event.payload.rationale]) : ""}
            </article>`;
        })
        .join("")
    : renderEmpty("No approvals recorded.");
}

function renderEvaluations() {
  const evaluations = state.data.run.evaluations;
  els.evaluations.innerHTML = evaluations.length
    ? evaluations
        .map(
          (evaluation) => {
            const event = evaluationEventById(evaluation.id);
            const mlflowStatus = event?.payload?.mlflow_status || "not recorded";
            const langsmithStatus = event?.payload?.langsmith_status || null;
            return `
            <article class="compact-item">
              <div class="compact-main">
                <strong>${escapeHtml(evaluation.id)}</strong>
                <span class="${pillClass(evaluation.passed ? "passed" : "failed")}">
                  ${evaluation.passed ? "Passed" : "Failed"}
                </span>
              </div>
              ${renderMeta([
                `score ${evaluation.score}`,
                evaluation.target_artifact_id ? `artifact ${evaluation.target_artifact_id}` : null,
                `${evaluation.checks.length} checks`,
              ])}
              ${renderMeta([
                `MLflow ${mlflowStatus}`,
                langsmithStatus ? `LangSmith ${langsmithStatus}` : null,
              ])}
              <details>
                <summary>Checks</summary>
                ${renderKeyValues(
                  Object.fromEntries(
                    evaluation.checks.map((check, index) => [
                      titleLabel(check.name || `check_${index + 1}`),
                      `${check.passed ? "Passed" : "Failed"} (${check.score ?? "n/a"})`,
                    ])
                  ),
                  "No evaluation checks recorded."
                )}
              </details>
            </article>`;
          }
        )
        .join("")
    : renderEmpty("No evaluations recorded.");
}

function renderDeploymentHistory() {
  const jobs = deploymentJobs();
  const artifacts = deploymentArtifacts();
  const items = [
    ...jobs.map((job) => ({ kind: "job", item: job })),
    ...artifacts.map((artifact) => ({ kind: "artifact", item: artifact })),
  ];
  els.deploymentHistory.innerHTML = items.length
    ? items
        .map(({ kind, item }) => {
          if (kind === "artifact") {
            return `
              <article class="compact-item">
                <div class="compact-main">
                  <strong>${escapeHtml(item.id)}</strong>
                  <span class="${pillClass(item.metadata.deployment_status || "completed")}">
                    ${escapeHtml(titleLabel(item.metadata.deployment_status || "completed"))}
                  </span>
                </div>
                ${renderMeta([
                  item.metadata.destination,
                  item.metadata.approved_by ? `approved by ${item.metadata.approved_by}` : null,
                  `created ${formatDate(item.created_at)}`,
                ])}
                <div class="detail-block">
                  <strong>Promoted artifacts</strong>
                  ${renderIdChips(item.source_artifact_ids, "none", true)}
                </div>
              </article>`;
          }
          const approval = item.payload.approval || {};
          return `
            <article class="compact-item">
              <div class="compact-main">
                <strong>${escapeHtml(item.id)}</strong>
                <span class="${pillClass(item.status)}">${escapeHtml(titleLabel(item.status))}</span>
              </div>
              ${renderMeta([
                item.payload.destination,
                item.payload.requested_by ? `requested by ${item.payload.requested_by}` : null,
                approval.approver ? `decided by ${approval.approver}` : null,
              ])}
              <div class="detail-block">
                <strong>Artifacts</strong>
                ${renderIdChips(item.payload.artifact_ids || [], "none", true)}
              </div>
              ${approval.rationale ? renderMeta([approval.rationale]) : ""}
            </article>`;
        })
        .join("")
    : renderEmpty("No deployment history recorded.");
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
                <strong>${escapeHtml(titleLabel(event.event_type))}</strong>
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
  renderFlowStory();
  renderNodes();
  renderJobs();
  renderTimeline();
  renderArtifacts();
  renderApprovalHistory();
  renderEvaluations();
  renderDeploymentHistory();
  renderEvents();
}

function handleFlowSelection(event) {
  const target = event.target.closest("[data-flow-node-id]");
  if (!target) {
    return;
  }
  state.selectedNodeId = target.dataset.flowNodeId;
  renderFlowStory();
  renderNodes();
  els.flowDetail.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function submitNodeAction(nodeId, action) {
  const encodedRunId = encodeURIComponent(state.runId);
  const encodedNodeId = encodeURIComponent(nodeId);
  if (action === "approve" || action === "deny") {
    return requestJson(`/runs/${encodedRunId}/graph-nodes/${encodedNodeId}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved: action === "approve",
        comment:
          action === "approve"
            ? "Approved from run inspector."
            : "Denied from run inspector.",
      }),
    });
  }
  if (action === "retry") {
    return requestJson(`/runs/${encodedRunId}/graph-nodes/${encodedNodeId}/retry`, {
      method: "POST",
    });
  }
  throw new Error(`Unsupported node action: ${action}`);
}

async function submitDeploymentAction(jobId, action) {
  const encodedRunId = encodeURIComponent(state.runId);
  const encodedJobId = encodeURIComponent(jobId);
  return requestJson(`/runs/${encodedRunId}/deployments/${encodedJobId}/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      approved: action === "approve",
      approver: "Run Inspector",
      rationale:
        action === "approve"
          ? "Deployment approved from run inspector."
          : "Deployment denied from run inspector.",
    }),
  });
}

async function submitWorkflowJobAction(jobId, action) {
  const encodedRunId = encodeURIComponent(state.runId);
  const encodedJobId = encodeURIComponent(jobId);
  if (action !== "retry" && action !== "dismiss") {
    throw new Error(`Unsupported workflow job action: ${action}`);
  }
  return requestJson(`/runs/${encodedRunId}/workflow-jobs/${encodedJobId}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      reason:
        action === "retry"
          ? "Manual retry requested from run inspector."
          : "Dead-letter job dismissed from run inspector.",
    }),
  });
}

function actionSuccessMessage(nodeId, action) {
  if (action === "approve") {
    return `Approved ${nodeId}.`;
  }
  if (action === "deny") {
    return `Denied ${nodeId}.`;
  }
  return `Retried ${nodeId}.`;
}

function deploymentActionSuccessMessage(jobId, action) {
  return action === "approve"
    ? `Approved deployment ${jobId}.`
    : `Denied deployment ${jobId}.`;
}

function workflowJobActionSuccessMessage(jobId, action) {
  return action === "retry"
    ? `Queued retry for workflow job ${jobId}.`
    : `Dismissed workflow job ${jobId}.`;
}

async function handleNodeAction(event) {
  const button = event.target.closest("[data-node-action]");
  if (!button) {
    return;
  }

  const nodeId = button.dataset.nodeId;
  const action = button.dataset.nodeAction;
  state.pendingAction = { nodeId, action };
  setActionStatus("", "idle");
  renderNodes();

  try {
    await submitNodeAction(nodeId, action);
    setActionStatus(actionSuccessMessage(nodeId, action), "success");
    await loadRun();
  } catch (error) {
    setActionStatus(error.message, "error");
  } finally {
    state.pendingAction = null;
    if (state.data) {
      renderNodes();
    }
  }
}

async function handleDeploymentAction(event) {
  const deploymentButton = event.target.closest("[data-deployment-action]");
  const jobButton = event.target.closest("[data-job-action]");
  if (!deploymentButton && !jobButton) {
    return;
  }

  if (jobButton) {
    const jobId = jobButton.dataset.jobId;
    const action = jobButton.dataset.jobAction;
    state.pendingAction = { jobId, action };
    setActionStatus("", "idle");
    renderJobs();

    try {
      await submitWorkflowJobAction(jobId, action);
      setActionStatus(workflowJobActionSuccessMessage(jobId, action), "success");
      await loadRun();
    } catch (error) {
      setActionStatus(error.message, "error");
    } finally {
      state.pendingAction = null;
      if (state.data) {
        renderJobs();
      }
    }
    return;
  }

  const button = deploymentButton;
  const jobId = button.dataset.jobId;
  const action = button.dataset.deploymentAction;
  state.pendingAction = { jobId, action };
  setActionStatus("", "idle");
  renderJobs();

  try {
    await submitDeploymentAction(jobId, action);
    setActionStatus(deploymentActionSuccessMessage(jobId, action), "success");
    await loadRun();
  } catch (error) {
    setActionStatus(error.message, "error");
  } finally {
    state.pendingAction = null;
    if (state.data) {
      renderJobs();
    }
  }
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
    const lineageByArtifactId = await loadArtifactLineage(run);
    state.data = { run, jobs, graphNodes, events, timeline, lineageByArtifactId };
    renderAll();
  } catch (error) {
    els.runTitle.textContent = state.runId;
    els.runStatus.textContent = "Error";
    els.runStatus.className = "status-pill status-failed";
    els.errorText.textContent = error.message;
    els.taskText.textContent = "Unable to load run inspection data.";
  }
}

async function loadArtifactLineage(run) {
  const encodedRunId = encodeURIComponent(state.runId);
  const entries = await Promise.all(
    run.artifacts.map(async (artifact) => {
      try {
        const lineage = await fetchJson(
          `/runs/${encodedRunId}/artifacts/${encodeURIComponent(artifact.id)}/lineage`
        );
        return [artifact.id, lineage];
      } catch {
        return [artifact.id, null];
      }
    })
  );
  return Object.fromEntries(entries);
}

els.graphNodes.addEventListener("click", handleNodeAction);
els.graphNodes.addEventListener("click", handleFlowSelection);
els.flowSteps.addEventListener("click", handleFlowSelection);
els.workflowJobs.addEventListener("click", handleDeploymentAction);

loadRun();
