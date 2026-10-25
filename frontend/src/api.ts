import type { AgentEvent, AgentRegistration, Analysis, Artifact, Connector, DataSource, Evaluation, GraphNode, Investigation, InvestigationSummary, PolicyRegistry, Run, RunDetail, UserSession } from './types';

export class ApiError extends Error { constructor(message: string, readonly status: number) { super(message); this.name = 'ApiError'; } }
function humanError(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(humanError).join('; ');
  if (detail && typeof detail === 'object') {
    const d = detail as Record<string, unknown>;
    return humanError(d.message ?? d.msg ?? JSON.stringify(detail));
  }
  return detail ? String(detail) : 'Request failed';
}
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', ...init });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => undefined);
    const detail = payload && typeof payload === 'object' && 'detail' in payload ? (payload as {detail: unknown}).detail : payload;
    throw new ApiError(humanError(detail) || `HTTP ${response.status}`, response.status);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type') || '';
  return contentType.includes('application/json') ? response.json() as Promise<T> : response.text() as Promise<T>;
}
const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const enc = encodeURIComponent;
export const api = {
  health: () => request<Record<string, unknown>>('/health'),
  me: () => request<UserSession>('/auth/me'),
  runs: () => request<Run[]>('/runs'),
  run: (id: string) => request<RunDetail>(`/runs/${enc(id)}`),
  createRun: (payload: {task: string; dataset_uri?: string; data_source_id?: string; metadata: Record<string, unknown>}) => request<RunDetail>('/runs', json(payload)),
  executeRun: (id: string) => request<RunDetail>(`/runs/${enc(id)}/execute`, {method: 'POST'}),
  graph: (id: string) => request<GraphNode[]>(`/runs/${enc(id)}/graph-nodes`),
  events: (id: string) => request<AgentEvent[]>(`/runs/${enc(id)}/events`),
  artifacts: (id: string) => request<Artifact[]>(`/runs/${enc(id)}/artifacts`),
  evaluations: (id: string) => request<Evaluation[]>(`/runs/${enc(id)}/evaluations`),
  approve: (id: string, nodeId: string, approved: boolean, comment: string) => request<RunDetail>(`/runs/${enc(id)}/graph-nodes/${enc(nodeId)}/approval`, json({approved, comment})),
  retryNode: (id: string, nodeId: string) => request<RunDetail>(`/runs/${enc(id)}/graph-nodes/${enc(nodeId)}/retry`, {method: 'POST'}),
  artifactContent: (runId: string, artifactId: string) => request<Analysis>(`/runs/${enc(runId)}/artifacts/${enc(artifactId)}/content`),
  artifactUrl: (runId: string, artifactId: string, download = false) => `/runs/${enc(runId)}/artifacts/${enc(artifactId)}/content${download ? '?download=true' : ''}`,
  dataSources: () => request<DataSource[]>('/data-sources'),
  registerDataSource: (payload: {id: string; name: string; source_type: string; dataset_uri: string; owner: string}) => request<DataSource>('/data-sources', json(payload)),
  validateDataSource: (id: string) => request<{status: string; message: string}>(`/data-sources/${enc(id)}/validate`, {method: 'POST'}),
  connectors: () => request<Connector[]>('/connectors'),
  investigations: () => request<Investigation[]>('/investigations'),
  investigationSummary: () => request<InvestigationSummary>('/investigations/summary'),
  updateInvestigation: (runId: string, anomalyId: string, payload: {status: string; comment?: string; assignee?: string}) => request<Investigation>(`/investigations/${enc(runId)}/${enc(anomalyId)}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}),
  agents: () => request<AgentRegistration[]>('/admin/agents'),
  policies: () => request<PolicyRegistry>('/admin/policies'),
  metrics: () => request<string>('/metrics'),
};
