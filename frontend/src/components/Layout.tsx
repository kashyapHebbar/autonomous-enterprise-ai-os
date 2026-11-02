import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { Activity, ArrowRight, Bell, BookOpen, BrainCircuit, ChevronRight, Database, FileStack, ChartNoAxesCombined, GitCompareArrows, LayoutDashboard, MessageCircle, Menu, RadioTower, ServerCog, Moon, PanelLeftClose, Plus, Search, Settings2, ShieldCheck, Sparkles, Sun, Wallet } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import CommandPalette from './CommandPalette';
import QuickStartWizard from './QuickStartWizard';
import { timeAgo } from './Ui';
import { updateUiPrefs, useUiPrefs } from '../lib/uiPreferences';

const mainLinks=[
  {path:'/',title:'Home',icon:LayoutDashboard},
  {path:'/workflows',title:'Investigations',icon:Activity},
  {path:'/data',title:'Data Sources',icon:Database},
  {path:'/artifacts',title:'Results Library',icon:FileStack},
  {path:'/intelligence',title:'AI Insights',icon:Sparkles},
  {path:'/visualizations',title:'Visualization Studio',icon:ChartNoAxesCombined},
  {path:'/analyst',title:'AI Analyst',icon:MessageCircle},
  {path:'/compare',title:'Compare Analyses',icon:GitCompareArrows},
];
const platformLinks=[
  {path:'/monitoring',title:'Intelligence Monitoring',icon:RadioTower},
  {path:'/operations',title:'Operations Center',icon:ServerCog},
  {path:'/scale',title:'Big Data Explorer',icon:Database},
  {path:'/investigations',title:'Review Cases',icon:ShieldCheck},
  {path:'/usage',title:'AI Usage',icon:Wallet},
  {path:'/settings',title:'Settings',icon:Settings2},
];
const advancedLinks=[{path:'/governance',title:'Governance',icon:ShieldCheck},{path:'/observability',title:'System Monitoring',icon:Activity}];
const allLinks=[...mainLinks,...platformLinks,...advancedLinks];
export default function Layout(){
  const prefs=useUiPrefs();const [mobileOpen,setMobileOpen]=useState(false),[collapsed,setCollapsed]=useState(false),[searchOpen,setSearchOpen]=useState(false),[wizardOpen,setWizardOpen]=useState(false),[notificationsOpen,setNotificationsOpen]=useState(false);
  const notificationsRef=useRef<HTMLDivElement>(null);const location=useLocation();
  const {data:user}=useQuery({queryKey:['me'],queryFn:api.me,retry:false});
  const {data:health}=useQuery({queryKey:['health'],queryFn:api.health,retry:false,refetchInterval:30000});
  const {data:runs=[]}=useQuery({queryKey:['runs'],queryFn:api.runs,refetchInterval:7000});
  useEffect(()=>{document.documentElement.dataset.theme=prefs.theme;document.documentElement.dataset.density=prefs.density;document.documentElement.dataset.motion=prefs.motion?'enabled':'disabled';},[prefs]);
  useEffect(()=>{setMobileOpen(false);setNotificationsOpen(false);},[location.pathname]);
  useEffect(()=>{const handler=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setSearchOpen(v=>!v);}if(e.key==='Escape'){setNotificationsOpen(false);setMobileOpen(false);}};window.addEventListener('keydown',handler);return()=>window.removeEventListener('keydown',handler);},[]);
  useEffect(()=>{const open=()=>setWizardOpen(true);window.addEventListener('aeai:new-workflow',open);return()=>window.removeEventListener('aeai:new-workflow',open);},[]);
  useEffect(()=>{if(!notificationsOpen)return;const close=(e:MouseEvent)=>{if(notificationsRef.current&&!notificationsRef.current.contains(e.target as Node))setNotificationsOpen(false);};document.addEventListener('pointerdown',close);return()=>document.removeEventListener('pointerdown',close);},[notificationsOpen]);
  const attention=[...runs].filter(r=>r.status==='failed'||r.status==='waiting_for_approval').sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at));
  const recent=[...runs].sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at)).slice(0,5);
  const breadcrumb=allLinks.find(x=>x.path===location.pathname)?.title||(location.pathname.startsWith('/workflows/')?'Analysis results':'Workspace');
  function navLinks(items:typeof mainLinks){return items.map(item=><NavLink key={item.path} to={item.path} end={item.path==='/'} title={item.title} className={({isActive})=>`nav-link ${isActive?'nav-active':''}`}><item.icon size={18} strokeWidth={1.8}/><span className="nav-label">{item.title}</span>{item.path==='/workflows'&&attention.length>0&&<span className="nav-count">{attention.length}</span>}</NavLink>);}
  return <div className={`app-layout ux-app ${collapsed?'sidebar-collapsed':''}`}>
    {mobileOpen&&<div className="mobile-backdrop" onClick={()=>setMobileOpen(false)}/>}
    <aside className={`sidebar ${mobileOpen?'sidebar-open':''}`}>
      <Link to="/" className="brand"><div className="brand-mark"><BrainCircuit size={22}/></div><div className="brand-text"><b>AEAI<span className="brand-accent">.</span> OS</b><small>Enterprise Intelligence</small></div></Link>
      <div className="workspace-switch"><span className="workspace-avatar">W</span><span className="workspace-copy"><strong>{user?.active_workspace_id||'Default workspace'}</strong><small>{user?.organization_id||'Local environment'}</small></span></div>
      <div className="ux-sidebar-new"><button type="button" onClick={()=>setWizardOpen(true)} className="ux-new-button" aria-label="New investigation"><Plus size={17}/><span className="nav-label">New investigation</span></button></div>
      <nav className="sidebar-navigation" aria-label="Main navigation"><div className="nav-section"><div className="nav-heading">WORKSPACE</div>{navLinks(mainLinks)}</div><div className="nav-section"><div className="nav-heading">MANAGE</div>{navLinks(platformLinks)}</div>{prefs.advanced&&<div className="nav-section"><div className="nav-heading">ADVANCED</div>{navLinks(advancedLinks)}</div>}</nav>
      <div className="sidebar-bottom"><div className="environment-card"><div className="env-head"><span className={`live-dot ${health?'':'live-muted'}`}/>{health?'Platform connected':'Checking connection'}</div><p>{health?'Your local AI OS is reachable.':'Checking the FastAPI backend…'}</p><small>Development environment</small></div><a className="nav-link side-doc-link" href="/docs" target="_blank" rel="noreferrer"><BookOpen size={17}/><span className="nav-label">API documentation</span></a><a className="nav-link side-doc-link" href="/legacy-app" target="_blank" rel="noreferrer"><BookOpen size={17}/><span className="nav-label">Original UI</span></a></div>
    </aside>
    <div className="main-area"><header className="topbar ux-topbar"><div className="topbar-left"><button type="button" className="icon-button desktop-collapse" aria-label="Toggle sidebar" onClick={()=>setCollapsed(v=>!v)}><PanelLeftClose size={19}/></button><button type="button" className="icon-button mobile-toggle" aria-label="Open navigation" onClick={()=>setMobileOpen(true)}><Menu size={20}/></button><span className="topbar-crumb">Workspace</span><ChevronRight size={14} className="crumb-chevron"/><b>{breadcrumb}</b></div><div className="topbar-right">
      <button type="button" className="ux-global-search" onClick={()=>setSearchOpen(true)}><Search size={16}/><span>Search anything</span><kbd>⌘ K</kbd></button>
      <span className="backend-state"><span className={`live-dot ${health?'':'live-muted'}`}/>{health?'Connected':'Checking'}</span>
      <button type="button" className="icon-button" aria-label={`Switch to ${prefs.theme==='dark'?'light':'dark'} mode`} title="Toggle appearance" onClick={()=>updateUiPrefs({theme:prefs.theme==='dark'?'light':'dark'})}>{prefs.theme==='dark'?<Sun size={19}/>:<Moon size={19}/>}</button>
      <div className="ux-notification-wrap" ref={notificationsRef}><button type="button" className="icon-button top-icon-alert" aria-label="Notifications" aria-expanded={notificationsOpen} onClick={()=>setNotificationsOpen(v=>!v)}><Bell size={19}/>{attention.length>0&&<i/>}</button>{notificationsOpen&&<div className="ux-notifications"><strong>Recent activity</strong><span>{attention.length?`${attention.length} analyses need attention`:'No items need urgent action'}</span>{(attention.length?attention:recent).slice(0,5).map(r=><Link key={r.id} to={`/workflows/${encodeURIComponent(r.id)}`} className="ux-notification-item"><span className={`ux-activity-indicator ux-status-${r.status}`}/><span><b>{r.task}</b><small>{r.status.replaceAll('_',' ')} · {timeAgo(r.updated_at)}</small></span><ArrowRight size={14}/></Link>)}{!recent.length&&<p>Run an investigation to see activity here.</p>}</div>}</div>
      <div className="topbar-divider"/><div className="topbar-user"><span className="user-avatar">{(user?.name||user?.user_id||'L').slice(0,1).toUpperCase()}</span><div><strong>{user?.name||'Local operator'}</strong><small>{user?.roles?.[0]||'Developer'}</small></div></div>
    </div></header><div className="content"><Outlet/></div><footer className="bottomline"><span>AEAI OS · Enterprise Intelligence</span><span>Results come from your connected backend <span className="dot-separator">•</span> <Link to="/settings">Preferences</Link></span></footer></div>
    <CommandPalette open={searchOpen} onClose={()=>setSearchOpen(false)} runs={runs}/>
    {wizardOpen&&<QuickStartWizard onClose={()=>setWizardOpen(false)}/>}
  </div>;
}
