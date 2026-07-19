const elements = {
  refresh: document.querySelector("#refreshAdmin"),
  agentCount: document.querySelector("#agentCount"),
  connectorCount: document.querySelector("#connectorCount"),
  policyRuleCount: document.querySelector("#policyRuleCount"),
  affectedRunCount: document.querySelector("#affectedRunCount"),
  agentStatus: document.querySelector("#agentStatus"),
  connectorStatus: document.querySelector("#connectorStatus"),
  profileStatus: document.querySelector("#profileStatus"),
  policyStatus: document.querySelector("#policyStatus"),
  affectedStatus: document.querySelector("#affectedStatus"),
  agentsList: document.querySelector("#agentsList"),
  connectorsList: document.querySelector("#connectorsList"),
  profilesList: document.querySelector("#profilesList"),
  permissionsList: document.querySelector("#permissionsList"),
  rulesList: document.querySelector("#rulesList"),
  affectedRunsList: document.querySelector("#affectedRunsList"),
  installationStatus: document.querySelector("#installationStatus"),
  connectorForm: document.querySelector("#connectorForm"),
  organizationId: document.querySelector("#organizationId"),
  workspaceId: document.querySelector("#workspaceId"),
  connectorId: document.querySelector("#connectorId"),
  installationName: document.querySelector("#installationName"),
  credentialReference: document.querySelector("#credentialReference"),
  configurationFields: document.querySelector("#configurationFields"),
  connectorFormMessage: document.querySelector("#connectorFormMessage"),
  installationsList: document.querySelector("#installationsList"),
};

const connectorHub = { connectors: [], installations: [] };

async function requestJson(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const message = await readError(response);
    throw new Error(`${response.status} ${message}`);
  }
  return response.json();
}

async function readError(response) {
  try {
    const payload = await response.json();
    return payload.detail || response.statusText;
  } catch {
    return response.statusText;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function label(value) {
  return String(value ?? "unknown")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replaceAll(":", ": ");
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
      const suffix = word.endsWith(":") ? ":" : "";
      const key = word.replace(":", "").toLowerCase();
      return `${acronyms[key] || key[0].toUpperCase() + key.slice(1)}${suffix}`;
    })
    .join(" ");
}

function chip(value, extraClass = "") {
  const normalized = String(value ?? "unknown").toLowerCase();
  const cssClass = `status-${normalized.replaceAll(" ", "_")}`;
  return `<span class="chip ${cssClass} ${extraClass}">${escapeHtml(displayStatus(normalized))}</span>`;
}

function displayStatus(value) {
  const normalized = String(value || "unknown").toLowerCase();
  const names = {
    ok: "Ready",
    not_configured: "Setup needed",
    loading: "Checking",
    failed: "Attention",
  };
  return names[normalized] || titleLabel(normalized);
}

function agentName(value) {
  const names = {
    analytics_code: "Analytics",
    data_retrieval: "Data Retrieval",
    evaluation: "Quality Evaluation",
    planner: "Planning",
    report: "Reporting",
  };
  return names[value] || titleLabel(value);
}

function setText(element, value) {
  element.textContent = value;
}

function setStatus(element, value) {
  element.textContent = displayStatus(value);
  element.className = `status-pill status-${String(value).toLowerCase()}`;
}

function empty(message) {
  return `<p class="empty">${escapeHtml(message)}</p>`;
}

function errorBox(message) {
  return `<p class="error-box">${escapeHtml(message)}</p>`;
}

function renderAgents(agents) {
  if (!agents.length) {
    elements.agentsList.innerHTML = empty("No agents registered.");
    return;
  }
  elements.agentsList.innerHTML = agents
    .map(
      (agent) => `
        <article class="item-card">
          <div class="item-header">
            <div class="item-title">
              <strong>${escapeHtml(agentName(agent.agent_type))}</strong>
              <span>${escapeHtml(agent.description)}</span>
            </div>
            ${chip(agent.risk_profile)}
          </div>
          <div class="chips">
            ${agent.capabilities.map((capability) => chip(capability)).join("")}
          </div>
        </article>
      `
    )
    .join("");
}

