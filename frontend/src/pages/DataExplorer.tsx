import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, Columns3, Database, FileSpreadsheet, Info, Search, ShieldCheck } from 'lucide-react';
import { api } from '../api';
import { Empty, ErrorBox, Loading, PageHeader, Panel, formatNumber, nice } from '../components/Ui';

type ColumnInfo={name:string;type:string;missing:number|null;unique:number|null;description:string;summary:Record<string,number>};
function numericStats(value:unknown):Record<string,number>{if(!value||typeof value!=='object'||Array.isArray(value))return {};return Object.fromEntries(Object.entries(value).filter(([,v])=>typeof v==='number'&&Number.isFinite(v)).slice(0,8)) as Record<string,number>;}
function columnsFromProfile(raw:unknown):ColumnInfo[]{
  if(!raw||typeof raw!=='object')return [];
  const object=raw as Record<string,unknown>;
  const candidate=object.columns??(object.profile&&typeof object.profile==='object'?(object.profile as Record<string,unknown>).columns:null);
  if(Array.isArray(candidate))return candidate.map((x,i)=>{const c=(typeof x==='object'&&x!==null?x:{} )as Record<string,unknown>;return {name:String(c.name??c.column??`Column ${i+1}`),type:String(c.dtype??c.data_type??c.type??'Not specified'),missing:typeof (c.missing_count??c.null_count)==='number'?Number(c.missing_count??c.null_count):null,unique:typeof (c.unique_count??c.distinct_count)==='number'?Number(c.unique_count??c.distinct_count):null,description:typeof c.description==='string'?c.description:'',summary:numericStats(c.summary_statistics)};});
  if(candidate&&typeof candidate==='object')return Object.entries(candidate as Record<string,unknown>).map(([name,val])=>{const c=typeof val==='object'&&val!==null?val as Record<string,unknown>:{};return{name,type:String(c.dtype??c.type??val??'Not specified'),missing:typeof (c.missing_count??c.null_count)==='number'?Number(c.missing_count??c.null_count):null,unique:typeof (c.unique_count??c.distinct_count)==='number'?Number(c.unique_count??c.distinct_count):null,description:typeof c.description==='string'?c.description:'',summary:numericStats(c.summary_statistics)};});
  const dtypes=object.dtypes??object.column_types;
  if(dtypes&&typeof dtypes==='object'&&!Array.isArray(dtypes))return Object.entries(dtypes as Record<string,unknown>).map(([name,type])=>({name,type:String(type),missing:null,unique:null,description:'',summary:{}}));
  return [];
}
export default function DataExplorer(){
  const runsQ=useQuery({queryKey:['runs'],queryFn:api.runs});const sorted=useMemo(()=>[...(runsQ.data||[])].filter(x=>x.status==='completed').sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at)),[runsQ.data]);
  const [selected,setSelected]=useState(''),[query,setQuery]=useState('');const id=selected||sorted[0]?.id||'';
  const artifacts=useQuery({queryKey:['artifacts',id],queryFn:()=>api.artifacts(id),enabled:!!id});
  const profileArtifact=artifacts.data?.find(a=>a.type==='schema_profile');
  const raw=useQuery({queryKey:['dataset-profile',id,profileArtifact?.id],queryFn:()=>api.artifactContent(id,profileArtifact!.id),enabled:!!id&&!!profileArtifact});
  const cols=useMemo(()=>columnsFromProfile(raw.data),[raw.data]);const filtered=cols.filter(c=>`${c.name} ${c.type}`.toLowerCase().includes(query.toLowerCase()));
  const data=raw.data&&typeof raw.data==='object'?raw.data as Record<string,unknown>:{};
  const rows=data.row_count??data.rows??(data.dataset&&typeof data.dataset==='object'?(data.dataset as Record<string,unknown>).row_count:undefined);
  return <div className="page ux-data-explorer"><Link className="back-link" to="/data"><ArrowLeft size={15}/> Back to data sources</Link><PageHeader eyebrow="UNDERSTAND YOUR DATA" title="Dataset overview" description="Examine previously saved schema and quality information—without sending raw CSV rows to an AI model." action={<label className="select-shell run-selector"><Database size={15}/><select aria-label="Select analysis" value={id} onChange={e=>setSelected(e.target.value)}><option value="" disabled>Choose a completed analysis</option>{sorted.map(r=><option key={r.id} value={r.id}>{r.task.slice(0,65)}</option>)}</select></label>}/>
    {!id?<Empty title="No completed analyses yet" description="Run a workflow to collect a reusable dataset profile." action={<Link to="/workflows" className="btn btn-primary">Start an analysis <ArrowRight size={15}/></Link>}/>:artifacts.isLoading||raw.isLoading?<Loading label="Reading the saved dataset profile…"/>:artifacts.isError||raw.isError?<ErrorBox error={artifacts.error||raw.error}/>:!profileArtifact?<Empty title="Dataset profile not available" description="This analysis did not save a schema profile. Other reports may still be available in Results Library."/>:<>
      <div className="ux-data-head"><div><span className="ux-data-head-icon"><FileSpreadsheet size={24}/></span><strong>Analyzed dataset</strong><small>Read-only profile from completed workflow</small></div><div><Columns3 size={18}/><span>{cols.length?`${cols.length} known columns`:'Column details unavailable'}</span></div><div><Database size={18}/><span>{typeof rows==='number'?`${formatNumber(rows)} rows`: 'Row count not provided'}</span></div></div>
      <Panel title="Column dictionary" description="Types and quality metrics as recorded by the original profiling agent" action={<label className="ux-compact-search"><Search size={15}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Find a column" aria-label="Find a dataset column"/></label>}>
        {cols.length?<div className="ux-columns-table"><div className="ux-columns-head"><span>FIELD NAME</span><span>TYPE</span><span>MISSING VALUES</span><span>UNIQUE VALUES</span></div>{filtered.map(c=><div className="ux-column-entry" key={c.name}><div className="ux-column-row"><strong>{c.name}</strong><span>{nice(c.type)}</span><span>{c.missing===null?'Not recorded':formatNumber(c.missing)}</span><span>{c.unique===null?'Not recorded':formatNumber(c.unique)}</span></div>{(c.description||Object.keys(c.summary).length>0)&&<details className="ux-column-extra"><summary>Column meaning and statistics</summary>{c.description&&<p>{c.description}</p>}{Object.keys(c.summary).length>0&&<div>{Object.entries(c.summary).map(([key,value])=><span key={key}><strong>{nice(key)}:</strong> {formatNumber(value,3)}</span>)}</div>}</details>}</div>)}{!filtered.length&&<div className="ux-no-match">No columns match this search.</div>}</div>:<div className="ux-no-match">The saved profile does not expose a recognized column structure. The original profile remains available in the workflow's Outputs.</div>}
      </Panel><div className="inline-notice"><Info size={17}/> Only saved metadata is shown. Row-level preview is intentionally unavailable until the backend exposes a permission-checked, redacted sample endpoint.</div><div className="ux-comparison-links"><Link to={`/workflows/${encodeURIComponent(id)}`} className="btn btn-secondary"><ShieldCheck size={15}/> Open source analysis <ArrowRight size={14}/></Link></div>
    </>}
  </div>;
}
