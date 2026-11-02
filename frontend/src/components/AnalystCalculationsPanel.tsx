import { lazy, Suspense, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BrainCircuit, Calculator, CircleAlert, Search, Send, ShieldCheck } from 'lucide-react';
import { api } from '../api';
import { ErrorBox } from './Ui';
import type { AnalystCalculation } from '../types';

const AnalystChart=lazy(()=>import('./AnalystChart'));
const examples=[
  'Compare total spending by supplier.',
  'Show monthly procurement spending as a trend.',
  'Which categories account for the most spending?',
  'Compare spending between March and June 2026.',
];
const symbols:Record<string,string>={USD:'$',INR:'₹',EUR:'€',GBP:'£',JPY:'¥'};
function currency(v:number,code:string){return `${symbols[code]||''}${v.toLocaleString('en-IN',{maximumFractionDigits:2})}${symbols[code]?'':` ${code}`}`;}

function CalculationResult({item}: {item:AnalystCalculation}){
  // Local UI-only drilldown. Does not send a model request or change verified totals.
  const [filter,setFilter]=useState('');
  const [sort,setSort]=useState<'highest'|'name'>('highest');
  const points=item.points.filter(point=>point.label.toLowerCase().includes(filter.toLowerCase())).sort(
    (a,b)=>sort==='highest'?b.value-a.value:a.label.localeCompare(b.label)
  );
  const displayed={...item,points};
  return <article className="ux-analyst-calc-answer">
    <div className="ux-analyst-calc-question"><span>YOUR QUESTION</span><strong>{item.question}</strong></div>
    <div className="ux-analyst-calc-result">
      <div className="ux-analyst-calc-heading"><ShieldCheck size={17}/><span>Python-verified calculation</span><span className="ux-calc-pill">{item.tool_label}</span></div>
      <h3>{item.chart_title}</h3>
      <p>{item.answer}</p>
      <div className="ux11-drilldown"><label><Search size={15}/> Filter chart groups<input aria-label="Filter chart groups" placeholder="Search suppliers, categories or months" value={filter} onChange={event=>setFilter(event.target.value)}/></label><label>Sort groups<select aria-label="Sort chart groups" value={sort} onChange={event=>setSort(event.target.value as 'highest'|'name')}><option value="highest">Highest spending first</option><option value="name">Name / date</option></select></label></div>
      <Suspense fallback={<div className="ux-analyst-chart">Preparing your chart…</div>}><AnalystChart result={displayed}/></Suspense>
      {points.length===0&&<p className="ux11-empty-mini">No groups match this filter.</p>}
      <p className="ux11-filter-note">Showing {points.length} of {item.points.length} verified groups. Filtering is local and does not change the original calculation.</p>
      <div className="ux-analyst-calc-table" role="region" aria-label="Verified calculation table" tabIndex={0}>
        <table><thead><tr><th>Group</th><th>Spending</th><th>Transactions</th></tr></thead><tbody>
          {points.map(point=><tr key={point.label}><td>{point.label}</td><td>{currency(point.value,item.currency)}</td><td>{point.transactions}</td></tr>)}
        </tbody></table>
      </div>
      <div className="ux-analyst-calc-notes"><CircleAlert size={16}/><div>{item.limitations.map((note,i)=><p key={i}>{note}</p>)}</div></div>
      <div className="ux-analyst-calc-foot"><span>{item.model} · {item.model_calls} AI request(s) · Estimated ${item.estimated_cost_usd.toFixed(6)}</span><span>{new Date(item.created_at).toLocaleString()}</span></div>
    </div>
  </article>;
}

export default function AnalystCalculationsPanel({runId}: {runId:string}){
  const queryClient=useQueryClient();
  const [question,setQuestion]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState<string|null>(null);
  const history=useQuery({queryKey:['analyst-calculations',runId],queryFn:()=>api.analystCalculations(runId),enabled:!!runId});
  const current=history.data??[];
  async function execute(){const text=question.trim();if(busy||text.length<8||text.length>600)return;
    setBusy(true);setError(null);
    try{await api.calculateFollowup(runId,text);setQuestion('');await queryClient.invalidateQueries({queryKey:['analyst-calculations',runId]});}
    catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}
  }
  return <section className="ux-analyst-calc-panel" aria-label="Ask AI to calculate something new">
    <div className="ux-analyst-calc-intro"><div className="ux-analyst-calc-icon"><Calculator size={22}/></div><div><h2>Ask AI to calculate something new</h2><p>Qwen selects a safe read-only calculation; Python computes the exact results and draws a chart. Nothing runs until you press Calculate.</p></div></div>
    <label htmlFor="ux-calculation-question">What would you like to calculate?</label>
    <textarea id="ux-calculation-question" value={question} onChange={e=>setQuestion(e.target.value)} rows={3} maxLength={600} placeholder="Compare supplier spending and show me a chart…"/>
    <div className="ux-analyst-calc-actions"><small>Up to 2 Hugging Face calls · No arbitrary SQL or Python · Group totals only</small><button className="btn btn-primary" type="button" disabled={busy||question.trim().length<8} onClick={()=>void execute()}><Send size={15}/>{busy?'Calculating…':'Calculate & chart'}</button></div>
    {!current.length&&<div className="ux-analyst-calc-examples"><span>Try asking:</span>{examples.map(s=><button key={s} type="button" onClick={()=>setQuestion(s)}>{s}</button>)}</div>}
    {error&&<ErrorBox error={error}/>}{history.isError&&<ErrorBox error={history.error}/>}
    {history.isLoading&&<p className="ae-ask-muted">Loading saved calculations…</p>}
    {[...current].reverse().map(item=><CalculationResult key={item.id} item={item}/>)}
    <div className="ux-analyst-calc-disclaimer"><BrainCircuit size={15}/> Only local authorized CSV data is supported initially. Charts show verified aggregates; groups with fewer than two transactions are hidden. New calculations may use Hugging Face credits.</div>
  </section>;
}
