import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Activity, CheckCheck, CircleAlert, Filter, GitBranch, Plus, Search } from 'lucide-react';
import { api } from '../api';
import { Empty, ErrorBox, Loading, Metric, PageHeader, Panel, Refresh } from '../components/Ui';
import Composer from '../components/Composer';
import RunTable from '../components/RunTable';
export default function Workflows(){const [search,setSearch]=useState(''),[status,setStatus]=useState('all'),[showComposer,setShowComposer]=useState(false);
  const query=useQuery({queryKey:['runs'],queryFn:api.runs,refetchInterval:7000});const runs=query.data??[];
  const filtered=useMemo(()=>runs.filter(r=>(status==='all'||r.status===status) && `${r.task} ${r.id}`.toLowerCase().includes(search.toLowerCase())).sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at)),[runs,status,search]);
  return <div className="page"><PageHeader eyebrow="ORCHESTRATION" title="Workflows" description="Create, track and inspect every execution across your workspace." action={<button className="btn btn-primary" onClick={()=>setShowComposer(v=>!v)}><Plus size={17}/>{showComposer?'Close composer':'New workflow'}</button>}/>
    {showComposer&&<div className="inline-composer"><Composer compact/></div>}
    <div className="metrics-grid metrics-grid-3"><Metric label="All workflows" value={runs.length} icon={<GitBranch size={18}/>}/><Metric label="Completed" value={runs.filter(r=>r.status==='completed').length} icon={<CheckCheck size={18}/>}/><Metric label="Needs attention" value={runs.filter(r=>['failed','waiting_for_approval'].includes(r.status)).length} icon={<CircleAlert size={18}/>}/></div>
    <Panel title="Workflow history" description="Live run records from the repository" action={<Refresh onClick={()=>void query.refetch()} loading={query.isFetching}/>}><div className="filter-row"><div className="search-field"><Search size={17}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search objective or run ID" aria-label="Search workflows" /></div><div className="select-shell"><Filter size={15}/><select aria-label="Filter workflow status" value={status} onChange={e=>setStatus(e.target.value)}>{['all','pending','queued','running','waiting_for_approval','completed','failed'].map(x=><option value={x} key={x}>{x==='all'?'All statuses':x.replaceAll('_',' ')}</option>)}</select></div></div>{query.isLoading?<Loading/>:query.isError?<ErrorBox error={query.error}/>:filtered.length?<RunTable runs={filtered}/>:<Empty title="No matching workflows" description="Try another filter or create a new analysis." action={<Link to="/" className="btn btn-secondary"><Activity size={16}/> Open command center</Link>}/>}<div className="table-footer">Showing {filtered.length} of {runs.length} workflows · updates every 7 seconds</div></Panel></div>;
}
