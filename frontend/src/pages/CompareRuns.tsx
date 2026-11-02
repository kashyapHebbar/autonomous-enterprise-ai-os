import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, GitCompareArrows, Info, ShieldCheck, TrendingDown, TrendingUp } from 'lucide-react';
import { api } from '../api';
import { Empty, ErrorBox, Loading, PageHeader, Panel, formatNumber, nice } from '../components/Ui';
import type { Analysis } from '../types';

const safeNum=(x:unknown):number|null=>typeof x==='number'&&Number.isFinite(x)?x:null;
export default function CompareRuns(){
  const runsQ=useQuery({queryKey:['runs'],queryFn:api.runs});const completed=useMemo(()=>[...(runsQ.data||[])].filter(r=>r.status==='completed').sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at)),[runsQ.data]);
  const [leftId,setLeft]=useState(''),[rightId,setRight]=useState('');
  const left=leftId||completed[0]?.id||'';const right=rightId||completed.find(r=>r.id!==left)?.id||'';
  const la=useQuery({queryKey:['artifacts',left],queryFn:()=>api.artifacts(left),enabled:Boolean(left)});
  const ra=useQuery({queryKey:['artifacts',right],queryFn:()=>api.artifacts(right),enabled:Boolean(right)});
  const lKpi=la.data?.find(a=>a.type==='kpi_table');const rKpi=ra.data?.find(a=>a.type==='kpi_table');
  const lv=useQuery({queryKey:['compare-content',left,lKpi?.id],queryFn:()=>api.artifactContent(left,lKpi!.id),enabled:Boolean(left&&lKpi)});
  const rv=useQuery({queryKey:['compare-content',right,rKpi?.id],queryFn:()=>api.artifactContent(right,rKpi!.id),enabled:Boolean(right&&rKpi)});
  const metricsLeft:Record<string,number|null>=(lv.data as Analysis|undefined)?.kpis||{};const metricsRight:Record<string,number|null>=(rv.data as Analysis|undefined)?.kpis||{};
  const metricKeys=Object.keys(metricsLeft).filter(k=>safeNum(metricsLeft[k])!==null&&safeNum(metricsRight[k])!==null).slice(0,24);
  const consistentType=(lv.data as Analysis|undefined)?.analysis_type===(rv.data as Analysis|undefined)?.analysis_type;
  const idsMatch=left===right;
  const lRun=completed.find(r=>r.id===left),rRun=completed.find(r=>r.id===right);
  return <div className="page ux-compare-page"><PageHeader eyebrow="UNDERSTAND WHAT CHANGED" title="Compare analyses" description="Compare previously saved, Python-calculated figures side by side. No model calls, no new calculations on source data."/>
    {runsQ.isLoading?<Loading/>:runsQ.isError?<ErrorBox error={runsQ.error}/>:completed.length<2?<Empty title="You need two completed analyses" description="Run at least two investigations to compare their saved findings. Different datasets may not be directly comparable." action={<Link to="/workflows" className="btn btn-primary">Explore investigations <ArrowRight size={15}/></Link>}/>:<>
      <div className="ux-compare-choices"><label><span>FIRST ANALYSIS</span><select value={left} onChange={e=>setLeft(e.target.value)}>{completed.map(r=><option value={r.id} key={r.id}>{r.task.slice(0,84)}</option>)}</select><small>{lRun&&new Date(lRun.created_at).toLocaleString()}</small></label><div className="ux-compare-vs"><GitCompareArrows size={21}/><span>VS</span></div><label><span>SECOND ANALYSIS</span><select value={right} onChange={e=>setRight(e.target.value)}>{completed.map(r=><option value={r.id} key={r.id}>{r.task.slice(0,84)}</option>)}</select><small>{rRun&&new Date(rRun.created_at).toLocaleString()}</small></label></div>
      {idsMatch?<div className="inline-notice"><Info size={17}/> Choose two different completed workflows to see a comparison.</div>:la.isLoading||ra.isLoading||lv.isLoading||rv.isLoading?<Loading label="Loading saved analytical figures…"/>:la.isError||ra.isError||lv.isError||rv.isError?<ErrorBox error={la.error||ra.error||lv.error||rv.error}/>:<>
        {!consistentType&&<div className="inline-notice"><Info size={17}/> These workflows use different analysis types. Interpret shared metric names cautiously and confirm units and scope before drawing conclusions.</div>}
        {metricKeys.length?<Panel title="Verified figures — side by side" description="Values come directly from each completed workflow's original KPI artifact. Changes are arithmetic comparisons of saved metrics."><div className="ux-compare-header"><span>MEASURE</span><span>FIRST</span><span>SECOND</span><span>CHANGE</span></div><div className="ux-compare-rows">{metricKeys.map(key=>{const a=safeNum(metricsLeft[key])!,b=safeNum(metricsRight[key])!,delta=b-a;const relative=a!==0?100*delta/Math.abs(a):null;return <div key={key} className="ux-compare-row"><strong>{nice(key)}</strong><span>{formatNumber(a,3)}</span><span>{formatNumber(b,3)}</span><span className={delta>0?'ux-compare-up':delta<0?'ux-compare-down':''}>{delta>0?<TrendingUp size={14}/>:delta<0?<TrendingDown size={14}/>:null}{delta>0?'+':''}{formatNumber(delta,3)}{relative!==null&&<small> ({relative>0?'+':''}{formatNumber(relative,1)}%)</small>}</span></div>})}</div><div className="ux-compare-footer"><ShieldCheck size={15}/> Changes are descriptive, not necessarily performance improvements. Check dates, filters, currencies and source scope before comparing business impact.</div></Panel>:<Empty title="No matching numerical measures" description="The selected runs don't share saved KPI keys with numerical values. Compare their individual results instead."/>}
        <div className="ux-comparison-links"><Link className="btn btn-secondary" to={`/workflows/${encodeURIComponent(left)}`}>First analysis <ArrowRight size={15}/></Link><Link className="btn btn-secondary" to={`/workflows/${encodeURIComponent(right)}`}>Second analysis <ArrowRight size={15}/></Link></div>
      </>}
    </>}
  </div>;
}
