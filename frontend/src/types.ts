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

export interface WorkflowJob {
  id: string; run_id: string; workflow_name: string; status: string;
  attempt_count: number; max_attempts: number; worker_id: string | null;
  error_summary: string | null; created_at: string; updated_at: string;
}
export interface RunProgressSnapshot {
  run: Run; nodes: GraphNode[]; jobs: WorkflowJob[]; event_count: number;
}

export interface RunQuestionEvidence { id: string; label: string; facts: Record<string, string | number | boolean | null>; source_paths: string[]; source_artifact_id: string }
export interface RunQuestion { id: string; question: string; answer: string; evidence: RunQuestionEvidence[]; limitations: string[]; model: string; estimated_cost_usd: number; created_at: string }

export interface AnalystPoint { label: string; value: number; transactions: number }
export interface AnalystCalculation {
  id: string; question: string; answer: string; tool: string; tool_label: string;
  chart_kind: 'bar' | 'line'; chart_title: string; currency: string;
  points: AnalystPoint[]; verified_total: number; evidence_artifact_id: string;
  limitations: string[]; model: string; estimated_cost_usd: number;
  model_calls: number; created_at: string;
}

export interface IntelligenceAnalysis {
  run_id: string; task: string; updated_at: string; artifact_id: string;
  analysis_type: string; currency: string | null;
  figures: Record<string, number>; trend: Array<{label:string;value:number}>;
  insights: string[]; recommendations: string[];
  opportunities: Array<{description:string;estimated_savings:number|null}>;
}
export interface IntelligenceOverview {
  completed_runs: number; analyzed_runs: number; latest: IntelligenceAnalysis | null;
  analyses: IntelligenceAnalysis[]; note: string;
}
export interface WorkspaceHealth {
  persistent_runs: boolean; repository: string;
  stale_runs: Array<{run_id:string;task:string;status:string;updated_at:string}>;
  failed_runs: Array<{run_id:string;task:string;status:string;updated_at:string}>;
  auto_recovery_enabled: boolean; message: string;
}

export interface VisualizationCell {
  supplier: string; category: string; department: string; month: string;
  amount: number; transactions: number;
}
export interface VisualizationCube {
  cells: VisualizationCell[]; dimensions: string[]; covered_transactions: number;
  suppressed_cells: number; note: string;
}

// Upgrade 12: scheduled, read-only intelligence monitoring.
export interface Monitor {
  id:string; organization_id:string; workspace_id:string;
  name:string; task:string; source_id:string; interval:'hourly'|'daily'|'weekly';
  enabled:boolean; only_on_change:boolean; ai_escalation:boolean;
  anomaly_limit:number; spend_change_pct:number; minimum_completeness:number;
  last_checked_at:string|null; last_run_id:string|null; next_due_at:string;
  created_at:string; updated_at:string;
}
export interface MonitorAlert {
  id:string; monitor_id:string; dispatch_id:string; run_id:string|null;
  severity:'high'|'medium'|'low'; title:string; description:string;
  rule:string; status:'open'|'acknowledged'|'resolved';
  evidence:Record<string,string|number>; created_at:string; updated_at:string;
}
export interface MonitoringSummary {
  monitor_count:number; enabled_monitors:number; open_alerts:number;critical_alerts:number;
  worker_online:boolean; worker_last_seen:string|null;
  recent_alerts:MonitorAlert[]; auto_ai_enabled:boolean; note:string;
}
export interface MonitorExecution {
  id:string; monitor_id:string; started_at:string; finished_at:string|null;
  status:string; run_id:string|null; metrics:Record<string,number>;ai_review?:{status:string;interpretation?:string;recommended_next_step?:string};error:string|null;
}

// Upgrade 12.5: authenticated, workspace-scoped operations overview.
export interface OperationsJob {
  id:string; run_id:string; task:string; status:string;
  created_at:string; attempt_count:number; max_attempts:number;
  error_summary:string|null;
}
export interface OperationsStatus {
  workflow_worker: {online:boolean;active:boolean;last_seen:string|null;mode:'inline'|'managed'};
  queue: {queued:number;running:number;failed:number;dead_letter:number;completed:number};
  guidance:string; jobs:OperationsJob[]; execution_mode:string;
  repository:string; actions:{retry_dead_letter:boolean;arbitrary_shell:boolean};
}

// Upgrade 13: backend-measured execution metrics and independent evidence checks.
export interface RunVerification {
  run_id: string; status: string; reason?: string; rows_scanned?: number;
  checks?: Record<string, boolean>; checks_passed?: number; checks_total?: number;
  reported_total?: number; independently_calculated_total?: number; duration_seconds?: number;
}
export interface PerformanceSummary {
  runs_sampled: number; completed_runs: number; audited_rows: number;
  verification: Record<'verified'|'mismatch'|'failed'|'skipped'|'unavailable'|'not_checked', number>;
  average_job_duration_seconds: number|null; measured_jobs: number;
  recent_verifications: Array<{run_id:string;task:string;status:string;rows_scanned?:number;checks_passed?:number;checks_total?:number}>;
  description: string;
}
