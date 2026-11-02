import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, CirclePause, DatabaseZap, Play, RotateCcw, ShieldCheck, ZapOff } from 'lucide-react';
import { api } from '../api';
import type { RiskScreeningJob } from '../risk-types';
import '../risk-screening.css';

const fmt=(value:number)=>new Intl.NumberFormat('en-IN',{maximumFractionDigits:2}).format(value);
function Status({job}:{job:RiskScreeningJob}) {
  const labels:Record<string,string>={queued:'Waiting for worker',running:'Scanning data',cancel_requested:'Stopping after checkpoint',cancelled:'Cancelled',interrupted:'Interrupted — resumable',failed:'Needs attention',completed:'Screening completed',not_started:'Not started'};
  return <span className={`risk-badge risk-${job.status}`}>{labels[job.status]||job.status}</span>;
}
export default function RiskScreeningPanel({runId}:{runId:string}) {
  const [submitting,setSubmitting]=useState(false),[error,setError]=useState('');
  const scan=useQuery({queryKey:['risk-screen',runId],queryFn:()=>api.riskScan(runId),enabled:!!runId,refetchInterval:2500,retry:false});
  const job=scan.data||{status:'not_started',run_id:runId} as RiskScreeningJob;
  const active=['queued','running','cancel_requested'].includes(job.status);
  const canResume=['cancelled','interrupted','failed'].includes(job.status);
  async function act(action:'start'|'resume'|'cancel'){
    if(!runId)return;setSubmitting(true);setError('');
    try{
      if(action==='start')await api.startRiskScan(runId);
      else if(job.id)await api.riskScanAction(runId,job.id,action);
      await scan.refetch();
    }catch(e){setError(e instanceof Error?e.message:String(e));}finally{setSubmitting(false);}
  }
  const metrics=job.result?.signals;
  return <section className="risk-screening">
    <div className="risk-heading"><div><span className="risk-eyebrow">UPGRADE 14 · PHASE 2</span><h2>Large-Data Risk Screening</h2><p>Disk-backed transaction pattern checks with pause-safe checkpoints. No AI usage.</p></div><Status job={job}/></div>
    <div className="risk-actions">
      <div className="risk-worker"><DatabaseZap size={20}/><span>Background screening</span><small>Managed by your unified local worker stack</small></div>
      <div className="risk-buttons">
        {(!active && !canResume)&&<button className="btn btn-primary" type="button" disabled={!runId||submitting} onClick={()=>void act('start')}><Play size={15}/> {job.status==='completed'?'Run fresh screening':'Start risk screening'}</button>}
        {canResume&&<button className="btn btn-primary" type="button" disabled={submitting} onClick={()=>void act('resume')}><RotateCcw size={15}/> Resume from checkpoint</button>}
        {active&&<button className="btn btn-secondary" type="button" disabled={submitting||job.status==='cancel_requested'} onClick={()=>void act('cancel')}><CirclePause size={15}/> Request cancellation</button>}
      </div>
    </div>
    {active&&<div className="risk-progress" aria-live="polite"><div className="risk-progress-header"><span>Source scan progress (estimated)</span><b>{fmt(job.progress_percent||0)}%</b></div><div className="risk-track"><div style={{width:`${Math.max(0,Math.min(100,job.progress_percent||0))}%`}}/></div><p>{fmt(job.rows_scanned||0)} records scanned · checkpoints every 500 rows · automatic polling</p></div>}
    {error&&<p className="risk-error" role="alert">{error}</p>}{scan.error&&<p className="risk-error" role="alert">Cannot load screening status: {String(scan.error)}</p>}
    {job.error&&<p className="risk-error"><AlertTriangle size={16}/>{job.error}</p>}
    {job.result&&<><div className="risk-result-header"><CheckCircle2 size={19}/><div><strong>Evidence-backed screening completed</strong><p>{fmt(job.result.metrics.rows_scanned)} records · {fmt(job.result.metrics.invalid_amount_rows)} invalid amounts skipped · no model calls</p></div></div>
      <div className="risk-cards">{[
        ['High-value outliers',metrics?.unusually_high_amount_transactions||0],
        ['Repeated pattern groups',metrics?.repeated_transaction_pattern_groups||0],
        ['Repeated invoice IDs',metrics?.repeated_invoice_identifier_groups||0],
        ['Possible split groups',metrics?.possible_split_pattern_groups||0],
      ].map(([title,value])=><article key={title}><small>{title}</small><strong>{fmt(Number(value))}</strong></article>)}</div>
      <div className="risk-evidence"><ShieldCheck size={18}/><div><b>Independent reconciliation</b><p>{job.result.verification}</p><p>Upper IQR threshold: {job.result.thresholds.amount_iqr_upper_source_units===null?'Insufficient data':fmt(job.result.thresholds.amount_iqr_upper_source_units)} source units</p></div></div>
      <details className="risk-limitations"><summary>Screening scope and limitations</summary><ul>{job.result.limitations.map(item=><li key={item}>{item}</li>)}</ul></details>
    </>}
    {!job.result&&<div className="risk-empty"><ZapOff size={16}/><span>Only screening evidence is produced here; this does not replace your full six-agent investigation or assert fraud.</span></div>}
  </section>;
}
