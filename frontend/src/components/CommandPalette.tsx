import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, ArrowUpRight, Database, FileStack, ChartNoAxesCombined, GitCompareArrows, Home, Keyboard, MessageCircle, RadioTower, ServerCog, Search, Settings2, Sparkles, X } from 'lucide-react';
import type { Run } from '../types';
const destinations=[
  {name:'Home',hint:'Overview and recent activity',path:'/',icon:Home},
  {name:'Investigations',hint:'Workflow history and new analyses',path:'/workflows',icon:Activity},
  {name:'Data Sources',hint:'Registered datasets and connectors',path:'/data',icon:Database},
  {name:'Results Library',hint:'Reports, charts and saved results',path:'/artifacts',icon:FileStack},
  {name:'AI Insights',hint:'Charts and calculated findings',path:'/intelligence',icon:Sparkles},
  {name:'AI Analyst',hint:'Ask questions about saved results',path:'/analyst',icon:MessageCircle},
  {name:'Visualization Studio',hint:'Interactive charts, filters and saved dashboard views',path:'/visualizations',icon:ChartNoAxesCombined},
  {name:'Compare Analyses',hint:'See what changed between runs',path:'/compare',icon:GitCompareArrows},
  {name:'Intelligence Monitoring',hint:'Scheduled investigations and alerts',path:'/monitoring',icon:RadioTower},
  {name:'Operations Center',hint:'Workflow queue, workers, and retries',path:'/operations',icon:ServerCog},
  {name:'Settings & Usage',hint:'Display preferences and AI costs',path:'/settings',icon:Settings2},
];
export default function CommandPalette({open,onClose,runs}: {open:boolean;onClose:()=>void;runs:Run[]}){
  const [query,setQuery]=useState('');const input=useRef<HTMLInputElement>(null);const navigate=useNavigate();
  useEffect(()=>{if(open){setQuery('');window.setTimeout(()=>input.current?.focus(),0);}},[open]);
  useEffect(()=>{if(!open)return;const escape=(e:KeyboardEvent)=>{if(e.key==='Escape')onClose();};window.addEventListener('keydown',escape);return ()=>window.removeEventListener('keydown',escape);},[open,onClose]);
  const q=query.trim().toLowerCase();
  const links=useMemo(()=>destinations.filter(x=>`${x.name} ${x.hint}`.toLowerCase().includes(q)),[q]);
  const matches=useMemo(()=>[...runs].sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at)).filter(r=>`${r.task} ${r.id}`.toLowerCase().includes(q)).slice(0,q?7:4),[runs,q]);
  if(!open)return null;
  const go=(path:string)=>{onClose();navigate(path);};
  return <div className="ux-modal-overlay ux-command-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}><section className="ux-command" role="dialog" aria-modal="true" aria-label="Search the AI OS"><div className="ux-command-input"><Search size={20}/><input ref={input} value={query} onChange={e=>setQuery(e.target.value)} placeholder="Find pages, workflows, reports…" aria-label="Search pages and workflows"/><button type="button" aria-label="Close search" onClick={onClose}><X size={19}/></button></div><div className="ux-command-results">
    {links.length>0&&<div className="ux-command-group"><span>PAGES & TOOLS</span>{links.map(x=>{const Icon=x.icon;return <button type="button" key={x.path} onClick={()=>go(x.path)}><Icon size={18}/><span><strong>{x.name}</strong><small>{x.hint}</small></span><ArrowUpRight size={15}/></button>;})}</div>}
    {matches.length>0&&<div className="ux-command-group"><span>WORKFLOWS</span>{matches.map(r=><button type="button" key={r.id} onClick={()=>go(`/workflows/${encodeURIComponent(r.id)}`)}><Activity size={18}/><span><strong>{r.task}</strong><small>{r.status.replaceAll('_',' ')} · {new Date(r.updated_at).toLocaleDateString()}</small></span><ArrowUpRight size={15}/></button>)}</div>}
    {!links.length&&!matches.length&&<div className="ux-command-empty">No matches. Try a different name or phrase.</div>}
  </div><footer className="ux-command-foot"><Keyboard size={15}/> Open with <kbd>⌘ K</kbd> or <kbd>Ctrl K</kbd><span>Escape to close</span></footer></section></div>;
}
