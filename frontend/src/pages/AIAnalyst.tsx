import { lazy, Suspense, useState } from 'react';
import '../upgrade10.css';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, BrainCircuit, MessageCircle, ShieldCheck, Sparkles } from 'lucide-react';
import { api } from '../api';
import { AskRunPanel } from '../components/AskRunPanel';
const AnalystCalculationsPanel=lazy(()=>import('../components/AnalystCalculationsPanel'));
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Ui';
export default function AIAnalyst(){
  const navigate=useNavigate();const {data:runs=[],isLoading,isError,error}=useQuery({queryKey:['runs'],queryFn:api.runs});const completed=[...runs].filter(r=>r.status==='completed').sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at));
  const [selected,setSelected]=useState('');const id=selected||completed[0]?.id||'';
  const active=completed.find(r=>r.id===id);
  return <div className="page ux-analyst-page"><PageHeader eyebrow="ASK BETTER QUESTIONS" title="Your AI Analyst" description="Explore a completed investigation by asking grounded questions about its saved findings. No reanalysis or model calls happen until you press Ask."/>
    <section className="ux-analyst-hero"><div><span><Sparkles size={14}/> EVIDENCE-FIRST ASSISTANCE</span><h2>Go beyond the report.</h2><p>Ask what matters, see verified supporting figures, and keep a history of the explanations you received.</p></div><div aria-hidden="true" className="ux-analyst-mark"><BrainCircuit size={65}/></div></section>
    {isLoading?<Loading/>:isError?<ErrorBox error={error}/>:!id?<Empty title="No completed analysis yet" description="Run an investigation first. The AI Analyst uses existing, verified results to answer questions." action={<Link to="/workflows" className="btn btn-primary">Start an investigation <ArrowRight size={15}/></Link>}/>:<>
      <div className="ux-analyst-context"><div><MessageCircle size={17}/><span><strong>Ask about this completed analysis</strong><small>Choose the saved investigation your question refers to.</small></span></div><select aria-label="Choose completed analysis" value={id} onChange={e=>setSelected(e.target.value)}>{completed.map(r=><option value={r.id} key={r.id}>{r.task.slice(0,90)}</option>)}</select></div>
      <Suspense fallback={<div className="panel">Loading analytical tools…</div>}><AnalystCalculationsPanel key={`tools-${id}`} runId={id}/></Suspense>
      <AskRunPanel key={id} runId={id} onViewEvidence={()=>navigate(`/workflows/${encodeURIComponent(id)}`)}/>
      <div className="ux-results-note"><ShieldCheck size={15}/> Questions use the selected analysis's saved evidence and may consume one Hugging Face request per question. <Link to={`/workflows/${encodeURIComponent(id)}`}>Open complete results <ArrowRight size={14}/></Link></div>
      {active&&<div className="ux-analyst-footnote">Selected analysis was completed in this environment. Generated responses do not replace human review or the original calculated evidence.</div>}
    </>}
  </div>;
}
