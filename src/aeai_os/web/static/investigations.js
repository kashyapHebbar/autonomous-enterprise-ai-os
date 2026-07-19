const state = { cases: [], selected: null };
const $ = (selector) => document.querySelector(selector);

async function request(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === "string" ? payload.detail : "Request failed");
  }
  return response.json();
}
const money = (value, currency = "USD") => new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0 }).format(value || 0);
const exposure = (values) => {
  const entries = Object.entries(values || {});
  if (!entries.length) return money(0);
  if (entries.length === 1) return money(entries[0][1], entries[0][0]);
  return `${entries.length} currencies`;
};
const when = (value) => new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(value));
const escapeHtml = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

async function load() {
  const [session, summary, cases] = await Promise.all([request("/auth/me"), request("/investigations/summary"), request("/investigations")]);
  state.cases = cases;
  $("#workspaceName").textContent = session.active_workspace_id;
  $("#openCount").textContent = summary.new + summary.investigating;
  $("#criticalCount").textContent = summary.critical;
  $("#confirmedCount").textContent = summary.confirmed;
  $("#riskExposure").textContent = exposure(summary.risk_exposure_by_currency);
  $("#riskExposure").title = Object.entries(summary.risk_exposure_by_currency || {}).map(([currency, value]) => money(value, currency)).join(" · ");
  renderCases();
  if (state.selected) await selectCase(state.selected.run_id, state.selected.anomaly_id);
}

function renderCases() {
  const query = $("#caseSearch").value.trim().toLowerCase();
  const status = $("#statusFilter").value;
  const cases = state.cases.filter((item) => (!status || item.status === status) && (!query || `${item.supplier} ${item.category} ${item.reason}`.toLowerCase().includes(query)));
  $("#caseList").innerHTML = cases.length ? cases.map((item) => `<button class="case-row ${state.selected?.id === item.id ? "active" : ""}" data-run-id="${escapeHtml(item.run_id)}" data-anomaly-id="${escapeHtml(item.anomaly_id)}" type="button"><span class="score">${item.risk_score}</span><span class="transaction"><strong>${escapeHtml(item.supplier)}</strong><span>${escapeHtml(item.category)} · ${money(item.amount, item.currency)}</span></span><span class="status status-${item.status}">${escapeHtml(item.status)}</span><span class="owner">${escapeHtml(item.assignee || "Unassigned")}</span><span class="updated">${when(item.updated_at)}</span></button>`).join("") : '<p class="empty-list">No investigations match these filters.</p>';
}

async function selectCase(runId, anomalyId) {
  const item = await request(`/investigations/${encodeURIComponent(runId)}/${encodeURIComponent(anomalyId)}`);
  state.selected = item;
  $("#emptyDetail").hidden = true; $("#activeDetail").hidden = false;
  $("#detailSeverity").textContent = `${item.severity} risk`; $("#caseDetailTitle").textContent = item.supplier; $("#detailScore").textContent = item.risk_score;
  $("#detailAmount").textContent = money(item.amount, item.currency); $("#detailConfidence").textContent = `${Math.round(item.confidence * 100)}%`; $("#detailCategory").textContent = item.category; $("#detailRun").textContent = item.run_task;
  $("#evidenceList").innerHTML = item.signals.map((signal) => `<li><strong>+${signal.weight} ${escapeHtml(signal.code.replaceAll("_", " "))}</strong><br>${escapeHtml(signal.evidence)}</li>`).join("");
  $("#recommendedAction").textContent = item.recommended_action; $("#caseStatus").value = item.status; $("#caseAssignee").value = item.assignee || ""; $("#caseComment").value = "";
  $("#historyList").innerHTML = item.history.length ? [...item.history].reverse().map((entry) => `<div class="history-entry"><strong>${escapeHtml(entry.status)} · ${escapeHtml(entry.actor.name || entry.actor.id || "User")}</strong><span>${escapeHtml(entry.comment || entry.disposition_reason || "Case updated")} · ${when(entry.created_at)}</span></div>`).join("") : '<p class="empty-list">No decisions recorded yet.</p>';
  renderCases();
}

$("#caseList").addEventListener("click", (event) => { const row = event.target.closest("[data-anomaly-id]"); if (row) selectCase(row.dataset.runId, row.dataset.anomalyId).catch(showError); });
$("#caseSearch").addEventListener("input", renderCases); $("#statusFilter").addEventListener("change", renderCases); $("#refreshCases").addEventListener("click", () => load().catch(showError));
$("#caseForm").addEventListener("submit", async (event) => { event.preventDefault(); if (!state.selected) return; $("#caseMessage").textContent = "Saving decision..."; try { await request(`/investigations/${encodeURIComponent(state.selected.run_id)}/${encodeURIComponent(state.selected.anomaly_id)}`, { method: "PATCH", body: JSON.stringify({ status: $("#caseStatus").value, assignee: $("#caseAssignee").value.trim() || null, comment: $("#caseComment").value.trim() || null, disposition_reason: $("#caseComment").value.trim() || null }) }); $("#caseMessage").textContent = "Decision saved to the audit history."; await load(); } catch (error) { showError(error); } });
function showError(error) { $("#caseMessage").textContent = error.message || "Unable to load investigations."; }
load().catch(showError);
