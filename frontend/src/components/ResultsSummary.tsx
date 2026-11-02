import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, BarChart3, CheckCircle2, ClipboardCheck, FileText, ShieldAlert, Sparkles } from 'lucide-react';
import { api } from '../api';
import { artifactTitle } from '../lib/artifactGroups';
import { formatNumber, nice } from './Ui';
import type { Analysis, Artifact, Evaluation } from '../types';
const preferred=['total_spend','transaction_count','supplier_count','anomaly_count','row_count','completeness','estimated_savings','outlier_count'];
export default function ResultsSummary({runId,artifacts,evaluations,onOutputs}: {runId:string;artifacts:Artifact[];evaluations:Evaluation[];onOutputs:()=>void}){
  const kpi=artifacts.find(a=>a.type==='kpi_table');
  const content=useQuery({queryKey:['result-summary',runId,kpi?.id],queryFn:()=>api.artifactContent(runId,kpi!.id),enabled:Boolean(kpi),staleTime:60000});
  const result=content.data as Analysis|undefined;
  const values=Object.entries(result?.kpis||{}).filter(([,v])=>typeof v==='number'&&Number.isFinite(v)).sort((a,b)=>{const ia=preferred.indexOf(a[0]),ib=preferred.indexOf(b[0]);return (ia<0?99:ia)-(ib<0?99:ib);}).slice(0,4);
  const insights=(result?.insights||[]).filter(x=>typeof x==='string'&&x.trim()).slice(0,3);
  const reports=artifacts.filter(a=>a.type==='report'||a.type==='dashboard');const passed=evaluations.filter(e=>e.passed).length;
  return <section className="ux-results-summary"><div className="ux-result-head"><div><span className="eyebrow">YOUR ANALYSIS, EXPLAINED</span><h2>Investigation overview</h2><p>Start with the verified facts, then explore the reports and supporting evidence.</p></div><button type="button" className="btn btn-secondary" onClick={onOutputs}><FileText size={16}/> View all results <ArrowRight size={15}/></button></div>
  {values.length>0&&<div className="ux-result-kpis">{values.map(([k,v])=><div key={k}><span>{nice(k)}</span><strong>{k==='completeness'&&typeof v==='number'?`${formatNumber(v*100,1)}%`:formatNumber(v as number,2)}</strong><small>Verified analysis</small></div>)}</div>}
  <div className="ux-result-feature-grid"><div className="ux-result-feature"><div className="ux-result-feature-title"><Sparkles size={17}/><strong>Key findings</strong></div>{content.isLoading?<p>Reading saved insights…</p>:content.isError?<p>Insights unavailable. Open the original report to review findings.</p>:insights.length?<ol>{insights.map((text,i)=><li key={i}>{text}</li>)}</ol>:<p>Open the report for findings and recommendations from this workflow.</p>}</div>
    <div className="ux-result-feature ux-result-feature-small"><div className="ux-result-feature-title"><ClipboardCheck size={17}/><strong>Results at a glance</strong></div><div className="ux-result-mini"><BarChart3 size={16}/><span>{reports.length} reports & dashboards</span></div><div className="ux-result-mini"><ShieldAlert size={16}/><span>{artifacts.filter(a=>a.type==='quality_report').length} data quality checks</span></div><div className="ux-result-mini"><CheckCircle2 size={16}/><span>{passed} evaluations passed</span></div>{reports.slice(0,2).map(a=><div key={a.id} className="ux-result-mini"><FileText size={16}/><span>{artifactTitle(a)}</span></div>)}</div></div>
  <div className="ux-results-note"><CheckCircle2 size={15}/> Figures and insights are loaded from saved analysis artifacts. AI-generated explanations should still be reviewed against their supporting evidence. <Link to="/intelligence">Explore charts <ArrowRight size={13}/></Link></div>
  </section>;
}
