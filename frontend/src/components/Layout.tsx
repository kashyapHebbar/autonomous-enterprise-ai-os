import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { Activity, Bell, BookOpen, BrainCircuit, ChevronDown, ChevronRight, CircleHelp, Database, FileStack, FlaskConical, GitBranch, LayoutDashboard, Menu, Moon, PanelLeftClose, Search, ShieldCheck, Sparkles, Sun, X } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { timeAgo } from './Ui';

type MenuItem = {path: string; title: string; icon: typeof LayoutDashboard};
const sections: Array<{heading: string; items: MenuItem[]}> = [
  {heading: 'WORKSPACE', items: [
    {path: '/', title: 'Command center', icon: LayoutDashboard},
    {path: '/workflows', title: 'Workflows', icon: GitBranch},
    {path: '/intelligence', title: 'Intelligence', icon: Sparkles},
    {path: '/investigations', title: 'Investigations', icon: Search},
  ]},
  {heading: 'PLATFORM', items: [
    {path: '/data', title: 'Data & connectors', icon: Database},
    {path: '/artifacts', title: 'Reports & artifacts', icon: FileStack},
    {path: '/governance', title: 'Governance', icon: ShieldCheck},
    {path: '/observability', title: 'Observability', icon: Activity},
  ]},
];
function useTheme() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => localStorage.getItem('aeai-theme') === 'light' ? 'light' : 'dark');
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('aeai-theme', theme); }, [theme]);
  return { theme, toggle: () => setTheme(prev => prev === 'dark' ? 'light' : 'dark') };
}
export default function Layout() {
  const {theme, toggle} = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);
  const {data: user} = useQuery({queryKey: ['me'], queryFn: api.me, retry: false});
  const {data: health} = useQuery({queryKey: ['health'], queryFn: api.health, retry: false, refetchInterval: 30000});
  const {data: runs=[]} = useQuery({queryKey: ['runs'], queryFn: api.runs, refetchInterval: 7000});
  const awaiting = runs.filter(r => r.status === 'waiting_for_approval').length;
  const breadcrumb = sections.flatMap(s => s.items).find(i => i.path === location.pathname)?.title || (location.pathname.includes('/workflows/') ? 'Workflow details' : 'Workspace');
  return <div className={`app-layout ${collapsed?'sidebar-collapsed':''}`}>
    {mobileOpen && <div className="mobile-backdrop" onClick={() => setMobileOpen(false)}/>}
    <aside className={`sidebar ${mobileOpen?'sidebar-open':''}`}>
      <div className="brand"><div className="brand-mark"><BrainCircuit size={22} strokeWidth={2.1}/></div><div className="brand-text"><b>AEAI<span className="brand-accent">.</span> OS</b><small>Enterprise AI Platform</small></div><button className="icon-button mobile-close" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X size={17}/></button></div>
      <div className="workspace-switch"><span className="workspace-avatar">W</span><span className="workspace-copy"><strong>{user?.active_workspace_id || 'Default workspace'}</strong><small>{user?.organization_id || 'Local development'}</small></span><ChevronDown size={14}/></div>
      <nav className="sidebar-navigation" aria-label="Main navigation">{sections.map(section => <div className="nav-section" key={section.heading}><div className="nav-heading">{section.heading}</div>{section.items.map(item => <NavLink key={item.path} to={item.path} end={item.path === '/'} title={item.title} className={({isActive}) => `nav-link ${isActive?'nav-active':''}`}><item.icon size={18} strokeWidth={1.9}/><span className="nav-label">{item.title}</span>{item.path === '/governance' && awaiting>0 && <span className="nav-count">{awaiting}</span>}</NavLink>)}</div>)}</nav>
      <div className="sidebar-bottom"><div className="environment-card"><div className="env-head"><span className="live-dot"/> Local environment</div><p>Connected to FastAPI backend</p><small>Development mode</small></div><a className="nav-link side-doc-link" href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer"><BookOpen size={17}/><span className="nav-label">API reference</span></a><a className="nav-link side-doc-link" href="http://127.0.0.1:8000/app" target="_blank" rel="noreferrer"><CircleHelp size={17}/><span className="nav-label">Original UI</span></a></div>
    </aside>
    <div className="main-area"><header className="topbar"><div className="topbar-left"><button className="icon-button desktop-collapse" aria-label="Toggle sidebar" onClick={()=>setCollapsed(v=>!v)}>{collapsed?<ChevronRight size={19}/>:<PanelLeftClose size={19}/>}</button><button className="icon-button mobile-toggle" aria-label="Open navigation" onClick={()=>setMobileOpen(true)}><Menu size={20}/></button><span className="topbar-crumb">Workspace</span><ChevronRight size={14} className="crumb-chevron"/><b>{breadcrumb}</b></div><div className="topbar-right"><span className="backend-state"><span className={`live-dot ${health?'':'live-muted'}`}/>{health?'Backend connected':'Checking backend'}</span><button className="icon-button" title="Toggle theme" aria-label="Toggle theme" onClick={toggle}>{theme === 'dark'?<Sun size={19}/>:<Moon size={19}/>}</button><NavLink to="/governance" title="Governance" className="icon-button top-icon-alert"><Bell size={19}/>{awaiting>0&&<i/>}</NavLink><div className="topbar-divider"/><div className="topbar-user"><span className="user-avatar">{(user?.name||user?.user_id||'L').slice(0,1).toUpperCase()}</span><div><strong>{user?.name || 'Local operator'}</strong><small>{user?.roles?.[0]||'Developer'}</small></div></div></div></header><div className="content"><Outlet/></div><footer className="bottomline"><span>AEAI OS · Local development</span><span><FlaskConical size={13}/> Existing FastAPI backend <span className="dot-separator">•</span> Updated {timeAgo(new Date().toISOString())}</span></footer></div>
  </div>;
}
