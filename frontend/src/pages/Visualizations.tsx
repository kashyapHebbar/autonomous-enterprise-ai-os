import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, BarChart3, Bookmark, CheckCircle2, CircleAlert, Download, FilterX, GitCompareArrows, LayoutGrid, LockKeyhole, Save, ShieldCheck, Sparkles } from 'lucide-react';
import { api } from '../api';
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Ui';
import { downloadChartCSV, saveBlob, VizCard } from '../components/VizCharts';
import { deriveCharts, EMPTY_FILTERS, formatViz, SECTION_LABELS, valuesFor, visibleCells } from '../lib/vizModels';
import type { VizFilters, VizKind, VizSection } from '../lib/vizModels';
import type { Analysis } from '../types';
import '../viz-studio.css';

type View = {id:string;name:string;section:VizSection;filters:VizFilters;kinds:Record<string,VizKind>;created_at:string};
const sections: VizSection[]=['spending','risk','opportunities','quality','relationships'];
const keys: Array<keyof VizFilters>=['supplier','category','department','month'];
const labels:Record<keyof VizFilters,string>={supplier:'Supplier',category:'Category',department:'Department',month:'Month'};
function readViews(key:string):View[]{
  try {const raw=JSON.parse(localStorage.getItem(key)||'[]');if(!Array.isArray(raw))return [];
    return raw.slice(0,12).filter(v=>v&&typeof v.name==='string'&&sections.includes(v.section)&&v.filters&&typeof v.filters==='object'&&v.kinds&&typeof v.kinds==='object') as View[];
  }catch{return []}
}
export default function Visualizations(){
  const [params,setParams]=useSearchParams();const requested=params.get('run')||'';
  const [selected,setSelected]=useState('');const [section,setSection]=useState<VizSection>('spending');
  const [filters,setFilters]=useState<VizFilters>(EMPTY_FILTERS);const [kinds,setKinds]=useState<Record<string,VizKind>>({});
  const [name,setName]=useState('');const [notice,setNotice]=useState('');
  const runsQ=useQuery({queryKey:['runs'],queryFn:api.runs});
  const completed=useMemo(()=>[...(runsQ.data||[])].filter(r=>r.status==='completed').sort((a,b)=>+new Date(b.updated_at)-+new Date(a.updated_at)),[runsQ.data]);
  const id=completed.some(r=>r.id===(selected||requested))?(selected||requested):(completed[0]?.id||'');
  const artifacts=useQuery({queryKey:['artifacts',id],queryFn:()=>api.artifacts(id),enabled:!!id});
  const source=artifacts.data?.find(a=>a.type==='kpi_table'&&a.metadata?.source==='analytics_code_agent')||artifacts.data?.find(a=>a.type==='kpi_table');
  const saved=useQuery({queryKey:['visualization-source',id,source?.id],queryFn:()=>api.artifactContent(id,source!.id),enabled:!!id&&!!source});
  const cubeQ=useQuery({queryKey:['visualization-cube',id],queryFn:()=>api.visualizationCube(id),enabled:!!id,retry:false,staleTime:300000});
  const cube=cubeQ.data;const analysis=saved.data as Analysis|undefined;
  const activeFilters=keys.filter(key=>filters[key]);const filtered=activeFilters.length>0;
  const charts=useMemo(()=>deriveCharts(analysis,cube,filters),[analysis,cube,filters]);
  const visible=charts.filter(c=>c.section===section);
  const storageKey=`aeai.viz.115:${id}`;
  const [views,setViews]=useState<View[]>([]);
  useEffect(()=>{if(id){setViews(readViews(storageKey));setFilters(EMPTY_FILTERS);setKinds({});setSection('spending');setNotice('');}},[id,storageKey]);
  const availableCounts=useMemo(()=>Object.fromEntries(sections.map(s=>[s,charts.filter(c=>c.section===s).length])) as Record<VizSection,number>,[charts]);
  const eligible=visibleCells(cube,filters);
  const covered=eligible.reduce((sum,c)=>sum+c.transactions,0);
  const amount=eligible.reduce((sum,c)=>sum+c.amount,0);
  function selectRun(runId:string){setSelected(runId);setParams({run:runId});}
  function clearFilters(){setFilters(EMPTY_FILTERS);setNotice('');}
  function updateFilter(key:keyof VizFilters,value:string){setFilters(old=>({...old,[key]:value}));}
  function drilldown(chartId:string,label:string){
    const key: keyof VizFilters|undefined=chartId.includes('supplier')?'supplier':chartId.includes('category')?'category':chartId.includes('month')?'month':chartId.includes('department')?'department':undefined;
    if(!key)return;
    if(!valuesFor(cube,key).includes(label)){setNotice('This chart is from saved full-run results. No matching privacy-safe drill-down is available for that group.');return;}
    updateFilter(key,label);setNotice(`Showing privacy-eligible cohorts for ${labels[key]}: ${label}.`);
  }
  function saveView(){
    const label=name.trim().slice(0,60);if(!label){setNotice('Enter a name before saving this view.');return;}
    const view:View={id:Math.random().toString(36).slice(2),name:label,section,filters:{...filters},kinds:{...kinds},created_at:new Date().toISOString()};
    const next=[view,...views].slice(0,12);try{localStorage.setItem(storageKey,JSON.stringify(next));setViews(next);setName('');setNotice('Saved in this browser, for the selected investigation.');}catch{setNotice('Browser storage is unavailable. Export the view configuration instead.');}
  }
  function restoreView(view:View){setSection(view.section);setFilters({...EMPTY_FILTERS,...view.filters});setKinds(view.kinds);setNotice(`Loaded saved view: ${view.name}`);}
  function removeView(view:View){const next=views.filter(x=>x.id!==view.id);localStorage.setItem(storageKey,JSON.stringify(next));setViews(next);}
  function exportView(){
    const payload={schema:'aeai-visualization-view/v1',run_id:id,section,filters,kinds,chart_ids:visible.map(c=>c.id),created_at:new Date().toISOString(),notice:'Visualization settings only. Not a dataset or verified evidence export.'};
    saveBlob(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}),`aeai-dashboard-view-${id.slice(0,15)}.json`);
  }
  return <div className="page vz-page">
    <Link to="/intelligence" className="back-link"><ArrowLeft size={15}/> Back to AI Insights</Link>
    <PageHeader eyebrow="EXPLORE YOUR EVIDENCE" title="Visualization Studio" description="Interactive, evidence-backed charts and saved dashboard views—without additional Hugging Face requests."/>
    <div className="vz-hero"><div><span><Sparkles size={15}/> BUSINESS INTELLIGENCE STUDIO</span><h2>One investigation.<br/><em>Every useful perspective.</em></h2><p>Discover trends, breakdowns, anomalies, and opportunities. Change visualization types, focus on supported cohorts, and save your preferred dashboard.</p></div><div className="vz-hero-symbol" aria-hidden="true"><BarChart3 size={78}/></div></div>
    {!id?(runsQ.isLoading?<Loading label="Loading investigations…"/>:<Empty title="No completed investigation yet" description="Complete an investigation to explore its verified analytical figures." action={<Link to="/workflows" className="btn btn-primary">Create an investigation <ArrowRight size={15}/></Link>}/>):<>
      <div className="vz-source-bar"><label><span>ANALYSIS</span><select value={id} aria-label="Select a completed investigation" onChange={e=>selectRun(e.target.value)}>{completed.map(r=><option key={r.id} value={r.id}>{r.task.slice(0,95)}</option>)}</select></label><Link to={`/workflows/${encodeURIComponent(id)}`} className="btn btn-secondary"><ShieldCheck size={15}/> Source evidence <ArrowRight size={14}/></Link></div>
      {artifacts.isLoading||saved.isLoading?<Loading label="Preparing charts from verified saved results…"/>:artifacts.isError||saved.isError?<ErrorBox error={artifacts.error||saved.error}/>:!analysis?<Empty title="No analytical evidence found" description="This run did not save a machine-readable analytics output."/>:<>
        <div className="vz-summary-grid"><div><span>Chart cards</span><strong>{charts.length}</strong><small>Available for this selection</small></div><div><span>Chart families</span><strong>11</strong><small>Only compatible types appear</small></div><div><span>{filtered?'Visible transactions':'Recorded records'}</span><strong>{filtered?covered:typeof (analysis.dataset as Record<string,unknown>|undefined)?.row_count==='number'?Number((analysis.dataset as Record<string,unknown>).row_count).toLocaleString('en-IN'):'—'}</strong><small>{filtered?'Privacy-eligible cohorts':'From saved analytics'}</small></div><div><span>{filtered?'Visible cohort spend':'Verified spending'}</span><strong>{filtered?formatViz(amount,'money',String((analysis.dataset as Record<string,unknown>|undefined)?.currency||'USD')):typeof analysis.kpis?.total_spend==='number'?formatViz(analysis.kpis.total_spend,'money',String((analysis.dataset as Record<string,unknown>|undefined)?.currency||'USD')):'—'}</strong><small>{filtered?'Not a full-dataset total':'Original calculated KPI'}</small></div></div>
        <div className="vz-filters"><div className="vz-panel-title"><div><h3>Explore and filter</h3><p>Filters use privacy-safe grouped data, when available. Unsupported slices are hidden rather than estimated.</p></div><button className="vz-text-button" onClick={clearFilters} type="button"><FilterX size={15}/> Clear filters</button></div><div className="vz-filter-row">{keys.map(key=><label key={key}><span>{labels[key]}</span><select aria-label={`Filter ${labels[key]}`} value={filters[key]} onChange={e=>updateFilter(key,e.target.value)} disabled={!valuesFor(cube,key).length}><option value="">All {labels[key].toLowerCase()}s</option>{valuesFor(cube,key).map(value=><option key={value} value={value}>{value}</option>)}</select></label>)}</div>{cubeQ.isLoading&&<small>Checking eligible combinations…</small>}{filtered?<div className="vz-disclaimer"><LockKeyhole size={16}/><span>Filtered charts include only combinations containing at least two transactions. {covered} eligible transactions shown; suppressed groups are not included. These figures are not directly comparable to the full-run totals.</span></div>:<div className="vz-disclaimer"><ShieldCheck size={16}/><span>Full-run charts use saved analytical artifacts. Cross-category charts use privacy-safe grouped data. No raw invoice records are displayed.</span></div>}{cube?.note&&<small className="vz-cube-note">{cube.note}</small>}</div>
        <div className="vz-tabs" role="tablist" aria-label="Business dashboard sections">{sections.map(key=><button key={key} type="button" role="tab" aria-selected={section===key} className={section===key?'active':''} onClick={()=>setSection(key)}>{SECTION_LABELS[key]}<span>{availableCounts[key]}</span></button>)}</div>
        {visible.length?<div className="vz-chart-grid">{visible.map(spec=><VizCard key={spec.id} spec={spec} currency={String((analysis.dataset as Record<string,unknown>|undefined)?.currency||'USD')} kind={spec.allowed.includes(kinds[spec.id])?kinds[spec.id]:spec.kind} onKindChange={kind=>setKinds(old=>({...old,[spec.id]:kind}))} onSelect={label=>drilldown(spec.id,label)}/>)}</div>:<div className="vz-empty"><CircleAlert size={26}/><h3>No verified chart is available for this selection</h3><p>{filtered?'Your combination may have too few transactions to display safely. Remove one or more filters.':'This analysis does not contain the evidence necessary for charts in this section.'}</p><button className="btn btn-secondary" type="button" onClick={clearFilters}>Clear filters</button></div>}
        <div className="vz-views"><div className="vz-panel-title"><div><h3><Bookmark size={17}/> Saved dashboard views</h3><p>Save charts, filters and layout choices in this browser. These settings never modify source reports.</p></div><button className="btn btn-secondary" type="button" onClick={exportView}><Download size={14}/> Export settings</button></div><div className="vz-save-row"><label className="vz-view-name"><span>NAME THIS VIEW</span><input value={name} onChange={e=>setName(e.target.value)} maxLength={60} placeholder="e.g. Supplier risk review" aria-label="Name this dashboard view"/></label><button type="button" className="btn btn-primary" onClick={saveView}><Save size={15}/> Save view</button></div>{views.length?<div className="vz-saved-list">{views.map(v=><div key={v.id} className="vz-saved-item"><div><strong>{v.name}</strong><span>{SECTION_LABELS[v.section]} · {new Date(v.created_at).toLocaleDateString()}</span></div><button type="button" onClick={()=>restoreView(v)}><CheckCircle2 size={14}/> Open</button><button type="button" onClick={()=>removeView(v)} aria-label={`Delete saved view ${v.name}`}>Remove</button></div>)}</div>:<p className="vz-saved-empty">Your first saved dashboard view will appear here.</p>}{notice&&<p className="vz-notice" role="status">{notice}</p>}</div>
        <div className="vz-bottom-links"><Link to="/compare"><GitCompareArrows size={16}/> Compare investigations <ArrowRight size={14}/></Link><Link to="/analyst"><LayoutGrid size={16}/> Ask AI for a new calculation <ArrowRight size={14}/></Link><button type="button" onClick={()=>visible.forEach(downloadChartCSV)}><Download size={15}/> Download section tables</button></div>
      </>}
    </>}
  </div>;
}
