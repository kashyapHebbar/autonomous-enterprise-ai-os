import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Activity, CheckCircle2, Database, Gauge, ShieldCheck, TriangleAlert } from 'lucide-react';
import { api } from '../api';
import '../intelligence-performance.css';

export default function IntelligencePerformance() {
  const result = useQuery({queryKey:['intelligence-performance'],queryFn:api.performanceSummary,refetchInterval:30000});
  const data = result.data;
  if (result.isError) return <section className="ip-panel"><h2>Intelligence performance</h2><p>Performance measurements are temporarily unavailable.</p></section>;
  return <section className="ip-panel" aria-label="Intelligence performance">
    <div className="ip-heading"><div><span className="ip-eyebrow">MEASURED SYSTEM RESULTS</span><h2>Intelligence performance</h2><p>Independent source checks and real execution timings—never guessed figures.</p></div><Link to="/operations" className="btn btn-secondary">Operations Center</Link></div>
    <div className="ip-metrics">
      <div className="ip-metric"><Database size={19}/><span>Rows independently checked</span><strong>{data ? data.audited_rows.toLocaleString() : '—'}</strong><small>Across fully checked runs, not unique source rows</small></div>
      <div className="ip-metric"><CheckCircle2 size={19}/><span>Reconciled analyses</span><strong>{data ? data.verification.verified : '—'}</strong><small>Source totals matched saved financial KPIs</small></div>
      <div className="ip-metric"><Gauge size={19}/><span>Measured job duration</span><strong>{data?.average_job_duration_seconds != null ? `${data.average_job_duration_seconds.toFixed(1)}s` : '—'}</strong><small>Average of {data?.measured_jobs ?? 0} completed jobs</small></div>
      <div className="ip-metric"><TriangleAlert size={19}/><span>Needs verification review</span><strong>{data ? (data.verification.mismatch + data.verification.failed) : '—'}</strong><small>Independent mismatches or verification errors</small></div>
    </div>
    {data?.recent_verifications.length ? <div className="ip-recents"><span>Recent evidence checks</span>{data.recent_verifications.slice(0,4).map(item=><Link to={`/workflows/${encodeURIComponent(item.run_id)}`} key={item.run_id}><ShieldCheck size={16}/><span>{item.task}</span><em className={item.status==='verified'?'ip-verified':'ip-warning'}>{item.status.replaceAll('_',' ')}</em></Link>)}</div>:<div className="ip-empty"><Activity size={18}/> New managed investigations will record independent evidence checks here. Existing runs remain available.</div>}
    <p className="ip-footnote">Passing reconciliation validates selected procurement totals—not the accuracy of every anomaly, prediction, or AI-generated conclusion.</p>
  </section>;
}
