import RiskScreeningPanel from '../components/RiskScreeningPanel';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Activity, ArrowRight, ChartNoAxesCombined, Database, Download, Gauge, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { api } from '../api';
import { ErrorBox, Empty, PageHeader } from '../components/Ui';
import type { ScalableSummary, ScalableGroup } from '../scaling-types';
import '../scalable.css';

const fmt = (n:number) => new Intl.NumberFormat('en-IN',{maximumFractionDigits:2}).format(n);
const money = (n:number) => fmt(n);
function Ranked({title,groups}:{title:string;groups:ScalableGroup}) {
  const max = Math.max(...groups.items.map(x=>Math.max(x.spend,0)),1);
  return <section className="scale-panel"><div className="scale-panel-heading"><div><h2>{title}</h2><p>{groups.groups_shown} visible groups · {groups.groups_suppressed} small groups suppressed</p></div></div>
    {groups.items.length?<div className="scale-bars">{groups.items.slice(0,10).map(x=><div className="scale-bar" key={x.name}><div className="scale-bar-label"><strong title={x.name}>{x.name}</strong><span>{money(x.spend)} · {x.transactions} transactions</span></div><div className="scale-track"><div style={{width:`${Math.max(0,Math.min(100,x.spend/max*100))}%`}}/></div></div>)}</div>:<p className="scale-muted">No eligible grouped figures to display.</p>}
    <p className="scale-footnote">Not all groups appear. Headline total includes the complete scanned file.</p>
  </section>;
}
function Trend({months}:{months:ScalableSummary['monthly_spend']}) {
  const view=months.slice(-30), max=Math.max(...view.map(x=>x.spend),1), w=560,h=180;
  const points=view.map((x,i)=>`${20+(i/Math.max(1,view.length-1))*(w-40)},${h-20-Math.max(0,x.spend)/max*(h-50)}`).join(' ');
  return <section className="scale-panel"><div className="scale-panel-heading"><div><h2>Spending over time</h2><p>Recorded transaction months · no forecast or inferred values</p></div></div>
    {view.length>1?<><svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Monthly spend trend" className="scale-trend"><defs><linearGradient id="scaleAreaFill" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#877af5" stopOpacity=".35"/><stop offset="1" stopColor="#877af5" stopOpacity="0"/></linearGradient></defs><path d={`M ${points.replaceAll(' ', ' L ')} L ${w-20},${h-20} L 20,${h-20} Z`} fill="url(#scaleAreaFill)"/><polyline points={points} stroke="#9d90ff" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round"/></svg><div className="scale-trend-labels"><span>{view[0].month}</span><span>{view[view.length-1].month}</span></div></>:<p className="scale-muted">The source needs at least two valid months for a time series.</p>}
  </section>;
}
function csvValue(v:unknown) {let text=String(v??'');if(typeof v!=='number' && /^[\s]*[=+@\-]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';}
function exportCSV(result:ScalableSummary) {
  const lines=[['section','name','spend','transactions'], ...result.suppliers.items.map(x=>['supplier',x.name,x.spend,x.transactions]),...result.categories.items.map(x=>['category',x.name,x.spend,x.transactions]),...result.monthly_spend.map(x=>['month',x.month,x.spend,''])];
  const csv=lines.map(row=>row.map(csvValue).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='streaming-financial-overview.csv';a.click();URL.revokeObjectURL(url);
}
export default function ScalableData(){
  const runs=useQuery({queryKey:['runs'],queryFn:api.runs});
  const [id,setId]=useState(''),[busy,setBusy]=useState(false),[result,setResult]=useState<ScalableSummary|null>(null),[error,setError]=useState('');
  const eligible=useMemo(()=>runs.data?.filter(r=>!!r.dataset_artifact_id)||[],[runs.data]);
  const selected=id||(eligible[0]?.id||'');
  async function selectRun(runId:string){setId(runId);setResult(null);setError('');if(!runId)return;try{const saved=await api.scalableSummary(runId);if(saved.status==='completed')setResult(saved);}catch{/* A missing previous scan is not an error */}}
  async function scan(){if(!selected)return;setBusy(true);setError('');try{const output=await api.computeScalableSummary(selected);setResult(output);}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  return <div className="page scale-page">
    <PageHeader eyebrow="LARGE DATA LAB / STREAMING" title="Big Data Explorer" description="Analyze complete CSV spending totals without loading every transaction into memory or calling an AI model." action={<Link className="btn btn-secondary" to="/operations"><Activity size={15}/> Operations <ArrowRight size={14}/></Link>}/>
    <section className="scale-hero"><div className="scale-hero-text"><div className="scale-overline"><Sparkles size={14}/> STREAMING ANALYTICS</div><h2>Big datasets.<br/><em>Verified answers.</em></h2><p>Start with exact spending aggregates and monthly trends. We never present skipped anomaly or invoice checks as successful investigations.</p><div className="scale-hero-features"><span><ShieldCheck size={15}/> Financially reconciled</span><span><Database size={15}/> Full-file scan</span><span><Gauge size={15}/> Zero model requests</span></div></div><div className="scale-hero-visual"><Database size={62} strokeWidth={1.15}/><span>CSV → Streaming → Verified totals</span></div></section>
    <section className="scale-run-select"><label htmlFor="scalable-run">SOURCE INVESTIGATION <select id="scalable-run" value={selected} onChange={e=>void selectRun(e.target.value)}><option value="" disabled>Select a saved investigation</option>{eligible.map(r=><option key={r.id} value={r.id}>{r.task.slice(0,110)}</option>)}</select></label><button type="button" className="btn btn-primary" disabled={!selected||busy} onClick={()=>void scan()}>{busy?<RefreshCw className="spin" size={16}/>:<ChartNoAxesCombined size={16}/>} {busy?'Scanning complete file…':'Calculate financial overview'}</button></section>
    <div className="scale-note"><ShieldCheck size={18}/><p><strong>Scope: full-source financial aggregation only.</strong> This is not a substitute for the six-agent investigation. It does not run anomaly detection, supplier-risk scoring, duplicate invoice matching, or savings estimation. All scans are explicit and read-only.</p></div>
    {selected&&<RiskScreeningPanel runId={selected}/>}
    {error&&<ErrorBox error={new Error(error)}/>}
    {!result?<Empty title="No large-data overview yet" description="Choose an investigation with a local procurement CSV, then calculate spending totals. This works independently of AI credits."/>:<>
      <div className="scale-result-heading"><div><span>VERIFIED OUTPUT</span><h2>Financial overview</h2><p>{fmt(result.metrics.rows_scanned)} rows scanned in {result.duration_seconds}s · exact source-to-group reconciliation</p></div><button className="btn btn-secondary" onClick={()=>exportCSV(result)}><Download size={15}/> Export aggregate CSV</button></div>
      <div className="scale-metrics">{[
        ['Total recorded spending (source units)',money(result.metrics.total_spend)],
        ['Rows scanned',fmt(result.metrics.rows_scanned)],
        ['Valid amounts',fmt(result.metrics.valid_amount_rows)],
        ['Supplier groups',fmt(result.metrics.supplier_count)],
        ['Categories',fmt(result.metrics.category_count)],
        ['Invalid/missing amounts',fmt(result.metrics.invalid_amount_rows)],
      ].map(([name,value])=><article key={name}><span>{name}</span><strong>{value}</strong></article>)}</div>
      <div className="scale-grid"><Ranked title="Top supplier spending" groups={result.suppliers}/><Ranked title="Spending by category" groups={result.categories}/><Trend months={result.monthly_spend}/><section className="scale-panel"><div className="scale-panel-heading"><div><h2>Calculation coverage</h2><p>Exactly what was and wasn't evaluated</p></div></div><div className="scale-verification"><ShieldCheck size={18}/><span>{result.verification}</span></div><ul className="scale-limitations">{result.data_limitations.map(item=><li key={item}>{item}</li>)}</ul><p className="scale-footnote">File stability checked before and after scanning. Invalid amounts are excluded from spending totals.</p></section></div>
    </>}
  </div>;
}
