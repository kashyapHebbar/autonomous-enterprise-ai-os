import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity, AlertCircle, AlertTriangle, ArrowRight, ArrowUpRight, Check,
  CheckCircle2, ChevronDown, CircleDot, Clock3, Database, HeartPulse,
  LoaderCircle, PauseCircle, Play, RefreshCw, RotateCcw, Search,
  ServerCog, ShieldCheck, SlidersHorizontal, Sparkles, Workflow, X,
} from 'lucide-react';
import { api } from '../api';
import { ErrorBox } from '../components/Ui';
import type { OperationsJob } from '../types';
import '../operations.css';

type QueueFilter = 'all' | 'waiting' | 'running' | 'attention' | 'completed';
const retryable = (job: OperationsJob) => job.status === 'dead_letter';
const isAttention = (status: string) => ['dead_letter', 'failed'].includes(status);
const isWaiting = (status: string) => ['queued', 'pending', 'retrying'].includes(status);

function readable(iso: string | null | undefined) {
  if (!iso) return 'No check-in yet';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? 'Not available' : date.toLocaleString();
}
function relative(iso: string | null | undefined) {
  if (!iso) return 'No check-in yet';
  const delta = Date.now() - Date.parse(iso);
  if (!Number.isFinite(delta)) return 'Time unavailable';
  if (delta < 0) return readable(iso);
  if (delta < 60_000) return 'Just now';
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`;
  return readable(iso);
}
const statusLabel = (status: string) => status.replaceAll('_', ' ');

export default function Operations() {
  const qc = useQueryClient();
  const { data, error, isLoading, isError, isFetching, dataUpdatedAt } = useQuery({
    queryKey: ['operations'], queryFn: api.operations, refetchInterval: 5000,
  });
  const monitors = useQuery({
    queryKey: ['monitoring-summary'], queryFn: api.monitoringSummary,
    refetchInterval: 10000, retry: false,
  });
  const [filter, setFilter] = useState<QueueFilter>('all');
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [failure, setFailure] = useState('');

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['operations'] });
    void qc.invalidateQueries({ queryKey: ['runs'] });
    void qc.invalidateQueries({ queryKey: ['monitoring-summary'] });
  };
  async function retry(job: OperationsJob) {
    if (!retryable(job)) return;
    const reason = window.prompt('Why should this failed job be retried? Review the previous failure first.');
    if (!reason?.trim()) return;
    setBusy(job.id); setFailure(''); setNotice('');
    try {
      await api.retryDeadLetter(job.run_id, job.id, reason.trim());
      setNotice('The investigation was returned to the queue. The workflow worker will retry it.');
      refresh();
    } catch (e) { setFailure(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(''); }
  }

  const worker = data?.workflow_worker;
  const queue = data?.queue;
  const monitorOnline = monitors.data?.worker_online;
  const monitorUnknown = !monitors.data;
  const workflowOnline = !!worker?.online;
  const bothOnline = workflowOnline && monitorOnline === true;
  const attentionCount = (queue?.failed ?? 0) + (queue?.dead_letter ?? 0);
  const waitingCount = queue?.queued ?? 0;
  const completedCount = queue?.completed ?? 0;
  const runningCount = queue?.running ?? 0;
  const totalCount = waitingCount + runningCount + completedCount + attentionCount;
  const hasIssue = !workflowOnline || monitorOnline === false || attentionCount > 0;
  const healthText = !data ? 'Checking system health' :
    bothOnline && !attentionCount ? 'Your operations are running smoothly' :
    !workflowOnline ? 'Workflow worker needs attention' :
    monitorOnline === false ? 'Monitoring worker is not responding' :
    monitorUnknown ? 'Checking monitoring service' :
    attentionCount ? 'Some investigations need review' : 'Workflow execution is available';
  const jobs = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data?.jobs ?? []).filter(job => {
      const match = filter === 'all' || (filter === 'waiting' && isWaiting(job.status)) ||
        (filter === 'running' && job.status === 'running') ||
        (filter === 'attention' && isAttention(job.status)) ||
        (filter === 'completed' && job.status === 'completed');
      return match && (!q || `${job.task} ${job.id} ${job.run_id} ${job.status}`.toLowerCase().includes(q));
    });
  }, [data?.jobs, filter, search]);
  const filters: { key: QueueFilter; label: string; count?: number }[] = [
    { key: 'all', label: 'All jobs', count: data?.jobs.length },
    { key: 'waiting', label: 'Waiting', count: waitingCount },
    { key: 'running', label: 'In progress', count: runningCount },
    { key: 'attention', label: 'Needs attention', count: attentionCount },
    { key: 'completed', label: 'Completed', count: completedCount },
  ];
  const segments = [
    { key: 'complete', value: completedCount, label: 'Completed' },
    { key: 'active', value: runningCount, label: 'Running' },
    { key: 'pending', value: waitingCount, label: 'Queued' },
    { key: 'failed', value: attentionCount, label: 'Needs attention' },
  ];

  return <div className="page ops-page ops-v2">
    <div className="ops-v2-topline">
      <span className="ops-v2-kicker"><Sparkles size={13} /> SYSTEM OPERATIONS <span className="ops-v2-kicker-dot" /> LIVE WORKSPACE</span>
      <div className="ops-v2-head-actions">
        <span className="ops-v2-updated">{dataUpdatedAt ? `Updated ${new Date(dataUpdatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}` : 'Connecting…'}</span>
        <button type="button" className="btn btn-secondary ops-v2-refresh" onClick={refresh} disabled={isFetching}>
          <RefreshCw size={15} className={isFetching ? 'ops-v2-spinning' : ''} /> Refresh
        </button>
      </div>
    </div>

    <header className="ops-v2-hero">
      <div className="ops-v2-hero-copy">
        <span className="ops-v2-subtitle">OPERATIONS CENTER</span>
        <h1>Keep intelligence<br /><em>moving.</em></h1>
        <p>Follow your investigations, monitor background services, and resolve what needs attention—all in one place.</p>
        <div className="ops-v2-hero-actions">
          <Link className="btn btn-primary" to="/workflows"><Workflow size={16} /> View investigations <ArrowRight size={16} /></Link>
          <Link className="btn ops-v2-ghost" to="/monitoring"><ShieldCheck size={16} /> Manage monitors</Link>
        </div>
      </div>
      <div className={`ops-v2-health ${hasIssue ? 'ops-v2-health-warn' : ''}`} role="status" aria-live="polite">
        <div className="ops-v2-health-icon">{hasIssue ? <AlertTriangle size={30} /> : <HeartPulse size={30} />}</div>
        <span className="ops-v2-health-eyebrow">SYSTEM HEALTH</span>
        <strong>{healthText}</strong>
        <div className="ops-v2-health-row"><span className={`ops-v2-led ${workflowOnline ? 'on' : 'off'}`} /> Workflow engine <b>{workflowOnline ? 'Online' : 'Offline'}</b></div>
        <div className="ops-v2-health-row"><span className={`ops-v2-led ${monitorOnline ? 'on' : 'off'}`} /> Monitoring <b>{monitorUnknown ? 'Unknown' : monitorOnline ? 'Online' : 'Offline'}</b></div>
      </div>
    </header>

    {isLoading && <div className="ops-v2-placeholder"><LoaderCircle size={18} className="ops-v2-spinning" /> Checking your backend services…</div>}
    {isError && <ErrorBox error={error} />}
    {failure && <div className="ops-error" role="alert"><AlertTriangle size={17} />{failure}<button aria-label="Dismiss error" onClick={() => setFailure('')}><X size={15}/></button></div>}
    {notice && <div className="ops-success" role="status"><CheckCircle2 size={17} />{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={15}/></button></div>}
    {data && <>
      <section aria-label="Operations statistics" className="ops-v2-metrics">
        <article className="ops-v2-metric ops-v2-metric-purple"><span className="ops-v2-metric-icon"><Clock3 size={20}/></span><div><span>Waiting in queue</span><strong>{waitingCount}</strong><small>{waitingCount ? 'Ready for background processing' : 'Nothing waiting to be processed'}</small></div><i /></article>
        <article className="ops-v2-metric ops-v2-metric-blue"><span className="ops-v2-metric-icon"><Activity size={20}/></span><div><span>Currently running</span><strong>{runningCount}</strong><small>{runningCount ? 'Investigations in progress' : 'No active investigations'}</small></div><i /></article>
        <article className="ops-v2-metric ops-v2-metric-teal"><span className="ops-v2-metric-icon"><CheckCircle2 size={20}/></span><div><span>Completed jobs</span><strong>{completedCount}</strong><small>Recorded in the workflow queue</small></div><i /></article>
        <article className="ops-v2-metric ops-v2-metric-amber"><span className="ops-v2-metric-icon"><AlertCircle size={20}/></span><div><span>Needs your attention</span><strong>{attentionCount}</strong><small>{attentionCount ? 'Review failed investigations' : 'No reported job failures'}</small></div><i /></article>
      </section>

      {!workflowOnline && waitingCount > 0 && <div className="ops-warning" role="status"><AlertTriangle size={22}/><div><strong>Investigations are waiting for a workflow worker</strong><p>The API is connected, but the background worker is not reporting a heartbeat. Check the managed services for this deployment. No jobs have been retried automatically.</p></div></div>}

      <section className="ops-v2-main-grid">
        <div className="ops-v2-panel ops-v2-services">
          <div className="ops-v2-panel-title"><div><span className="ops-v2-eyebrow">RUNTIME HEALTH</span><h2>Connected services</h2><p>Current status from your backend—not simulated checks.</p></div><span className="ops-v2-live"><span className="ops-v2-led on"/> Live status</span></div>
          <div className="ops-v2-service-list">
            <div className="ops-v2-service"><span className="ops-v2-service-icon purple"><ServerCog size={19}/></span><div><strong>Workflow engine</strong><span>{worker?.active ? 'Processing an investigation' : 'Executes queued business investigations'}</span><small>Last check-in · {relative(worker?.last_seen)}</small></div><span className={`ops-v2-service-state ${workflowOnline ? 'ok' : 'problem'}`}><span className={`ops-v2-led ${workflowOnline ? 'on' : 'off'}`} />{workflowOnline ? 'Healthy' : 'Offline'}</span></div>
            <div className="ops-v2-service"><span className="ops-v2-service-icon teal"><ShieldCheck size={19}/></span><div><strong>Monitoring engine</strong><span>Runs enabled schedules and creates alerts</span><small>Last check-in · {relative(monitors.data?.worker_last_seen)}</small></div><span className={`ops-v2-service-state ${monitorUnknown ? '' : monitorOnline ? 'ok' : 'problem'}`}><span className={`ops-v2-led ${monitorOnline ? 'on' : 'off'}`} />{monitorUnknown ? 'Unknown' : monitorOnline ? 'Healthy' : 'Offline'}</span></div>
            <div className="ops-v2-service"><span className="ops-v2-service-icon blue"><Database size={19}/></span><div><strong>Run storage</strong><span>{data.repository === 'persistent' ? 'Workspace records are stored in a database' : 'Run data may be lost on restart'}</span><small>Execution mode · {data.execution_mode}</small></div><span className={`ops-v2-service-state ${data.repository === 'persistent' ? 'ok' : 'problem'}`}><span className={`ops-v2-led ${data.repository === 'persistent' ? 'on' : 'off'}`} />{data.repository === 'persistent' ? 'Persistent' : 'Temporary'}</span></div>
          </div>
          <div className="ops-v2-service-foot"><span><CircleDot size={14}/> {monitors.data?.enabled_monitors ?? 0} enabled monitors</span><Link to="/monitoring">Manage schedules <ArrowUpRight size={14}/></Link></div>
        </div>
        <div className="ops-v2-panel ops-v2-overview">
          <div className="ops-v2-panel-title"><div><span className="ops-v2-eyebrow">WORKLOAD</span><h2>Execution overview</h2><p>Job distribution across recorded queue states.</p></div><span className="ops-v2-total">{totalCount} total</span></div>
          <div className="ops-v2-overview-display"><div className="ops-v2-ring" style={{ background: totalCount ? `conic-gradient(#36d5b1 0 ${100 * completedCount/totalCount}%, #777af6 ${100 * completedCount/totalCount}% ${100 * (completedCount + runningCount)/totalCount}%, #6baaff ${100 * (completedCount + runningCount)/totalCount}% ${100 * (completedCount + runningCount + waitingCount)/totalCount}%, #f2b26d ${100 * (completedCount + runningCount + waitingCount)/totalCount}% 100%)` : undefined }}><div><strong>{totalCount}</strong><small>Jobs recorded</small></div></div><div className="ops-v2-legend">{segments.map(s => <div key={s.key} className={`ops-v2-legend-${s.key}`}><span><i/>{s.label}</span><b>{s.value}</b></div>)}</div></div>
          <div className="ops-v2-overview-foot"><div><span>Worker readiness</span><strong>{workflowOnline ? (worker?.active ? 'Processing' : 'Ready for work') : 'Requires attention'}</strong></div><Link to="/workflows">Open investigations <ArrowRight size={15}/></Link></div>
        </div>
      </section>

      <section className="ops-v2-panel ops-v2-queue">
        <div className="ops-v2-panel-title ops-v2-queue-head"><div><span className="ops-v2-eyebrow">INVESTIGATION ACTIVITY</span><h2>Workflow queue <span>{data.jobs.length}</span></h2><p>Review recent jobs, inspect results, and retry eligible failures.</p></div><Link to="/workflows" className="ops-v2-link">All investigations <ArrowUpRight size={15}/></Link></div>
        <div className="ops-v2-queue-tools"><div className="ops-v2-tabs" role="group" aria-label="Filter workflow jobs">{filters.map(f => <button type="button" key={f.key} onClick={() => setFilter(f.key)} className={filter === f.key ? 'selected' : ''} aria-pressed={filter === f.key}>{f.label} <span>{f.count ?? 0}</span></button>)}</div><label className="ops-v2-search"><Search size={16}/><span className="ops-v2-sr">Search workflow jobs</span><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Find an investigation…" /></label></div>
        {jobs.length ? <div className="ops-v2-jobs"><div className="ops-v2-job-cols"><span>INVESTIGATION</span><span>STATUS</span><span>ATTEMPTS</span><span>ACTION</span></div>{jobs.map(job => <div className="ops-v2-job" key={job.id}><div className="ops-v2-job-title"><span className={`ops-v2-job-symbol ${isAttention(job.status) ? 'alert' : job.status === 'completed' ? 'complete' : 'default'}`}>{job.status === 'completed' ? <Check size={17}/> : isAttention(job.status) ? <AlertTriangle size={17}/> : job.status === 'running' ? <Play size={17}/> : <Clock3 size={17}/>}</span><div><Link title={job.task} to={`/workflows/${encodeURIComponent(job.run_id)}`}>{job.task}</Link><small>{readable(job.created_at)}{job.error_summary ? ` · ${job.error_summary}` : ''}</small></div></div><span className={`ops-v2-job-badge ${isAttention(job.status) ? 'attention' : job.status === 'completed' ? 'complete' : job.status === 'running' ? 'running' : 'waiting'}`}><span className="ops-v2-led" />{statusLabel(job.status)}</span><span className="ops-v2-job-attempt">{job.attempt_count} / {job.max_attempts}</span><div className="ops-v2-job-actions"><Link title="Open investigation" to={`/workflows/${encodeURIComponent(job.run_id)}`}>View <ArrowUpRight size={14}/></Link>{retryable(job) && <button type="button" disabled={busy === job.id} onClick={() => void retry(job)}>{busy === job.id ? <LoaderCircle className="ops-v2-spinning" size={14}/> : <RotateCcw size={14}/>} Retry</button>}</div></div>)}</div> : <div className="ops-v2-empty"><span><CheckCircle2 size={23}/></span><strong>{search || filter !== 'all' ? 'No matching jobs' : 'Your queue is clear'}</strong><p>{search || filter !== 'all' ? 'Try changing your search or status filter.' : 'New investigations will appear here as soon as they are submitted.'}</p>{(search || filter !== 'all') && <button type="button" onClick={() => {setFilter('all');setSearch('');}}>Clear filters</button>}</div>}
      </section>

      <section className="ops-v2-actions"><div className="ops-v2-actions-head"><div><span className="ops-v2-eyebrow">QUICK ACCESS</span><h2>Manage your workspace</h2></div><span><SlidersHorizontal size={15}/> Safe, governed actions</span></div><div className="ops-v2-action-grid"><Link to="/workflows"><span className="ops-v2-action-icon purple"><Workflow size={21}/></span><strong>Investigations</strong><small>Submit and inspect analyses</small><ArrowUpRight className="ops-v2-action-arrow" size={18}/></Link><Link to="/monitoring"><span className="ops-v2-action-icon teal"><Clock3 size={21}/></span><strong>Scheduled monitoring</strong><small>Manage automated checks</small><ArrowUpRight className="ops-v2-action-arrow" size={18}/></Link><Link to="/data"><span className="ops-v2-action-icon blue"><Database size={21}/></span><strong>Data sources</strong><small>Manage connections</small><ArrowUpRight className="ops-v2-action-arrow" size={18}/></Link><Link to="/usage"><span className="ops-v2-action-icon amber"><ShieldCheck size={21}/></span><strong>AI usage & budget</strong><small>View model costs</small><ArrowUpRight className="ops-v2-action-arrow" size={18}/></Link></div></section>

      <details className="ops-v2-diagnostics"><summary><span><PauseCircle size={16}/> Technical details & deployment guidance</span><ChevronDown size={16}/></summary><div className="ops-v2-diagnostics-body"><div><span>API connection</span><strong>Connected</strong></div><div><span>Storage backend</span><strong>{data.repository}</strong></div><div><span>Workflow execution</span><strong>{data.execution_mode}</strong></div><div><span>Workflow worker check-in</span><strong>{readable(worker?.last_seen)}</strong></div><div><span>Monitoring worker check-in</span><strong>{readable(monitors.data?.worker_last_seen)}</strong></div><p>{data.guidance} In distributed deployments, configure the API and workers as managed services using shared persistent state. These heartbeats are not a distributed health guarantee.</p><p>Infrastructure credentials and arbitrary shell commands are deliberately unavailable from this page. A retry is explicit and may use Hugging Face credits when AI is enabled.</p></div></details>
    </>}
  </div>;
}
