import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity, ArrowLeft, CheckCircle2, CircleAlert, Clock3, Code2, Database,
  FileJson, GitBranch, Layers, RotateCw, ShieldAlert, Download,
} from 'lucide-react';
import { api } from '../api';
import { useRunStream } from '../hooks/useRunStream';
import { ArtifactExplorer } from '../components/ArtifactExplorer';
import { ExecutionTimeline } from '../components/ExecutionTimeline';
import { AiUsagePanel } from '../components/AiUsagePanel';
import { AskRunPanel } from '../components/AskRunPanel';
import VerificationPanel from '../components/VerificationPanel';
import ResultsSummary from '../components/ResultsSummary';
import { downloadInvestigationPackage } from '../lib/investigationExport';
import { Empty, ErrorBox, Loading, PageHeader, Panel, Status, nice, timeAgo } from '../components/Ui';
import type { Artifact, GraphNode } from '../types';
import '../components/artifact-explorer.css';

type DetailTab = 'outputs' | 'execution' | 'logs';
const preferred=['data_profile','analytics','visualization','investigation','report','evaluation'];
const agentIcons=[Database,Code2,Layers,GitBranch,FileJson,CheckCircle2];
const statusEnd=new Set(['completed','failed','waiting_for_approval','cancelled']);
const displayName: Record<string,string> = {data_profile:'Review source data',analytics:'Calculate business findings',visualization:'Build charts & dashboard',investigation:'AI investigation',report:'Prepare executive report',evaluation:'Verify report quality'};

function WorkflowGraph({nodes, artifacts, onViewOutputs}: {nodes: GraphNode[]; artifacts: Artifact[]; onViewOutputs: (nodeId: string) => void}) {
  const ordered=[...nodes].sort((a,b)=>{const ia=preferred.indexOf(a.id),ib=preferred.indexOf(b.id);return (ia<0?999:ia)-(ib<0?999:ib);});
  return <div className="graph-track">{ordered.map((node,i)=>{const Icon=agentIcons[preferred.indexOf(node.id)]||GitBranch;const count=artifacts.filter(a=>a.producer_node_id===node.id).length;const duration=node.started_at&&node.finished_at?Math.max(0,Math.round((+new Date(node.finished_at)-+new Date(node.started_at))/1000)):null;return <div className="graph-unit" key={node.id}><div className={`graph-node graph-${node.status}`}><div className="graph-icon"><Icon size={19}/></div><span className="graph-label">{displayName[node.id]||nice(node.agent_type)}</span><Status status={node.status}/><div className="graph-meta">{duration!==null?`${duration}s elapsed`:node.retry_count>0?`${node.retry_count} retry(s)`:`${node.depends_on.length} dependencies`}</div>{count>0&&<button type="button" className="ae-graph-output" onClick={()=>onViewOutputs(node.id)}>View {count} {count===1?'output':'outputs'}</button>}</div>{i<ordered.length-1&&<div className="graph-connector" aria-hidden="true"><span/></div>}</div>})}</div>;
}