function renderConnectors(connectors, healthById) {
  if (!connectors.length) {
    elements.connectorsList.innerHTML = empty("No connectors registered.");
    return;
  }
  elements.connectorsList.innerHTML = connectors
    .map((connector) => {
      const health = healthById.get(connector.id);
      const status = health?.status || connector.status || "unknown";
      const message = health?.message || "Health check unavailable.";
      const details = health?.details || {};
      return `
        <article class="item-card">
          <div class="item-header">
            <div class="item-title">
              <strong>${escapeHtml(titleLabel(connector.name))}</strong>
              <span title="${escapeHtml(connector.id)}">${escapeHtml(
                titleLabel(connector.provider)
              )} &middot; ${escapeHtml(titleLabel(connector.kind))}</span>
            </div>
            ${chip(status)}
          </div>
          <p>${escapeHtml(message)}</p>
          <div class="meta-row">
            <span>Profile</span>
            <strong>${escapeHtml(titleLabel(connector.credential_profile_id || "none"))}</strong>
          </div>
          <div class="chips">
            ${(connector.capabilities || []).map((capability) => chip(capability)).join("")}
          </div>
          ${renderEnvDetails(details)}
        </article>
      `;
    })
    .join("");
}

function renderConnectorOptions(connectors) {
  const previous = elements.connectorId.value;
  elements.connectorId.innerHTML = connectors
    .map(
      (connector) =>
        `<option value="${escapeHtml(connector.id)}">${escapeHtml(connector.name)}</option>`
    )
    .join("");
  if (connectors.some((connector) => connector.id === previous)) {
    elements.connectorId.value = previous;
  }
  renderConfigurationFields();
}

function selectedConnector() {
  return connectorHub.connectors.find((connector) => connector.id === elements.connectorId.value);
}

function renderConfigurationFields() {
  const connector = selectedConnector();
  const fields = connector?.configuration_fields || [];
  elements.configurationFields.innerHTML = fields
    .map(
      (field) => `
        <label>
          <span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>
          <input
            name="configuration.${escapeHtml(field.key)}"
            data-configuration-key="${escapeHtml(field.key)}"
            placeholder="${escapeHtml(field.placeholder || "")}"
            ${field.required ? "required" : ""}
          />
        </label>
      `
    )
    .join("");
  elements.credentialReference.required = Boolean(connector?.credential_required);
}

function renderInstallations(installations) {
  if (!installations.length) {
    elements.installationsList.innerHTML = empty("No saved connections for this organization.");
    return;
  }
  elements.installationsList.innerHTML = installations
    .map(
      (installation) => `
        <article class="item-card">
          <div class="item-header">
            <div class="item-title">
              <strong>${escapeHtml(installation.name)}</strong>
              <span>${escapeHtml(titleLabel(installation.connector_id))}</span>
            </div>
            ${chip(installation.status)}
          </div>
          <div class="meta-row">
            <span>Workspace</span>
            <strong>${escapeHtml(installation.workspace_id || "Organization-wide")}</strong>
          </div>
          <div class="meta-row">
            <span>Credential</span>
            <strong>${escapeHtml(installation.credential_reference || "Not required")}</strong>
          </div>
          <div class="installation-actions">
            <button
              class="command-button test-connection"
              type="button"
              data-installation-id="${escapeHtml(installation.id)}"
            >Test Connection</button>
          </div>
        </article>
      `
    )
    .join("");
}

async function loadInstallations() {
  const installations = await requestJson("/connectors/installations");
  connectorHub.installations = installations;
  renderInstallations(installations);
  setStatus(elements.installationStatus, installations.length ? "ok" : "not_configured");
  return installations;
}

function renderEnvDetails(details) {
  const missing = details.missing_env_keys || [];
  const configured = details.configured_env_keys || [];
  if (!missing.length && !configured.length) {
    return "";
  }
  return `
    <div class="chips">
      ${configured.map((key) => chip(`configured:${key}`, "status-ok")).join("")}
      ${missing.map((key) => chip(`missing:${key}`, "status-not_configured")).join("")}
    </div>
  `;
}

