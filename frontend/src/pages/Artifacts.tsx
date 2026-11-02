import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowRight, BarChart3, CheckCircle2, FolderOpen, ShieldCheck, Sparkles } from 'lucide-react';
import { api } from '../api';
import { ArtifactExplorer } from '../components/ArtifactExplorer';
import { Empty, ErrorBox, Loading, PageHeader, Status } from '../components/Ui';
import type { Artifact } from '../types';
import './report-gallery.css';

export default function Artifacts() {
  const {data: runs = [], isError: runsError, error: runsFailure} = useQuery({queryKey:['runs'],queryFn:api.runs});
  const sorted=useMemo(()=>[...runs].sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at)),[runs]);
  const [selectedRun,setSelectedRun]=useState('');
  const activeRun=selectedRun||sorted[0]?.id||'';
  const query=useQuery({queryKey:['artifacts',activeRun],queryFn:()=>api.artifacts(activeRun),enabled:Boolean(activeRun)});
  const artifacts:Artifact[]=query.data??[];
  const visualCount=artifacts.filter(a=>['report','dashboard','chart'].includes(a.type)).length;
  const currentRun=sorted.find(r=>r.id===activeRun);
  return <div className="page reports-page">
    <PageHeader eyebrow="INTELLIGENCE LIBRARY" title="Reports & artifacts" description="Find every output by category, preview it without leaving the app, or download the original generated file." action={<label className="select-shell run-selector"><FolderOpen size={16}/><select aria-label="Choose workflow" value={activeRun} onChange={e=>setSelectedRun(e.target.value)}><option value="" disabled>Choose a workflow</option>{sorted.map(r=><option key={r.id} value={r.id}>{r.task.slice(0,72)}</option>)}</select></label>}/>
    {runsError?<ErrorBox error={runsFailure}/>:!activeRun?<Empty title="No workflows yet" description="Start an analysis to generate reports, charts, dashboards and quality evidence." action={<Link to="/" className="btn btn-primary"><Sparkles size={16}/> Create an analysis</Link>}/>:query.isLoading?<Loading label="Loading saved artifacts…"/>:query.isError?<ErrorBox error={query.error}/>:<>
      <section className="reports-hero"><div className="reports-hero-content"><span className="reports-kicker"><Sparkles size={13}/> ARTIFACT EXPLORER</span><h2>Every insight.<br/><em>One organized workspace.</em></h2><p>Reports, visualizations, and their evidence are grouped by purpose. Preview and download the actual outputs from your agents.</p><div className="reports-hero-foot"><span><CheckCircle2 size={15}/> {visualCount} visual outputs</span><span><ShieldCheck size={15}/> Source-linked evidence</span></div></div><div className="reports-hero-orbit" aria-hidden="true"><BarChart3 size={54}/></div></section>
      {currentRun&&<div className="ae-library-context"><div><span>SELECTED WORKFLOW</span><strong>{currentRun.task}</strong></div><Status status={currentRun.status}/><Link to={`/workflows/${encodeURIComponent(activeRun)}`} className="btn btn-secondary">Workflow details <ArrowRight size={15}/></Link></div>}
      <ArtifactExplorer key={activeRun} artifacts={artifacts}/>
    </>}
  </div>;
}
