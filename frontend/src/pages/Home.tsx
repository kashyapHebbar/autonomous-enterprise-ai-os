import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Activity, ArrowRight, CheckCircle2, Clock3, GitBranch, PlayCircle, ShieldAlert, Sparkles, TrendingUp } from 'lucide-react';
import { api } from '../api';
import Composer from '../components/Composer';
import RunTable from '../components/RunTable';
import { Empty, ErrorBox, Loading, Metric, Panel, Status, timeAgo } from '../components/Ui';

const active=new Set(['running','queued','pending','waiting_for_approval']);
export default function Home(){
  const {data:runs=[],isLoading,isError,error}=useQuery({queryKey:['runs'],queryFn:api.runs,refetchInterval:7000});
  const {data:investigationSummary}=useQuery({queryKey:['investigations-summary'],queryFn:api.investigationSummary,refetchInterval:15000});
  const ordered=[...runs].sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at));
  const completed=runs.filter(r=>r.status==='completed').length;
  const live=runs.filter(r=>active.has(r.status));
  return <div className="page home-page"><div className="home-hero"><div className="hero-glow hero-glow-one"/><div className="hero-glow hero-glow-two"/><div className="hero-copy"><div className="hero-chip"><Sparkles size={14}/> YOUR AI COMMAND CENTER <span className="hero-chip-dot"/> ONLINE</div><h1>Operate intelligence.<br/><span>Automate outcomes.</span></h1><p>One workspace for governed AI workflows, enterprise insights, and the agents that power them.</p></div><div className="hero-orbit" aria-hidden="true"><div className="orbit-circle orbit-large"/><div className="orbit-circle orbit-small"/><div className="orbit-core"><Sparkles size={31}/></div><span className="orbit-node orbit-node-one"><GitBranch size={18}/></span><span className="orbit-node orbit-node-two"><TrendingUp size={18}/></span><span className="orbit-node orbit-node-three"><ShieldAlert size={18}/></span></div></div>
    <div className="metrics-grid"><Metric label="Total workflows" value={runs.length} icon={<GitBranch size={18}/>} detail="Created in this environment"/><Metric label="Completed" value={completed} icon={<CheckCircle2 size={18}/>} detail={runs.length?`${Math.round(completed/runs.length*100)}% of all runs`:'No completed runs yet'}/><Metric label="Active workflows" value={live.length} icon={<Activity size={18}/>} detail="Pending, queued, running or paused"/><Metric label="Investigations" value={investigationSummary?.total??'—'} icon={<ShieldAlert size={18}/>} detail={investigationSummary?`${investigationSummary.new} new · ${investigationSummary.investigating} investigating`:'Checking case records'}/></div>
    <section className="section-space"><div className="section-title"><div><span className="eyebrow">START SOMETHING NEW</span><h2>What should your agents work on?</h2><p>Describe an objective, choose a dataset, and we'll run the existing analytics workflow.</p></div></div><Composer/></section>
    <div className="home-lower-grid"><Panel title="Recent workflows" description="Latest activity from your FastAPI backend" action={<Link to="/workflows" className="text-action">All workflows <ArrowRight size={15}/></Link>}>{isLoading?<Loading/>:isError?<ErrorBox error={error}/>:ordered.length?<RunTable runs={ordered.slice(0,6)}/>:<Empty title="No workflows yet" description="Use the composer above to create your first workflow."/>}</Panel>
      <Panel title="Execution pulse" description="Current run activity and status" className="pulse-panel">{live.length?live.slice(0,5).map(r=><Link className="pulse-item" key={r.id} to={`/workflows/${encodeURIComponent(r.id)}`}><div className="pulse-symbol"><PlayCircle size={18}/></div><div className="pulse-info"><strong>{r.task}</strong><small>{timeAgo(r.updated_at)}</small></div><Status status={r.status}/></Link>):<div className="quiet-state"><div className="quiet-icon"><Clock3 size={21}/></div><strong>All quiet right now</strong><p>No active workflows. Your platform is ready for the next task.</p></div>}<div className="pulse-footer"><span className="live-dot"/> Activity is refreshed automatically</div></Panel></div>
  </div>;
}
