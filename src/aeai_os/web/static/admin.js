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
};

async function requestJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
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
  return String(value ?? "unknown").replaceAll("_", " ");
}

function chip(value, extraClass = "") {
  const normalized = String(value ?? "unknown").toLowerCase();
  const cssClass = `status-${normalized.replaceAll(" ", "_")}`;
  return `<span class="chip ${cssClass} ${extraClass}">${escapeHtml(label(normalized))}</span>`;
}

function setText(element, value) {
  element.textContent = value;
}

function setStatus(element, value) {
  element.textContent = label(value);
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
              <strong>${escapeHtml(agent.agent_type)}</strong>
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
              <strong>${escapeHtml(connector.name)}</strong>
              <span>${escapeHtml(connector.id)} &middot; ${escapeHtml(connector.provider)} &middot; ${escapeHtml(connector.kind)}</span>
            </div>
            ${chip(status)}
          </div>
          <p>${escapeHtml(message)}</p>
          <div class="meta-row">
            <span>Profile</span>
            <strong>${escapeHtml(connector.credential_profile_id || "none")}</strong>
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
              <span>${escapeHtml(profile.provider)} &middot; ${escapeHtml(profile.credential_type)}</span>
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
          <strong>${escapeHtml(permission.tool)}</strong>
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
          <strong>${escapeHtml(rule.id)}</strong>
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
              <strong>${escapeHtml(run.id)}</strong>
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
    const [agents, connectors, profiles, policies, affectedRuns] = await Promise.all([
      requestJson("/admin/agents"),
      requestJson("/connectors"),
      requestJson("/connectors/credential-profiles"),
      requestJson("/admin/policies"),
      requestJson("/admin/affected-runs"),
    ]);
    const healthById = await loadConnectorHealth(connectors);

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
refreshAdmin();
