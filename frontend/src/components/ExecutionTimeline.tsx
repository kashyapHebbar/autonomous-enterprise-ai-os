import { useMemo, useState } from 'react';
import {
  Activity, AlertCircle, AlertTriangle, Check, ChevronDown, Clock3, Copy,
  Eye, FileJson, Filter, Search, ShieldAlert, Terminal, X,
} from 'lucide-react';
import type { AgentEvent, Artifact, GraphNode } from '../types';
import { Empty, nice, timeAgo } from './Ui';
import './artifact-explorer.css';

type LogFilter = 'all'|'errors'|'warnings'|'approvals'|'tools'|'system';
const nodeTitle = (key: string) => ({data_profile:'Data profiling',analytics:'Analytics engine',visualization:'Visualization',report:'Report generation',evaluation:'Quality evaluation'} as Record<string,string>)[key] ?? nice(key);
function level(event: AgentEvent): Exclude<LogFilter, 'all'> {
  const type = event.event_type.toLowerCase();
  const severity = String(event.payload.severity ?? event.payload.level ?? '').toLowerCase();
  if (type==='error' || ['error','critical'].includes(severity)) return 'errors';
  if (type.includes('approval') || type==='audit' && String(event.payload.action ?? '').includes('approval')) return 'approvals';
  if (type==='tool_call') return 'tools';
  if (type==='warning' || severity==='warning' || severity==='warn') return 'warnings';
  return 'system';
}
function eventSummary(event: AgentEvent): string {
  const candidate = event.payload.message ?? event.payload.summary ?? event.payload.reason ?? event.payload.action;
  if (typeof candidate === 'string' && candidate.trim()) return candidate;
  return event.node_id ? `${nodeTitle(event.node_id)} · ${nice(event.event_type)}` : nice(event.event_type);
}
export function ExecutionTimeline({events, nodes, artifacts, onViewOutputs}: {
  events: AgentEvent[]; nodes: GraphNode[]; artifacts: Artifact[];
  onViewOutputs: (nodeId: string) => void;
}) {
  const [filter,setFilter] = useState<LogFilter>('all');
  const [search,setSearch] = useState('');
  const [selectedAgent,setSelectedAgent] = useState('all');
  const [expanded,setExpanded] = useState<string[]>([]);
  const nodeNames = useMemo(() => Array.from(new Set([...nodes.map(n=>n.id),...events.map(e=>e.node_id)].filter(Boolean))).sort(), [nodes,events]);
  const filtered = useMemo(() => [...events].sort((a,b)=>+new Date(b.created_at)-+new Date(a.created_at)).filter(event=>{
    if (filter!=='all' && level(event)!==filter) return false;
    if (selectedAgent!=='all' && event.node_id!==selectedAgent) return false;
    const searchable=`${event.event_type} ${event.node_id} ${eventSummary(event)} ${String(event.payload.action??'')}`.toLowerCase();
    return searchable.includes(search.trim().toLowerCase());
  }),[events,filter,search,selectedAgent]);
  const counts = useMemo(() => events.reduce((acc,event)=>({...acc,[level(event)]:acc[level(event)]+1}),{errors:0,warnings:0,approvals:0,tools:0,system:0}),[events]);
  function toggle(id: string) {setExpanded(old=>old.includes(id)?old.filter(x=>x!==id):[...old,id]);}
  const filters: Array<[LogFilter,string,number]>=[['all','All events',events.length],['errors','Errors',counts.errors],['warnings','Warnings',counts.warnings],['approvals','Approvals',counts.approvals],['tools','Tool calls',counts.tools],['system','Activity',counts.system]];
  return <section className="ae-events"><div className="ae-events-heading"><div><div className="ae-kicker">EXECUTION OBSERVABILITY</div><h2>Agent execution timeline</h2><p>Search and inspect the persisted events recorded during this workflow. Logs are not fabricated or inferred.</p></div><div className="ae-events-total"><Activity size={18}/>{events.length} events</div></div>
    <div className="ae-events-tabs" role="group" aria-label="Filter execution events">{filters.map(([value,label,count])=><button type="button" key={value} aria-pressed={filter===value} className={filter===value?'selected':''} onClick={()=>setFilter(value)}>{label}<span>{count}</span></button>)}</div>
    <div className="ae-artifact-toolbar"><label className="ae-artifact-search"><Search size={16}/><input type="search" placeholder="Search event messages…" aria-label="Search execution logs" value={search} onChange={e=>setSearch(e.target.value)}/></label><label className="ae-artifact-agent"><Filter size={15}/><select aria-label="Filter logs by agent" value={selectedAgent} onChange={e=>setSelectedAgent(e.target.value)}><option value="all">All agents</option>{nodeNames.map(name=><option key={name} value={name}>{nodeTitle(name)}</option>)}</select></label>{(filter!=='all'||selectedAgent!=='all'||search)&&<button className="ae-clear-filters" onClick={()=>{setFilter('all');setSelectedAgent('all');setSearch('');}}><X size={14}/> Clear</button>}</div>
    {filtered.length===0 ? <Empty title={events.length?'No matching log events':'No execution events recorded yet'} description={events.length?'Clear the filters to view all recorded activity.':'The timeline will fill as the orchestrator writes agent events.'}/> : <div className="ae-log-list">{filtered.map(event=>{
      const classification=level(event); const Icon=classification==='errors'?AlertCircle:classification==='warnings'?AlertTriangle:classification==='approvals'?ShieldAlert:classification==='tools'?Terminal:Activity;
      const nodeArtifacts=artifacts.filter(a=>a.producer_node_id===event.node_id); const open=expanded.includes(event.id);
      return <article key={event.id} className={`ae-log-entry ae-log-${classification}`}><div className="ae-log-rail"><span className="ae-log-marker"><Icon size={16}/></span></div><div className="ae-log-content"><div className="ae-log-top"><strong>{nodeTitle(event.node_id||'system')}</strong><span className={`ae-log-badge ae-log-badge-${classification}`}>{classification==='system'?nice(event.event_type):nice(classification)}</span><time dateTime={event.created_at} title={new Date(event.created_at).toLocaleString()}>{timeAgo(event.created_at)}</time></div><p>{eventSummary(event)}</p><div className="ae-log-actions"><button type="button" aria-expanded={open} onClick={()=>toggle(event.id)}><FileJson size={14}/> {open?'Hide':'Technical'} details <ChevronDown className={open?'ae-chevron-open':''} size={14}/></button>{nodeArtifacts.length>0&&<button type="button" onClick={()=>onViewOutputs(event.node_id)}><Eye size={14}/> View {nodeArtifacts.length} {nodeArtifacts.length===1?'output':'outputs'}</button>}</div>{open&&<div className="ae-log-expanded"><div><Clock3 size={13}/>{new Date(event.created_at).toLocaleString()} <span>·</span> {event.event_type} <span>·</span> {event.id}</div><pre>{JSON.stringify(event.payload, null, 2)}</pre><button className="ae-log-copy" type="button" onClick={()=>{void navigator.clipboard?.writeText(JSON.stringify(event.payload,null,2));}}><Copy size={14}/> Copy JSON</button></div>}</div></article>;
    })}</div>}
    <footer className="ae-events-footer"><Check size={15}/> {filtered.length} of {events.length} saved events shown. Times displayed in your browser's local time zone.</footer>
  </section>;
}