function renderProfiles(profiles) {
  if (!profiles.length) {
    elements.profilesList.innerHTML = empty("No credential profiles registered.");
    return;
  }
  elements.profilesList.innerHTML = profiles
    .map(
      (profile) => `
        <article class="item-card">
          <div class="item-header">
            <div class="item-title">
              <strong>${escapeHtml(profile.id)}</strong>
              <span>${escapeHtml(titleLabel(profile.provider))} &middot; ${escapeHtml(titleLabel(profile.credential_type))}</span>
            </div>
            ${chip(profile.configured ? "ok" : "not_configured")}
          </div>
          <p>${escapeHtml(profile.description || "Environment-backed credential profile.")}</p>
          <div class="chips">
            ${(profile.configured_env_keys || []).map((key) => chip(`configured:${key}`, "status-ok")).join("")}
            ${(profile.missing_env_keys || []).map((key) => chip(`missing:${key}`, "status-not_configured")).join("")}
          </div>
        </article>
      `
    )
    .join("");
}

function renderPolicies(policy) {
  const permissions = policy.permissions || [];
  const rules = policy.rules || [];
  elements.permissionsList.innerHTML = permissions.length
    ? permissions.map(renderPermission).join("")
    : empty("No tool permissions registered.");
  elements.rulesList.innerHTML = rules.length
    ? rules.map(renderRule).join("")
    : empty("No policy rules registered.");
}

function renderPermission(permission) {
  const flags = [
    permission.approval_required ? "approval required" : null,
    permission.blocked ? "blocked" : null,
    permission.destructive ? "destructive" : null,
  ].filter(Boolean);
  return `
    <article class="item-card">
      <div class="item-header">
        <div class="item-title">
          <strong>${escapeHtml(titleLabel(permission.tool))}</strong>
          <span>${escapeHtml(permission.description)}</span>
        </div>
        ${chip(permission.risk)}
      </div>
      <div class="chips">
        ${chip(permission.permission_level)}
        ${flags.map((flag) => chip(flag)).join("")}
      </div>
    </article>
  `;
}

function renderRule(rule) {
  const matchers = [
    ...(rule.tool_patterns || []).map((value) => `tool:${value}`),
    ...(rule.permission_levels || []).map((value) => `permission:${value}`),
    ...(rule.risk_levels || []).map((value) => `risk:${value}`),
    ...(rule.connector_ids || []).map((value) => `connector:${value}`),
    ...(rule.artifact_types || []).map((value) => `artifact:${value}`),
    ...(rule.destinations || []).map((value) => `destination:${value}`),
  ];
  return `
    <article class="item-card">
      <div class="item-header">
        <div class="item-title">
          <strong>${escapeHtml(titleLabel(rule.id))}</strong>
          <span>${escapeHtml(rule.description)}</span>
        </div>
        ${chip(rule.decision)}
      </div>
      <p>${escapeHtml(rule.reason)}</p>
      <div class="chips">
        ${matchers.map((matcher) => chip(matcher)).join("")}
        ${rule.escalation_target ? chip(`escalate:${rule.escalation_target}`) : ""}
      </div>
    </article>
  `;
}

function renderAffectedRuns(runs) {
  if (!runs.length) {
    elements.affectedRunsList.innerHTML = empty("No connector or policy affected runs found.");
    return;
  }
  elements.affectedRunsList.innerHTML = runs
    .map(
      (run) => `
        <article class="item-card">
          <div class="item-header">
            <div class="item-title">
              <strong>${escapeHtml(titleLabel(run.affected_area))}</strong>
              <span>${escapeHtml(run.task)}</span>
            </div>
            ${chip(run.affected_area)}
          </div>
          <p>${escapeHtml(run.reason)}</p>
          <div class="chips">
            ${chip(run.status)}
            ${run.connector_id ? chip(`connector:${run.connector_id}`) : ""}
            ${run.policy_rule_id ? chip(`policy:${run.policy_rule_id}`) : ""}
          </div>
          <div class="meta-row">
            <span>${escapeHtml(new Date(run.updated_at).toLocaleString())}</span>
            <a class="run-link" href="${escapeHtml(run.inspector_url)}">Open Run</a>
          </div>
        </article>
      `
    )
    .join("");
}

async function loadConnectorHealth(connectors) {
  const entries = await Promise.all(
    connectors.map(async (connector) => {
      try {
        const health = await requestJson(`/connectors/${encodeURIComponent(connector.id)}/health`);
        return [connector.id, health];
      } catch (error) {
        return [connector.id, { status: "unknown", message: error.message, details: {} }];
      }
    })
  );
  return new Map(entries);
}

