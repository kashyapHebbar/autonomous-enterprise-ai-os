import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, CheckCircle2, FileSpreadsheet, Play, ShieldCheck, Sparkles, X } from 'lucide-react';
import { api } from '../api';
import { ErrorBox } from './Ui';

const templates = [
  {name:'Procurement risks', path:'examples/procurement_demo.csv', prompt:'Analyze procurement spending. Find supplier concentration, duplicate invoices, unusual transactions, monthly trends, data quality concerns, and opportunities for investigation. Generate an executive report and evidence-backed findings.'},
  {name:'Sales performance',path:'examples/sales_demo.csv',prompt:'Analyze sales performance by region and product. Identify trends, unusual results, data quality concerns, and important business opportunities. Generate a management report and clear charts.'},
  {name:'Data quality review',path:'examples/procurement_demo.csv',prompt:'Review this dataset for missing values, inconsistencies and outliers. Explain which quality problems should be addressed first, and generate supporting charts and a quality report.'},
];
export default function QuickStartWizard({onClose}: {onClose:()=>void}) {
  const navigate=useNavigate(), qc=useQueryClient();
  useEffect(()=>{const handler=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose();};window.addEventListener('keydown',handler);return()=>window.removeEventListener('keydown',handler);},[onClose]);
  const {data:sources=[]}=useQuery({queryKey:['data-sources'],queryFn:api.dataSources});
  const [step,setStep]=useState(0),[template,setTemplate]=useState(0),[task,setTask]=useState(templates[0].prompt);
  const [sourceType,setSourceType]=useState<'demo'|'registered'|'uri'>('demo');
  const [demo,setDemo]=useState(templates[0].path),[sourceId,setSourceId]=useState(''),[uri,setUri]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null);
  const validTask=task.trim().length>=3;
  const validSource=sourceType==='demo'||(sourceType==='registered'?Boolean(sourceId):Boolean(uri.trim()));
  const sourceName=sourceType==='demo'?demo:sourceType==='registered'?(sources.find(s=>s.id===sourceId)?.name||'Registered source'):uri;
  async function create() {
    setBusy(true);setError(null);
    try {
      const payload:{task:string;metadata:Record<string,unknown>;dataset_uri?:string;data_source_id?:string}={task:task.trim(),metadata:{source:'guided-workflow-setup'}};
      if(sourceType==='demo')payload.dataset_uri=demo;
      else if(sourceType==='registered')payload.data_source_id=sourceId;
      else payload.dataset_uri=uri.trim();
      const run=await api.createRun(payload);
      try {const job=await api.enqueueRun(run.id);qc.setQueryData(['jobs',run.id],[job]);}
      catch(e){setError(`Analysis created but could not start automatically: ${e instanceof Error?e.message:String(e)}. You can still open it from Workflows.`);await qc.invalidateQueries({queryKey:['runs']});return;}
      await qc.invalidateQueries({queryKey:['runs']});onClose();navigate(`/workflows/${encodeURIComponent(run.id)}`);
    }catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}
  }
  return <div className="ux-modal-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}><section role="dialog" aria-modal="true" aria-label="Create a new analysis" className="ux-wizard"><header className="ux-wizard-header"><div><span className="eyebrow">GUIDED WORKFLOW</span><h2>Start a new investigation</h2><p>Three straightforward steps. No technical setup required.</p></div><button type="button" aria-label="Close" className="icon-button" onClick={onClose}><X/></button></header>
  <div className="ux-steps">{['Your question','Choose data','Review & run'].map((name,i)=><div key={name} className={`ux-step ${step===i?'ux-step-active':step>i?'ux-step-done':''}`}><span>{step>i?<CheckCircle2 size={15}/>:i+1}</span>{name}</div>)}</div>
  <div className="ux-wizard-body">
    {step===0&&<><h3>What would you like to find out?</h3><p className="subtle-copy">Start with a business example, then customize the objective in your own words.</p><div className="ux-templates">{templates.map((item,i)=><button type="button" key={item.name} className={template===i?'ux-template-active':''} onClick={()=>{setTemplate(i);setTask(item.prompt);setDemo(item.path);setSourceType('demo');}}><Sparkles size={16}/>{item.name}</button>)}</div><label className="ux-field">Your business question<textarea maxLength={4000} rows={5} value={task} onChange={e=>setTask(e.target.value)} placeholder="Describe the business question or investigation…"/></label></>}
    {step===1&&<><h3>Which data should we analyze?</h3><p className="subtle-copy">Choose an example, an existing data source, or a path already accessible to your FastAPI backend.</p><div className="ux-source-options">{([['demo','Example dataset'],['registered','Registered source'],['uri','Dataset path']] as const).map(([val,label])=><label key={val}><input type="radio" name="ux-source" checked={sourceType===val} onChange={()=>setSourceType(val)}/>{label}</label>)}</div>
      {sourceType==='demo'&&<label className="ux-field">Example dataset<select value={demo} onChange={e=>setDemo(e.target.value)}><option value="examples/procurement_demo.csv">Procurement operations</option><option value="examples/sales_demo.csv">Regional sales performance</option></select></label>}
      {sourceType==='registered'&&<label className="ux-field">Available datasets<select value={sourceId} onChange={e=>setSourceId(e.target.value)}><option value="">Choose a registered source</option>{sources.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select>{!sources.length&&<small>No sources registered yet. Register one in Data Sources, or use an example dataset.</small>}</label>}
      {sourceType==='uri'&&<label className="ux-field">Dataset path<input value={uri} onChange={e=>setUri(e.target.value)} placeholder="examples/my_dataset.csv"/><small>This path must already be available to the backend. Uploading a file is not part of this step.</small></label>}</>}
    {step===2&&<><h3>Ready to investigate</h3><div className="ux-review"><div><Sparkles size={18}/><span><strong>Business objective</strong><small>{task}</small></span></div><div><FileSpreadsheet size={18}/><span><strong>Dataset</strong><small>{sourceName}</small></span></div><div><ShieldCheck size={18}/><span><strong>Trusted execution</strong><small>Uses your current governed agents and configured model budgets. AI usage may incur inference charges.</small></span></div></div></>}
  </div>{error&&<div className="ux-wizard-error"><ErrorBox error={error}/></div>}
  <footer className="ux-wizard-foot"><button type="button" className="btn btn-secondary" onClick={()=>step===0?onClose():setStep(x=>x-1)}>{step>0?<ArrowLeft size={15}/>:null}{step>0?'Back':'Cancel'}</button>{step<2?<button type="button" className="btn btn-primary" onClick={()=>setStep(x=>x+1)} disabled={step===0?!validTask:!validSource}>Continue <ArrowRight size={15}/></button>:<button type="button" className="btn btn-primary" onClick={()=>void create()} disabled={busy}><Play size={15}/>{busy?'Starting analysis…':'Start investigation'}</button>}</footer>
  </section></div>;
}
