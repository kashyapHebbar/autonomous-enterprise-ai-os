import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BarChart3, BookOpenText, ChevronRight, Database, Download, Eye, FileDown, FileCode2,
  Filter, LayoutDashboard, Search, ShieldCheck, X,
} from 'lucide-react';
import type { Artifact } from '../types';
import { Empty, nice, timeAgo } from './Ui';
import {
  ARTIFACT_GROUPS, artifactDescription, artifactFilename, artifactFormat, artifactGroup,
  artifactSize, artifactTitle, artifactsByGroup, type ArtifactGroupKey,
  previewableArtifact,
} from '../lib/artifactGroups';
import { api } from '../api';
import { ArtifactPreview } from './ArtifactPreview';
import './artifact-explorer.css';

const groupIcons = {
  reports: BookOpenText,
  dashboards: LayoutDashboard,
  charts: BarChart3,
  analysis: Database,
  technical: FileCode2,
};
const nodeLabel = (value: string) => ({
  data_profile: 'Review source data', analytics: 'Calculate findings', visualization: 'Create visuals',
  report: 'Write report', investigation: 'Investigate patterns', evaluation: 'Check quality',
} as Record<string, string>)[value] ?? nice(value);

export function ArtifactExplorer({artifacts, focusNode, onClearFocus}: {
  artifacts: Artifact[];
  focusNode?: string | null;
  onClearFocus?: () => void;
}) {
  const [group, setGroup] = useState<ArtifactGroupKey | 'all'>('all');
  const [query, setQuery] = useState('');
  const [agent, setAgent] = useState('all');
  const [preview, setPreview] = useState<Artifact | null>(null);
  const closePreview = useCallback(() => setPreview(null), []);
  useEffect(() => {if (focusNode) {setAgent(focusNode);setGroup('all');}}, [focusNode]);

  const groups = useMemo(() => artifactsByGroup(artifacts), [artifacts]);
  const producers = useMemo(() => Array.from(new Set(artifacts.map(a => a.producer_node_id).filter((n): n is string => Boolean(n)))).sort(), [artifacts]);
  const filtered = useMemo(() => artifacts.filter(a => {
    if (group !== 'all' && artifactGroup(a) !== group) return false;
    if (agent !== 'all' && a.producer_node_id !== agent) return false;
    if (query.trim()) {
      const haystack = `${artifactTitle(a)} ${artifactDescription(a)} ${artifactFilename(a)} ${a.type} ${a.producer_node_id ?? ''}`.toLowerCase();
      if (!haystack.includes(query.trim().toLowerCase())) return false;
    }
    return true;
  }), [artifacts, group, agent, query]);
  const filteredGroups = useMemo(() => artifactsByGroup(filtered), [filtered]);
  const clearFilters = () => {setGroup('all');setQuery('');setAgent('all');onClearFocus?.();};

  return <section className="ae-explorer">
    <div className="ae-explorer-intro"><div><div className="ae-kicker">ORGANIZED DELIVERABLES</div><h2>Your results</h2><p>Start with a report or dashboard. Supporting facts and technical details are available when you need them.</p></div><div className="ae-output-count"><strong>{artifacts.length}</strong><span>Files & results</span></div></div>
    <div className="ae-groups" role="group" aria-label="Artifact categories">
      {ARTIFACT_GROUPS.map(def => {const Icon = groupIcons[def.key]; const count = groups[def.key].length;return <button key={def.key} type="button" className={`ae-group-tile ae-group-${def.key} ${group===def.key?'is-active':''}`} aria-pressed={group===def.key} onClick={()=>setGroup(old=>old===def.key?'all':def.key)}>
        <div className="ae-group-icon"><Icon size={20}/></div><div className="ae-group-label"><strong>{def.label}</strong><span>{def.description}</span></div><div className="ae-group-bottom"><span>{count} {count===1?'file':'files'}</span><ChevronRight size={16}/></div>
      </button>})}
    </div>
    <div className="ae-artifact-toolbar">
      <label className="ae-artifact-search"><Search size={16}/><input type="search" aria-label="Search artifacts" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Find a report, result or file…"/></label>
      <label className="ae-artifact-agent"><Filter size={15}/><select aria-label="Filter artifacts by agent" value={agent} onChange={e=>{setAgent(e.target.value);if (e.target.value==='all') onClearFocus?.();}}><option value="all">All steps</option>{producers.map(p=><option key={p} value={p}>{nodeLabel(p)}</option>)}</select></label>
      {(group!=='all'||agent!=='all'||query) && <button type="button" className="ae-clear-filters" onClick={clearFilters}><X size={14}/> Clear filters</button>}
      <span className="ae-filter-count">{filtered.length} shown</span>
    </div>
    {filtered.length === 0 ? <Empty title={artifacts.length?'No artifacts match your filters':'Outputs will appear here'} description={artifacts.length?'Try a different category, search term or agent.':'When your agents finish, reports, dashboards, charts and evidence will be grouped automatically.'}/> :
      <div className="ae-artifact-sections">{ARTIFACT_GROUPS.filter(def=>filteredGroups[def.key].length>0).map(def=>{
        const Icon = groupIcons[def.key];const items=filteredGroups[def.key];
        return <section key={def.key} className="ae-artifact-section" aria-label={def.label}>
          <div className="ae-section-heading"><div className="ae-section-icon"><Icon size={18}/></div><div><h3>{def.label}</h3><p>{def.description}</p></div><span className="ae-section-count">{items.length}</span></div>
          <div className="ae-artifact-list">{items.map(a=>{const Icon2 = groupIcons[artifactGroup(a)]; const canPreview=previewableArtifact(a);return <article key={a.id} className={`ae-artifact-item ${a.type==='report'&&artifactFormat(a)==='html'?'ae-artifact-hero-item':''}`}>
            <div className="ae-file-icon"><Icon2 size={19}/></div>
            <div className="ae-file-main"><strong title={artifactTitle(a)}>{artifactTitle(a)}</strong><div className="ae-file-sub"><span>{artifactDescription(a)}</span><span className="ae-file-separator">·</span><span>{nodeLabel(a.producer_node_id??'source')}</span></div></div>
            <div className="ae-file-meta"><span className="ae-format-tag">{artifactFormat(a).toUpperCase()}</span><small>{artifactSize(a)} · {timeAgo(a.created_at)}</small></div>
            <div className="ae-file-actions"><button type="button" className="btn btn-secondary" onClick={()=>setPreview(a)}><Eye size={15}/>{canPreview?'Preview':'Details'}</button>{canPreview && artifactFormat(a) === 'html' && <button type="button" className="btn ae-pdf-list-button" title="Preview this HTML report and export to PDF" onClick={() => setPreview(a)}><FileDown size={15}/> <span>PDF</span></button>}{canPreview&&<a className="btn ae-download-button" href={api.artifactUrl(a.run_id,a.id,true)} aria-label={`Download ${artifactTitle(a)}`}><Download size={15}/> <span>Download</span></a>}</div>
          </article>})}</div>
        </section>;
      })}</div>}
    <div className="ae-explorer-foot"><ShieldCheck size={16}/><span>Every file is linked to the originating workflow. The source dataset remains a reference, not a downloadable generated file.</span></div>
    {preview&&<ArtifactPreview key={preview.id} artifact={preview} artifacts={artifacts} onClose={closePreview}/>}
  </section>;
}
