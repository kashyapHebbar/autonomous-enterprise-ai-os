import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BookOpenCheck, BrainCircuit, ChevronDown, ChevronUp, Send, ShieldCheck } from 'lucide-react';
import { api } from '../api';
import { ErrorBox } from './Ui';
import type { RunQuestion } from '../types';

const prompts = [
  'What are the most important risks in these results?',
  'What evidence supports the unusual activity findings?',
  'What should a manager investigate first?',
];

function EvidenceValue({ value }: {value: string | number | boolean | null}) {
  return <strong>{value === null ? 'Not available' : typeof value === 'boolean' ? (value ? 'Yes' : 'No') : typeof value === 'number' ? value.toLocaleString('en-IN', {maximumFractionDigits: 4}) : value}</strong>;
}

function EvidenceSummary({ entry }: { entry: RunQuestion['evidence'][number] }) {
  return <div className="ae-ask-evidence"><strong className="ae-ask-evidence-title"><ShieldCheck size={14}/>{entry.label}</strong>
    <div className="ae-ask-facts">{Object.entries(entry.facts).map(([name,value])=><div key={name}><span>{name.replaceAll('_',' ')}</span><EvidenceValue value={value}/></div>)}</div>
    <details className="ae-ask-source"><summary>Where these figures came from</summary><span>Saved analysis: {entry.source_paths.join(', ')}</span></details>
  </div>;
}

export function AskRunPanel({runId, onViewEvidence}: {runId:string; onViewEvidence:()=>void}) {
  const qc=useQueryClient();
  const [question,setQuestion]=useState('');
  const [open,setOpen]=useState(true);
  const [sending,setSending]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const history=useQuery({queryKey:['run-questions',runId],queryFn:()=>api.runQuestions(runId),enabled:!!runId});

  async function ask() {
    const text=question.trim();
    if(text.length<8||text.length>600||sending) return;
    setSending(true);setError(null);
    try {
      await api.askRun(runId,text);
      setQuestion('');
      await qc.invalidateQueries({queryKey:['run-questions',runId]});
    } catch (err) {setError(err instanceof Error?err.message:String(err));}
    finally {setSending(false);}
  }

  return <section className="ae-ask-panel" aria-label="Ask about this analysis">
    <button className="ae-ask-title" type="button" onClick={()=>setOpen(v=>!v)} aria-expanded={open}>
      <span className="ae-ask-icon"><BrainCircuit size={20}/></span>
      <span><strong>Ask about this analysis</strong><small>Get a grounded explanation from Qwen using saved results</small></span>
      {open?<ChevronUp size={16}/>:<ChevronDown size={16}/>}
    </button>
    {open&&<div className="ae-ask-content">
      <div className="ae-ask-compose">
        <label htmlFor="ae-ask-question">Your question</label>
        <textarea id="ae-ask-question" rows={2} maxLength={600} value={question} onChange={event=>setQuestion(event.target.value)} placeholder="For example: Which supplier risks should I investigate first?"/>
        <div className="ae-ask-compose-bottom"><span>New questions may use one Hugging Face call; identical saved questions reuse their evidence without another request</span><button type="button" className="btn btn-primary" disabled={sending||question.trim().length<8} onClick={()=>void ask()}><Send size={14}/>{sending?'Checking evidence…':'Ask Qwen'}</button></div>
      </div>
      {!history.data?.length&&<div className="ae-ask-suggestions"><span>Try a question:</span>{prompts.map(text=><button type="button" key={text} onClick={()=>setQuestion(text)}>{text}</button>)}</div>}
      {error&&<ErrorBox error={error}/>}
      {history.isError&&<ErrorBox error={history.error}/>}
      {history.data?.length? <div className="ae-ask-history" aria-live="polite">
        {[...history.data].reverse().map(item=><article className="ae-ask-answer" key={item.id}>
          <div className="ae-ask-question"><span>You asked</span><strong>{item.question}</strong></div>
          <div className="ae-ask-result"><div className="ae-ask-result-heading"><BookOpenCheck size={17}/>Grounded answer</div><p>{item.answer}</p>
            <div className="ae-ask-evidence-grid">{item.evidence.map(entry=><EvidenceSummary key={entry.id} entry={entry}/>)}</div>
            {item.limitations.length>0&&<p className="ae-ask-limits"><b>What this doesn't prove:</b> {item.limitations.join(' ')}</p>}
            <div className="ae-ask-foot"><span>{item.model} · Estimated ${item.estimated_cost_usd.toFixed(6)} · {new Date(item.created_at).toLocaleString()}</span><button className="ae-ask-view" type="button" onClick={onViewEvidence}>View all outputs</button></div>
          </div>
        </article>)}
      </div>:history.isLoading?<p className="ae-ask-muted">Loading saved questions…</p>:null}
      <p className="ux11-conversation-note">Follow-up questions can refer to the last three saved exchanges from this same investigation. The answer must still cite current verified evidence.</p>
      <p className="ae-ask-disclaimer">Answers are limited to saved verified checks, not raw transactions. AI explanations can still be wrong; use the linked figures for decisions. Asking is opt-in and may consume HF credits.</p>
    </div>}
  </section>;
}
