import { Activity, ShieldCheck, Wallet } from 'lucide-react';
import type { AgentEvent } from '../types';
import './ai-usage-panel.css';

type Summary = {
  provider: string; model_calls: number; model_calls_completed: number;
  model_calls_failed: number; model_calls_blocked: number;
  estimated_cost_usd: number; estimated_input_units: number;
  estimated_output_units: number; workflow_budget_usd: number;
  monthly_app_budget_usd: number; app_ledger_booked_usd: number;
  month: string; calls?: Array<{ purpose?: string; status?: string; estimated_cost_usd?: number }>;
};

function isSummary(data: unknown): data is Summary {
  if (!data || typeof data !== 'object') return false;
  const value = data as Record<string, unknown>;
  return typeof value.model_calls === 'number' && typeof value.workflow_budget_usd === 'number';
}

const money = (amount: number) => `$${(Number.isFinite(amount) ? amount : 0).toFixed(5)}`;

/** This reads persisted workflow events, not a provider billing API. */
export function AiUsagePanel({events}: {events: AgentEvent[]}) {
  const usage = [...events].reverse()
    .map(event => event.payload?.llm_usage_summary)
    .find(isSummary);
  if (!usage) return null;
  const percent = usage.workflow_budget_usd > 0
    ? Math.min(100, Math.max(0, 100 * usage.estimated_cost_usd / usage.workflow_budget_usd))
    : 0;
  return <section className="ae-ai-usage" aria-label="AI usage and estimated costs">
    <div className="ae-ai-usage-title">
      <div className="ae-ai-usage-head"><Wallet size={18}/><div><strong>AI Usage & Budget</strong><span>Hugging Face · Estimated inference spend</span></div></div>
      <span className="ae-ai-usage-pill"><ShieldCheck size={14}/> Guardrails enabled</span>
    </div>
    <div className="ae-ai-usage-metrics">
      <div><span>ESTIMATED SPEND</span><strong>{money(usage.estimated_cost_usd)}</strong><small>of {money(usage.workflow_budget_usd)} workflow allowance</small></div>
      <div><span>MODEL CALLS</span><strong>{usage.model_calls}</strong><small>{usage.model_calls_completed} success · {usage.model_calls_failed} failed · {usage.model_calls_blocked} blocked</small></div>
      <div><span>TOKENS ACCOUNTED</span><strong>{(usage.estimated_input_units + usage.estimated_output_units).toLocaleString()}</strong><small>Input {usage.estimated_input_units.toLocaleString()} · Output {usage.estimated_output_units.toLocaleString()}</small></div>
      <div><span>MONTHLY APP LEDGER</span><strong>{money(usage.app_ledger_booked_usd)}</strong><small>of {money(usage.monthly_app_budget_usd)} app-side allowance</small></div>
    </div>
    <div className="ae-ai-usage-meter" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100} aria-label="Estimated workflow cost budget used"><span style={{width:`${percent}%`}}/></div>
    <div className="ae-ai-usage-note"><Activity size={13}/> Estimated using configured model prices and provider tokens when reported. This is not your Hugging Face bill, total balance, or a guaranteed hard spending cap.</div>
  </section>;
}
