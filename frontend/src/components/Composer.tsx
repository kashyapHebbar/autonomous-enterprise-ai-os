import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, ChevronDown, Database, LoaderCircle, Play, Sparkles } from 'lucide-react';
import { api } from '../api';
import { ErrorBox } from './Ui';

const suggestions = [
  'Analyze procurement spending, flag anomalies and generate a management report.',
  'Analyze regional sales performance and visualize monthly trends.',
  'Profile this dataset and highlight missing data, patterns, and outliers.',
];
export default function Composer({compact=false}: {compact?: boolean}) {
  const navigate=useNavigate(), qc=useQueryClient();
  const [task,setTask]=useState('');
  const [mode,setMode]=useState<'demo'|'source'|'uri'>('demo');
  const [demo,setDemo]=useState('examples/procurement_demo.csv');
  const [source,setSource]=useState('');
  const [uri,setUri]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const {data: sources=[]}=useQuery({queryKey:['data-sources'],queryFn:api.dataSources});
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    if(task.trim().length<3) {setError('Enter a business objective of at least three characters.');return;}
    if(mode==='source'&&!source){setError('Choose a registered data source.');return;}
    if(mode==='uri'&&!uri.trim()){setError('Enter a dataset URI.');return;}
    setBusy(true);
    try {
      const payload:{task:string;metadata:Record<string,unknown>;dataset_uri?:string;data_source_id?:string}={task:task.trim(),metadata:{source:'react-command-center',...(mode==='demo'?{dataset_origin:'demo'}:{})}};
      if(mode==='demo') payload.dataset_uri=demo;
      if(mode==='uri') payload.dataset_uri=uri.trim();
      if(mode==='source') payload.data_source_id=source;
      const run=await api.createRun(payload);
      await qc.invalidateQueries({queryKey:['runs']});
      navigate(`/workflows/${encodeURIComponent(run.id)}`);
      // Existing backend /execute is synchronous. Fire it after navigation and poll the real status.
      // The request remains in-flight even when the form unmounts.
      void api.executeRun(run.id).then(async()=>{await qc.invalidateQueries({queryKey:['run',run.id]}); await qc.invalidateQueries({queryKey:['runs']});}).catch(async(err:unknown)=>{
        qc.setQueryData(['execute-error',run.id],err instanceof Error?err.message:String(err));
        await qc.invalidateQueries({queryKey:['run',run.id]});
      });
    } catch(e) {setError(e instanceof Error?e.message:String(e));} finally {setBusy(false);}
  }
  return <div className={`composer ${compact?'composer-compact':''}`}><form onSubmit={submit}><div className="composer-leading"><Sparkles size={18}/><span>AI WORKFLOW COMPOSER</span></div><textarea aria-label="Describe your business objective" placeholder="What would you like your AI agents to analyze?" value={task} onChange={e=>setTask(e.target.value)} rows={compact?2:3} maxLength={4000}/><div className="composer-control-row"><div className="source-control"><Database size={15}/><select aria-label="Dataset type" value={mode} onChange={e=>setMode(e.target.value as typeof mode)}><option value="demo">Demo dataset</option><option value="source">Registered data source</option><option value="uri">Dataset URI</option></select><ChevronDown size={13}/></div>{mode==='demo'&&<select className="source-option" aria-label="Demo dataset" value={demo} onChange={e=>setDemo(e.target.value)}><option value="examples/procurement_demo.csv">Procurement operations</option><option value="examples/sales_demo.csv">Regional sales</option></select>}{mode==='source'&&<select className="source-option" aria-label="Registered data source" value={source} onChange={e=>setSource(e.target.value)}><option value="">Select a source</option>{sources.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select>}{mode==='uri'&&<input className="source-uri" aria-label="Dataset URI" placeholder="examples/procurement_demo.csv" value={uri} onChange={e=>setUri(e.target.value)}/>}<button className="btn btn-primary composer-submit" type="submit" disabled={busy}>{busy?<LoaderCircle className="spin" size={17}/>:<Play size={16} fill="currentColor"/>}{busy?'Creating…':'Run workflow'}<ArrowRight size={16}/></button></div></form>{error&&<ErrorBox error={error}/>}<div className="suggestions"><span>TRY ASKING</span>{suggestions.map((s,i)=><button key={s} onClick={()=>{setTask(s);if(i===1){setMode('demo');setDemo('examples/sales_demo.csv')}else if(i===0){setMode('demo');setDemo('examples/procurement_demo.csv')}}}>{i===0?'Procurement intelligence':i===1?'Sales performance':'Data quality'}<ArrowRight size={13}/></button>)}</div></div>;
}