export default function WorkflowDetail() {
  const {runId=''}=useParams(); const id=decodeURIComponent(runId); const qc=useQueryClient();
  const [approvalComment,setApprovalComment]=useState(''); const [actionError,setActionError]=useState<string|null>(null); const [saving,setSaving]=useState(false); const [exporting,setExporting]=useState(false); const [exportNotice,setExportNotice]=useState('');
  const [tab,setTab]=useState<DetailTab>('execution'); const [focusNode,setFocusNode]=useState<string|null>(null);
  const initializedTab=useRef(false);
  const run=useQuery({queryKey:['run',id],queryFn:()=>api.run(id),refetchInterval:q=>statusEnd.has(q.state.data?.status||'')?false:1500});
  const {connection,jobs}=useRunStream(id,!statusEnd.has(run.data?.status||''));
  const graph=useQuery({queryKey:['graph',id],queryFn:()=>api.graph(id),refetchInterval:4000});
  const events=useQuery({queryKey:['events',id],queryFn:()=>api.events(id),refetchInterval:5000});
  const executionError=useQuery({queryKey:['execute-error',id],queryFn:()=>Promise.resolve(qc.getQueryData<string>(['execute-error',id])||''),enabled:false});
  useEffect(()=>{document.title=`${run.data?.task?.slice(0,35)||'Workflow'} — AEAI OS`;return()=>{document.title='Enterprise AI OS — Command Center'}},[run.data?.task]);
  useEffect(()=>{initializedTab.current=false;setTab('execution');setFocusNode(null);},[id]);
  useEffect(()=>{if(run.data&&!initializedTab.current){setTab(run.data.status==='completed'?'outputs':'execution');initializedTab.current=true;}},[run.data]);
  const data=run.data,nodes=graph.data||[],artifacts=data?.artifacts||[],evaluations=data?.evaluations||[];const completed=nodes.filter(n=>n.status==='completed').length;
  async function decide(nodeId:string,approved:boolean){setSaving(true);setActionError(null);try{await api.approve(id,nodeId,approved,approvalComment);await Promise.all([run.refetch(),graph.refetch(),events.refetch()]);setApprovalComment('')}catch(e){setActionError(e instanceof Error?e.message:String(e))}finally{setSaving(false)}}
  const viewOutputs=(nodeId:string)=>{setFocusNode(nodeId);setTab('outputs');};
  return <div className="page ae-detail-page"><Link to="/workflows" className="back-link"><ArrowLeft size={16}/> Back to workflows</Link>{run.isLoading?<Loading label="Loading workflow…"/>:run.isError?<ErrorBox error={run.error}/>:data&&<>
    <PageHeader eyebrow={`RUN / ${id.slice(0,21)}…`} title={data.task} description={`Created ${new Date(data.created_at).toLocaleString()} · ${id}`} action={<Status status={data.status}/>}/>
    {(executionError.data||qc.getQueryData<string>(['execute-error',id]))&&<ErrorBox error={executionError.data||qc.getQueryData<string>(['execute-error',id])}/>} {data.error_summary&&<ErrorBox error={data.error_summary}/>}
    <div className="run-detail-stats"><div><span>EXECUTION STATUS</span><strong><Status status={data.status}/></strong></div><div><span>AGENTS COMPLETED</span><strong>{completed} / {nodes.length||'—'}</strong></div><div><span>GENERATED ARTIFACTS</span><strong>{artifacts.filter(a=>a.type!=='dataset').length}</strong></div><div><span>LAST ACTIVITY</span><strong>{timeAgo(data.updated_at)}</strong></div></div>
    {data.status==='completed'&&<ResultsSummary runId={id} artifacts={artifacts} evaluations={evaluations} onOutputs={()=>setTab('outputs')}/>}
    {data.status==='completed'&&<div className="ux-export-row"><span>Save an offline collection of generated results, including the evidence manifest. Original CSV files are excluded.</span><button type="button" className="btn btn-secondary" disabled={exporting} onClick={()=>{setExporting(true);setExportNotice('');void downloadInvestigationPackage(data).then(n=>setExportNotice(`Downloaded ${n} generated files.`)).catch(e=>setExportNotice(e instanceof Error?e.message:String(e))).finally(()=>setExporting(false));}}><Download size={16}/>{exporting?'Preparing ZIP…':'Download results package'}</button>{exportNotice&&<span role="status" className="ux-export-status">{exportNotice}</span>}</div>}
    <AiUsagePanel events={events.data??[]}/>
    {data.status==='completed'&&<VerificationPanel runId={id}/>}
    {data.status==='completed'&&<AskRunPanel runId={id} onViewEvidence={()=>setTab('outputs')}/>}
    <nav className="ae-workflow-tabs" role="tablist" aria-label="Workflow details">
      {([['outputs','Reports & Results',artifacts.length],['execution','Agent Progress',nodes.length],['logs','Activity & Details',events.data?.length??0]] as Array<[DetailTab,string,number]>).map(([key,label,count])=><button type="button" role="tab" aria-selected={tab===key} key={key} className={tab===key?'selected':''} onClick={()=>setTab(key)}>{label}<span>{count}</span></button>)}
      <div className="ae-tabs-side">{connection==='live'?'Live connected':'Polling fallback'}{jobs.length?` · ${nice(jobs[0].status)}`:''}</div>
    </nav>
    {nodes.filter(n=>n.status==='waiting_for_approval').length>0&&<Panel title="Human approval required" description="A governed operation is waiting for an authorized reviewer"><div className="approval-box"><ShieldAlert size={22}/><div className="approval-content"><strong>Review before continuing</strong><p>Examine the node and related evidence before approving an operation.</p><textarea value={approvalComment} onChange={e=>setApprovalComment(e.target.value)} placeholder="Approval or denial reason" rows={2}/><div className="approval-actions">{nodes.filter(n=>n.status==='waiting_for_approval').map(n=><div key={n.id} className="approval-actions-inner"><span>{n.id}</span><button className="btn btn-danger" disabled={saving} onClick={()=>void decide(n.id,false)}>Deny</button><button className="btn btn-primary" disabled={saving} onClick={()=>void decide(n.id,true)}>Approve</button></div>)}</div>{actionError&&<ErrorBox error={actionError}/>}</div></div></Panel>}
    {tab==='outputs'&&<div id="ae-run-output-anchor"><ArtifactExplorer artifacts={artifacts} focusNode={focusNode} onClearFocus={()=>setFocusNode(null)}/></div>}
    {tab==='execution'&&<><Panel title="Agent execution graph" description={`Actual persisted node states · ${connection==='live'?'Live updates connected':'Polling fallback'}`} action={<button className="btn btn-secondary" onClick={()=>{void run.refetch();void graph.refetch();void events.refetch();}}><RotateCw size={15}/> Refresh</button>}>{graph.isError?<ErrorBox error={graph.error}/>:nodes.length?<><WorkflowGraph nodes={nodes} artifacts={artifacts} onViewOutputs={viewOutputs}/><div className="graph-caption"><Activity size={14}/> Nodes execute sequentially in the current generic backend; click an agent's outputs to inspect saved files.</div></>:<div className="loading"><Clock3 size={18}/> Waiting for the planner to register the execution graph…</div>}</Panel>
      <Panel title="Evaluation & trace" description="Quality checks and workflow correlation"><div className="info-pair"><span>Trace ID</span><code>{data.trace_id||'Not available'}</code></div><div className="info-pair"><span>Dataset attached</span><span>{data.dataset_artifact_id?'Yes':'No'}</span></div>{evaluations.length?evaluations.map(e=><div className="evaluation-item" key={e.id}><div className="evaluation-top"><strong>Quality score: {Math.round(e.score*100)}%</strong><Status status={e.passed?'completed':'failed'}/></div>{e.checks.map((check,i)=><div key={`${String(check.name)}-${i}`} className="evaluation-check">{check.passed?<CheckCircle2 size={15} className="text-good"/>:<CircleAlert size={15} className="text-bad"/>}{nice(check.name||`Check ${i+1}`)}</div>)}</div>):<p className="subtle-copy" style={{padding:'18px 20px'}}>Evaluation results will appear when the evaluation agent completes.</p>}</Panel>
    </>}
    {tab==='logs'&&(events.isError?<ErrorBox error={events.error}/>:events.isLoading?<Loading label="Loading execution logs…"/>:<ExecutionTimeline events={events.data??[]} nodes={nodes} artifacts={artifacts} onViewOutputs={viewOutputs}/>)}
    {tab==='outputs'&&artifacts.length===0&&data.status==='queued'&&<Empty title="Your workflow is queued" description="Outputs will appear here as the agents finish their work."/>}
  </>}</div>;
}
