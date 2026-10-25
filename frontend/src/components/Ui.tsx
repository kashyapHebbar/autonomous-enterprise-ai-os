import { ArrowUpRight, CircleAlert, Inbox, LoaderCircle, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';

export const formatNumber = (value: number | null | undefined, digits = 0) => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('en-IN', {maximumFractionDigits: digits}).format(value) : '—';
export const nice = (value: string | null | undefined) => String(value ?? 'unknown').replaceAll('_', ' ').replaceAll('-', ' ').replace(/\b\w/g, c => c.toUpperCase());
export const timeAgo = (value: string | null | undefined) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(+date)) return '—';
  const minutes = Math.max(0, Math.round((Date.now() - +date) / 60000));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  if (minutes < 10080) return `${Math.floor(minutes / 1440)}d ago`;
  return date.toLocaleDateString();
};
export function Status({status}: {status: string}) {
  const key = status.toLowerCase();
  const cls = ['completed','succeeded','ok','connected','resolved','approved'].includes(key) ? 'good' : ['failed','blocked','denied','critical','high'].includes(key) ? 'bad' : ['running','investigating','queued'].includes(key) ? 'info' : ['waiting_for_approval','pending','new','medium'].includes(key) ? 'warn' : 'neutral';
  return <span className={`status status-${cls}`}><span className="status-dot" />{nice(status)}</span>;
}
export function PageHeader({eyebrow, title, description, action}: {eyebrow: string; title: string; description: string; action?: ReactNode}) {
  return <div className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action && <div className="page-actions">{action}</div>}</div>;
}
export function Metric({label, value, detail, icon}: {label: string; value: ReactNode; detail?: string; icon: ReactNode}) {
  return <div className="metric"><div className="metric-top"><span>{label}</span><span className="metric-icon">{icon}</span></div><div className="metric-value">{value}</div><div className="metric-detail">{detail || 'Based on current platform data'}</div></div>;
}
export function Panel({title, description, action, children, className = ''}: {title: string; description?: string; action?: ReactNode; children: ReactNode; className?: string}) {
  return <section className={`panel ${className}`}><div className="panel-head"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{action}</div>{children}</section>;
}
export function Empty({title, description, action}: {title: string; description: string; action?: ReactNode}) {
  return <div className="empty-state"><span className="empty-symbol"><Inbox size={23}/></span><strong>{title}</strong><p>{description}</p>{action}</div>;
}
export function ErrorBox({error}: {error: unknown}) {
  return <div className="error-box" role="alert"><CircleAlert size={18}/><span>{error instanceof Error ? error.message : String(error)}</span></div>;
}
export function Loading({label='Loading live platform data…'}: {label?: string}) { return <div className="loading"><LoaderCircle size={19} className="spin"/>{label}</div>; }
export function Refresh({onClick, loading = false}: {onClick: () => void; loading?: boolean}) {return <button type="button" className="btn btn-secondary" onClick={onClick} disabled={loading}><RefreshCw size={15} className={loading?'spin':''}/> Refresh</button>;}
export function External({href, children}: {href: string; children: ReactNode}) {return <a className="external-link" href={href} target="_blank" rel="noreferrer">{children}<ArrowUpRight size={14}/></a>;}