async function refreshAdmin() {
  elements.refresh.disabled = true;
  ["agentStatus", "connectorStatus", "profileStatus", "policyStatus", "affectedStatus"].forEach(
    (key) => setStatus(elements[key], "loading")
  );

  try {
    const [session, agents, connectors, profiles, policies, affectedRuns] = await Promise.all([
      requestJson("/auth/me"),
      requestJson("/admin/agents"),
      requestJson("/connectors"),
      requestJson("/connectors/credential-profiles"),
      requestJson("/admin/policies"),
      requestJson("/admin/affected-runs"),
    ]);
    elements.organizationId.value = session.organization_id;
    elements.workspaceId.value = session.active_workspace_id;
    const healthById = await loadConnectorHealth(connectors);

    connectorHub.connectors = connectors;
    renderConnectorOptions(connectors);
    await loadInstallations();

    renderAgents(agents);
    renderConnectors(connectors, healthById);
    renderProfiles(profiles);
    renderPolicies(policies);
    renderAffectedRuns(affectedRuns);

    setText(elements.agentCount, agents.length);
    setText(elements.connectorCount, connectors.length);
    setText(elements.policyRuleCount, policies.rules.length);
    setText(elements.affectedRunCount, affectedRuns.length);
    setStatus(elements.agentStatus, "ok");
    setStatus(elements.connectorStatus, connectors.some((item) => item.status !== "ok") ? "not_configured" : "ok");
    setStatus(elements.profileStatus, profiles.some((item) => !item.configured) ? "not_configured" : "ok");
    setStatus(elements.policyStatus, "ok");
    setStatus(elements.affectedStatus, affectedRuns.length ? "failed" : "ok");
  } catch (error) {
    const message = error.message || "Unable to load admin data.";
    elements.agentsList.innerHTML = errorBox(message);
    elements.connectorsList.innerHTML = errorBox(message);
    elements.profilesList.innerHTML = errorBox(message);
    elements.permissionsList.innerHTML = errorBox(message);
    elements.rulesList.innerHTML = errorBox(message);
    elements.affectedRunsList.innerHTML = errorBox(message);
    ["agentCount", "connectorCount", "policyRuleCount", "affectedRunCount"].forEach((key) =>
      setText(elements[key], "--")
    );
    ["agentStatus", "connectorStatus", "profileStatus", "policyStatus", "affectedStatus"].forEach(
      (key) => setStatus(elements[key], "blocked")
    );
  } finally {
    elements.refresh.disabled = false;
  }
}

elements.refresh.addEventListener("click", refreshAdmin);
elements.connectorId.addEventListener("change", renderConfigurationFields);
elements.connectorForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.connectorFormMessage.textContent = "Adding connection...";
  const configuration = {};
  elements.configurationFields.querySelectorAll("[data-configuration-key]").forEach((input) => {
    if (input.value.trim()) configuration[input.dataset.configurationKey] = input.value.trim();
  });
  try {
    await requestJson("/connectors/installations", {
      method: "POST",
      body: JSON.stringify({
        connector_id: elements.connectorId.value,
        name: elements.installationName.value.trim(),
        credential_reference: elements.credentialReference.value.trim() || null,
        configuration,
      }),
    });
    elements.connectorFormMessage.textContent = "Connection saved. Credentials remain external.";
    elements.installationName.value = "";
    elements.credentialReference.value = "";
    renderConfigurationFields();
    await loadInstallations();
  } catch (error) {
    showHubError(error);
  }
});
elements.installationsList.addEventListener("click", async (event) => {
  const button = event.target.closest(".test-connection");
  if (!button) return;
  button.disabled = true;
  try {
    const health = await requestJson(
      `/connectors/installations/${encodeURIComponent(button.dataset.installationId)}/test`,
      { method: "POST" }
    );
    elements.connectorFormMessage.textContent = health.message;
    setStatus(elements.installationStatus, health.status);
  } catch (error) {
    showHubError(error);
  } finally {
    button.disabled = false;
  }
});

function showHubError(error) {
  elements.connectorFormMessage.textContent = error.message || "Connector operation failed.";
  setStatus(elements.installationStatus, "failed");
}

refreshAdmin();
