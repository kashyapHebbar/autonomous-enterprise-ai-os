import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { AlertTriangle, ArrowRight, BrainCircuit, CheckCircle2, Database, Lightbulb, ShieldCheck, TrendingUp } from 'lucide-react';
import { api } from '../api';
import { Empty, ErrorBox, Loading, Panel, formatNumber } from './Ui';

const currencySymbols: Record<string, string> = {USD:'$',EUR:'€',INR:'₹',GBP:'£',JPY:'¥'};
function money(value:number|undefined, code:string|null){
  if(value===undefined)return '—';
  const symbol=currencySymbols[code||'']||`${code||'units'} `;
  return `${symbol}${formatNumber(value,2)}`;
}
function figure(value:number|undefined, name:string, currency:string|null){
  return value===undefined?'—':['total_spend','estimated_savings'].includes(name)?money(value,currency):formatNumber(value,name==='completeness'?2:0);
}
const categories: Array<{key:'insights'|'recommendations'|'opportunities',label:string}>=[
  {key:'insights',label:'Key findings'},{key:'recommendations',label:'Next actions'},{key:'opportunities',label:'Opportunities'},
];
export default function IntelligenceOverview(){
  const overview=useQuery({queryKey:['intelligence-overview'],queryFn:api.intelligenceOverview,refetchInterval:30000});
  const health=useQuery({queryKey:['workspace-health'],queryFn:api.workspaceHealth,refetchInterval:30000});
  const [selected,setSelected]=useState('');
  const [category,setCategory]=useState<'insights'|'recommendations'|'opportunities'>('insights');
  const analyses=overview.data?.analyses??[];
  const current=analyses.find(run=>run.run_id===selected)||analyses[0];
  const figures:Record<string,number>=current?.figures??{};
  const cards: Array<{key:string,label:string,icon:typeof TrendingUp}> = current?.analysis_type==='procurement' ? [
    {key:'total_spend',label:'Verified spending',icon:TrendingUp},
    {key:'anomaly_count',label:'Flagged transactions',icon:AlertTriangle},
    {key:'estimated_savings',label:'Estimated opportunities',icon:Lightbulb},
    {key:'supplier_count',label:'Suppliers analyzed',icon:Database},
  ] : [
    {key:'row_count',label:'Rows analyzed',icon:Database},
    {key:'outlier_count',label:'Unusual values',icon:AlertTriangle},
    {key:'duplicate_row_count',label:'Duplicate rows',icon:ShieldCheck},
  ];
  return <section className="ux11-intelligence" aria-label="Saved business intelligence">
    <div className="ux11-section-top"><div><span className="eyebrow"><BrainCircuit size={14}/> WORKSPACE INTELLIGENCE</span><h2>What your investigations discovered</h2><p>Real findings from completed analyses. Nothing here makes a new AI request.</p></div>
      <Link to="/visualizations" className="text-action">Explore visualizations <ArrowRight size={15}/></Link></div>
    {overview.isLoading?<Loading label="Reading saved intelligence…"/>:overview.isError?<ErrorBox error={overview.error}/>:!current?<Empty title="Your intelligence snapshot will appear here" description="Complete an investigation to reveal evidence-backed figures, trends and recommendations on your home page."/>:<>
      <div className="ux11-source-row"><label htmlFor="ux11-investigation">Showing findings from</label><select id="ux11-investigation" value={current.run_id} onChange={event=>setSelected(event.target.value)}>
        {analyses.map(run=><option key={run.run_id} value={run.run_id}>{run.task.slice(0,90)}</option>)}
      </select><Link to={`/workflows/${encodeURIComponent(current.run_id)}`}>Open full evidence <ArrowRight size={14}/></Link></div>
      <div className="ux11-kpis">{cards.map(({key,label,icon:Icon})=><div className="ux11-kpi" key={key}><div className="ux11-kpi-label"><Icon size={16}/>{label}</div><strong>{figure(figures[key],key,current.currency)}</strong><small>{key==='estimated_savings'?'Indicative, not realized savings':'From this completed analysis only'}</small></div>)}</div>
      <div className="ux11-grid"><Panel title="Trend in the selected analysis" description="Historical values from verified calculations, not forecasts">
        {current.trend.length>1?<div className="ux11-chart" aria-label="Recorded trend"><ResponsiveContainer width="100%" height="100%"><AreaChart data={current.trend} margin={{top:10,right:15,bottom:0,left:0}}><defs><linearGradient id="ux11-intelligence-area" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#9585fb" stopOpacity={0.3}/><stop offset="100%" stopColor="#9585fb" stopOpacity={0}/></linearGradient></defs><CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeDasharray="4 7"/><XAxis dataKey="label" tickLine={false} axisLine={false} tick={{fill:'var(--text-muted)',fontSize:10}}/><YAxis tickLine={false} axisLine={false} tick={{fill:'var(--text-muted)',fontSize:10}} tickFormatter={v=>Number(v).toLocaleString('en-US',{notation:'compact'})}/><Tooltip contentStyle={{background:'var(--tooltip-bg)',border:'1px solid var(--border)',borderRadius:12,color:'var(--text)'}} formatter={value=>money(Number(value),current.currency)}/><Area dataKey="value" type="monotone" stroke="#968dff" strokeWidth={2.5} fill="url(#ux11-intelligence-area)"/></AreaChart></ResponsiveContainer></div>:<div className="ux11-empty-mini">No comparable time periods were calculated for this investigation.</div>}
      </Panel><Panel title="Findings & recommendations" description="Only results supported by saved evidence">
        <div className="ux11-tabs" role="group" aria-label="Business insight category">{categories.map(tab=><button key={tab.key} className={tab.key===category?'active':''} type="button" aria-pressed={tab.key===category} onClick={()=>setCategory(tab.key)}>{tab.label}</button>)}</div>
        <div className="ux11-findings">{category==='opportunities'?current.opportunities.length?current.opportunities.map((item,index)=><div key={index} className="ux11-finding"><Lightbulb size={17}/><span>{item.description||'Estimated potential savings'}{item.estimated_savings!=null&&<strong>{money(item.estimated_savings,current.currency)}</strong>}</span></div>):<div className="ux11-empty-mini">No separate savings opportunities are recorded for this run.</div>:(current[category] as string[]).length?(current[category] as string[]).map((value,index)=><div className="ux11-finding" key={index}><CheckCircle2 size={17}/><span>{value}</span></div>):<div className="ux11-empty-mini">No {category==='recommendations'?'recommended actions':'narrative findings'} were saved with this analysis.</div>}</div>
      </Panel></div>
    </>}
    {health.isError?<ErrorBox error={health.error}/>:health.data&&<div className={`ux11-storage ${health.data.persistent_runs?'ux11-storage-good':'ux11-storage-warn'}`}><div><Database size={17}/><strong>{health.data.persistent_runs?'Saved across restarts':'Temporary investigation storage'}</strong><span>{health.data.persistent_runs?'Database-backed workspace is active.':'This backend currently stores runs in memory. Enable persistent local storage to retain them after restart.'}</span></div><span>{health.data.stale_runs.length>0?`${health.data.stale_runs.length} stale run(s) to review`:'No stale executions detected'}</span></div>}
    {overview.data&&<p className="ux11-disclaimer">{overview.data.note}</p>}
  </section>;
}
