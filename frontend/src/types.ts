export type RunStatus = 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'waiting_for_approval' | 'cancelled' | string;
export interface Run {
  id: string; task: string; status: RunStatus; metadata: Record<string, unknown>;
  dataset_artifact_id: string | null; created_at: string; updated_at: string;
  trace_id: string | null; error_summary: string | null;
}
export interface RunDetail extends Run { artifacts: Artifact[]; evaluations: Evaluation[]; audit_events?: AuditEvent[] }
export interface Artifact {
  id: string; run_id: string; producer_node_id: string | null; type: string; uri: string;
  metadata: Record<string, unknown>; content_type: string | null; storage_backend: string | null;
  storage_key: string | null; size_bytes: number | null; source_artifact_ids: string[]; created_at: string;
}
export interface GraphNode {
  id: string; run_id: string; agent_type: string; status: string; depends_on: string[];
  required_tools: string[]; expected_artifacts: string[]; retry_count: number;
  started_at: string | null; finished_at: string | null; created_at: string; updated_at: string;
}
export interface AgentEvent { id: string; run_id: string; node_id: string; event_type: string; payload: Record<string, unknown>; created_at: string }
export interface Evaluation { id: string; run_id: string; target_artifact_id: string | null; score: number; passed: boolean; checks: Array<{ name?: string; passed?: boolean; score?: number; [key: string]: unknown }>; created_at: string }
export interface AuditEvent { id: string; action: string; actor: Record<string, unknown>; target: Record<string, unknown>; timestamp: string }
export interface DataSource { id: string; name: string; source_type: string; connector_id: string; dataset_uri: string; owner: string; latest_validation: {status: string; message: string} | null; metadata: Record<string, unknown> }
export interface Connector { id: string; name: string; provider: string; kind: string; capabilities: string[]; status: string }
export interface Investigation { id: string; run_id: string; run_task: string; anomaly_id: string; status: string; assignee: string | null; supplier: string; category: string; amount: number; currency: string; risk_score: number; severity: string; confidence: number; reason: string; signals: Array<Record<string, unknown>>; recommended_action: string; updated_at: string }
export interface InvestigationSummary { total: number; new: number; investigating: number; confirmed: number; dismissed: number; resolved: number; critical: number; high: number; risk_exposure: number; risk_exposure_by_currency: Record<string, number> }
export interface AgentRegistration { agent_type: string; description: string; risk_profile: string; capabilities: string[]; status: string }
export interface PolicyRegistry { permissions: Array<Record<string, unknown>>; rules: Array<Record<string, unknown>>; summary: Record<string, number> }
export interface UserSession { user_id: string; name: string | null; roles: string[]; organization_id: string; workspace_ids: string[]; active_workspace_id: string; permissions: string[] }
export type Analysis = {
  analysis_type?: string; kpis?: Record<string, number | null>; insights?: string[];
  spend_trend?: Array<{month: string; spend: number}>;
  spend_by_supplier?: Array<{supplier: string; spend: number}>;
  spend_by_category?: Array<{category: string; spend: number}>;
  time_series?: Array<{period: string; value: number; measure: string}>;
  measure_summaries?: Array<{column: string; sum: number | null; mean: number | null}>;
  dataset?: Record<string, unknown>;
  [key: string]: unknown;
};
