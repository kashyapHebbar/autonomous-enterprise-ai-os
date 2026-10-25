import { ArrowUpRight, Database, GitBranch } from 'lucide-react';
import { Link } from 'react-router-dom';
import { timeAgo, Status } from './Ui';
import type { Run } from '../types';

export default function RunTable({runs}: {runs: Run[]}) {
  return <div className="table-wrap"><table className="data-table"><thead><tr><th>WORKFLOW</th><th>STATUS</th><th>DATA</th><th>UPDATED</th><th aria-label="Open"/></tr></thead><tbody>{runs.map(r=><tr key={r.id}><td><Link to={`/workflows/${encodeURIComponent(r.id)}`} className="row-title"><span className="row-symbol"><GitBranch size={16}/></span><span><strong>{r.task}</strong><small>{r.id.slice(0,17)}…</small></span></Link></td><td><Status status={r.status}/></td><td><span className="table-muted"><Database size={14}/>{r.dataset_artifact_id?'Attached':'None'}</span></td><td><span className="table-muted">{timeAgo(r.updated_at)}</span></td><td><Link className="table-go" to={`/workflows/${encodeURIComponent(r.id)}`} title="Open workflow"><ArrowUpRight size={16}/></Link></td></tr>)}</tbody></table></div>;
}
