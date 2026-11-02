import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, BellRing, CheckCircle2, CircleAlert, Clock3, Database, Play, Plus, RefreshCw, ShieldCheck, Pause, Eye } from 'lucide-react';
import { api } from '../api';
import { ErrorBox, PageHeader, Panel } from '../components/Ui';
import '../monitoring.css';

const blank={name:'',task:'Monitor procurement activity and investigate risks using validated calculations.',source_id:'',interval:'daily',only_on_change:true,anomaly_limit:1,spend_change_pct:20,minimum_completeness:0.95};
export default function Monitoring(){
  const qc=useQueryClient();
  const summary=useQuery({queryKey:['monitoring-summary'],queryFn:api.monitoringSummary,refetchInterval:20000});
  const monitorQuery=useQuery({queryKey:['monitoring-monitors'],queryFn:api.monitors,refetchInterval:20000});
  const alertQuery=useQuery({queryKey:['monitoring-alerts'],queryFn:api.monitorAlerts,refetchInterval:20000});
  const sources=useQuery({queryKey:['data-sources'],queryFn:api.dataSources});
  const [draft,setDraft]=useState({...blank,ai_escalation:false});const [showForm,setShowForm]=useState(false);const [busy,setBusy]=useState('');const [notice,setNotice]=useState('');const [error,setError]=useState('');
  const [selected,setSelected]=useState('');const [filter,setFilter]=useState('open');
  const history=useQuery({queryKey:['monitoring-history',selected],queryFn:()=>api.monitorHistory(selected),enabled:!!selected,refetchInterval:20000});
  const localSources=(sources.data??[]).filter(s=>s.source_type==='local_file'&&/\.(csv|tsv)$/i.test(s.dataset_uri));
  const visibleAlerts=useMemo(()=> (alertQuery.data??[]).filter(a=>filter==='all'||a.status===filter),[alertQuery.data,filter]);
  const refresh=()=>{void qc.invalidateQueries({queryKey:['monitoring-summary']});void qc.invalidateQueries({queryKey:['monitoring-monitors']});void qc.invalidateQueries({queryKey:['monitoring-alerts']});void qc.invalidateQueries({queryKey:['monitoring-history']});};
  async function mutate(id:string,operation:()=>Promise<unknown>){setBusy(id);setError('');setNotice('');try{await operation();setNotice('Updated successfully.');refresh();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy('');}}
  async function create(){await mutate('create',async()=>{const next=await api.createMonitor(draft);setShowForm(false);setDraft({...blank,ai_escalation:false});setSelected(next.id);setNotice('Monitor created paused. Enable it when ready.');});}
  const stat=summary.data;
  return <div className="page monitor-page">
    <PageHeader eyebrow="AUTONOMOUS INTELLIGENCE" title="Intelligence Monitoring" description="Schedule governed checks, detect meaningful changes, and review alerts. New monitors are paused until you enable them." action={<button className="btn btn-primary" onClick={()=>setShowForm(v=>!v)}><Plus size={16}/> New monitor</button>}/>
    <div className="monitor-stat-grid">
      <div className="monitor-stat"><Activity size={19}/><span>Monitors</span><strong>{stat?.monitor_count??'—'}</strong><small>{stat?.enabled_monitors??0} enabled</small></div>
      <div className="monitor-stat"><BellRing size={19}/><span>Open alerts</span><strong>{stat?.open_alerts??'—'}</strong><small>{stat?.critical_alerts??0} high priority</small></div>
      <div className="monitor-stat"><Clock3 size={19}/><span>Scheduler</span><strong className="monitor-worker-state">{stat?.worker_online?'Online':'Offline'}</strong><small>{stat?.worker_last_seen?`Last check-in ${new Date(stat.worker_last_seen).toLocaleString()}`:'Managed monitoring worker is offline. Check Operations Center'}</small></div>
      <div className="monitor-stat"><ShieldCheck size={19}/><span>AI spending</span><strong>Protected</strong><small>Scheduled AI is off; no automatic HF calls</small></div>
    </div>
    <div className="monitor-explain"><CircleAlert size={19}/><div><strong>Monitoring is managed by the backend.</strong><p>It checks registered local CSV/TSV or allowlisted S3 sources, executes scheduled Python analysis, and writes alerts to your local database. Source checks and dashboard browsing use no Hugging Face credits. SQLite and Snowflake remain available through existing manual read-only connectors. S3 scheduling requires a bucket allowlist and IAM read permission.</p><code>Operations Center → Worker status</code></div></div>
    {error&&<ErrorBox error={error}/>}{notice&&<p className="monitor-notice" role="status">{notice}</p>}
    {showForm&&<Panel title="Create a scheduled investigation" description="Starts paused. Choose a previously registered local dataset."><div className="monitor-form">
      <label>Monitor name<input value={draft.name} maxLength={100} placeholder="Weekly procurement review" onChange={e=>setDraft({...draft,name:e.target.value})}/></label>
      <label>Registered data source<select value={draft.source_id} onChange={e=>setDraft({...draft,source_id:e.target.value})}><option value="">Choose a local CSV/TSV dataset</option>{localSources.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
      {!localSources.length&&<small>No registered CSV source found. <Link to="/data">Register one in Data Sources</Link>, or enter an allowlisted S3 path below.</small>}
      <label className="monitor-wide">Or enter an allowlisted S3 CSV/TSV path<input value={draft.source_id.startsWith("s3://")?draft.source_id:""} placeholder="s3://approved-bucket/path/data.csv" onChange={e=>setDraft({...draft,source_id:e.target.value})}/></label>
      <label className="monitor-wide">Business objective<textarea rows={3} value={draft.task} maxLength={1500} onChange={e=>setDraft({...draft,task:e.target.value})}/></label>
      <label>Frequency<select value={draft.interval} onChange={e=>setDraft({...draft,interval:e.target.value})}><option value="hourly">Every hour</option><option value="daily">Every day</option><option value="weekly">Every week</option></select></label>
      <label>Alert when anomaly count reaches<input type="number" min={1} max={100000} value={draft.anomaly_limit} onChange={e=>setDraft({...draft,anomaly_limit:Number(e.target.value)})}/></label>
      <label>Alert on spending change (%)<input type="number" min={1} max={500} value={draft.spend_change_pct} onChange={e=>setDraft({...draft,spend_change_pct:Number(e.target.value)})}/></label>
      <label>Minimum data completeness (0–1)<input type="number" min={0} max={1} step={0.05} value={draft.minimum_completeness} onChange={e=>setDraft({...draft,minimum_completeness:Number(e.target.value)})}/></label>
      <label className="monitor-checkbox"><input type="checkbox" checked={draft.ai_escalation} onChange={e=>setDraft({...draft,ai_escalation:e.target.checked})} disabled={!stat?.auto_ai_enabled}/> Optional AI alert explanation (billed; only after a threshold is crossed)</label>
      <label className="monitor-checkbox"><input type="checkbox" checked={draft.only_on_change} onChange={e=>setDraft({...draft,only_on_change:e.target.checked})}/> Skip unchanged files</label>
      <div className="monitor-form-actions"><button className="btn" onClick={()=>setShowForm(false)}>Cancel</button><button className="btn btn-primary" disabled={busy==='create'||!draft.name.trim()||!draft.source_id} onClick={()=>void create()}>Save monitor (paused)</button></div>
    </div></Panel>}
    <Panel title="Scheduled monitors" description="Enable a monitor when you're ready; Run check queues a background task for the managed worker" action={<button className="btn" onClick={refresh}><RefreshCw size={14}/> Refresh</button>}>
      {monitorQuery.isError&&<ErrorBox error={monitorQuery.error}/>}
      {(monitorQuery.data??[]).length===0?<div className="monitor-empty"><Database size={27}/><strong>No monitors yet</strong><p>Choose a saved dataset and schedule recurring investigation checks.</p></div>:<div className="monitor-list">{(monitorQuery.data??[]).map(m=><div key={m.id} className="monitor-row"><div className="monitor-row-head"><strong>{m.name}</strong><span className={`monitor-state ${m.enabled?'monitor-state-on':''}`}>{m.enabled?'Enabled':'Paused'}</span></div><p>{m.task}</p><div className="monitor-details"><span>Every {m.interval==='hourly'?'hour':m.interval==='daily'?'day':'week'}</span><span>Source: {m.source_id}</span><span>Next check: {m.enabled?new Date(m.next_due_at).toLocaleString():'Paused'}</span></div><div className="monitor-actions"><button disabled={busy===m.id} onClick={()=>void mutate(m.id,()=>api.enableMonitor(m.id,!m.enabled))}>{m.enabled?<Pause size={14}/>:<Play size={14}/>} {m.enabled?'Pause':'Enable'}</button><button disabled={!m.enabled||busy===m.id} onClick={()=>void mutate(m.id,()=>api.runMonitor(m.id))}><Play size={14}/> Run check</button><button onClick={()=>setSelected(m.id)}><Eye size={14}/> History</button></div></div>)}</div>}
      {selected&&<div className="monitor-history"><h3>Execution history</h3>{history.isLoading?<p>Loading…</p>:(history.data??[]).length?(history.data??[]).map(item=><div key={item.id} className="monitor-history-row"><span>{new Date(item.started_at).toLocaleString()}</span><strong>{item.status}</strong>{item.ai_review?.status==='created'&&<div className="monitor-ai-review"><strong>Optional AI interpretation</strong><p>{item.ai_review.interpretation}</p><p>{item.ai_review.recommended_next_step}</p></div>}{item.run_id?<Link to={`/workflows/${encodeURIComponent(item.run_id)}`}>Open analysis</Link>:<span>{item.error||'No new data'}</span>}</div>):<p>No checks recorded for this monitor.</p>}</div>}
    </Panel>
    <Panel title="Alert Center" description="Evidence-backed alerts requiring your review. No automatic accusations or business actions." action={<select aria-label="Filter alerts" value={filter} onChange={e=>setFilter(e.target.value)}><option value="open">Open</option><option value="acknowledged">Acknowledged</option><option value="resolved">Resolved</option><option value="all">All alerts</option></select>}>
      {alertQuery.isError&&<ErrorBox error={alertQuery.error}/>}
      {!visibleAlerts.length?<div className="monitor-empty"><CheckCircle2 size={26}/><strong>No matching alerts</strong><p>Alerts appear when a scheduled check crosses one of your configured thresholds.</p></div>:<div className="monitor-alerts">{visibleAlerts.map(a=><div key={a.id} className="monitor-alert"><span className={`monitor-severity monitor-severity-${a.severity}`}>{a.severity} priority</span><strong>{a.title}</strong><p>{a.description}</p><small>{new Date(a.created_at).toLocaleString()} · {a.status}</small><div className="monitor-actions">{a.run_id&&<Link to={`/workflows/${encodeURIComponent(a.run_id)}`}>View investigation</Link>}{a.status==='open'&&<button disabled={busy===a.id} onClick={()=>void mutate(a.id,()=>api.updateMonitorAlert(a.id,'acknowledged'))}>Acknowledge</button>}{a.status!=='resolved'&&<button disabled={busy===a.id} onClick={()=>void mutate(a.id,()=>api.updateMonitorAlert(a.id,'resolved'))}>Resolve</button>}</div></div>)}</div>}
    </Panel>
  </div>;
}
