import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Copy, Download, FileDown, FileText, GitBranch, Info, LoaderCircle, X } from 'lucide-react';
import { api } from '../api';
import type { Artifact } from '../types';
import { nice } from './Ui';
import { artifactDescription, artifactFilename, artifactFormat, artifactSize, artifactTitle, previewableArtifact } from '../lib/artifactGroups';

type PreviewTab = 'preview' | 'details' | 'lineage';

function MarkdownContent({content}: {content: string}) {
  return <div className="ae-markdown">{content.split(/\r?\n/).map((line, index) => {
    if (/^###\s/.test(line)) return <h4 key={index}>{line.replace(/^###\s/, '')}</h4>;
    if (/^##\s/.test(line)) return <h3 key={index}>{line.replace(/^##\s/, '')}</h3>;
    if (/^#\s/.test(line)) return <h2 key={index}>{line.replace(/^#\s/, '')}</h2>;
    if (/^[-*]\s/.test(line)) return <p className="ae-markdown-bullet" key={index}>{line.replace(/^[-*]\s/, '• ')}</p>;
    if (/^\d+[.)]\s/.test(line)) return <p className="ae-markdown-bullet" key={index}>{line}</p>;
    if (/^\|/.test(line)) return <pre key={index}>{line}</pre>;
    return line.trim() ? <p key={index}>{line}</p> : <div key={index} className="ae-markdown-space"/>;
  })}</div>;
}

export function ArtifactPreview({artifact, artifacts, onClose}: {artifact: Artifact; artifacts: Artifact[]; onClose: () => void}) {
  const [tab, setTab] = useState<PreviewTab>('preview');
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [reportTheme, setReportTheme] = useState<'dark' | 'light'>(
    () => document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
  );
  const [printError, setPrintError] = useState('');
  const format = artifactFormat(artifact);
  const url = api.artifactUrl(artifact.run_id, artifact.id);
  const sourceMap = new Map(artifacts.map(a => [a.id, a]));
  const parents = artifact.source_artifact_ids.map(id => sourceMap.get(id)).filter((a): a is Artifact => Boolean(a));
  const children = artifacts.filter(a => a.source_artifact_ids.includes(artifact.id));

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const beforeOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = beforeOverflow; previous?.focus(); };
  }, [onClose]);

  // The main React app owns the theme. Keep generated HTML in sync without
  // enabling scripts inside the sandboxed report/document iframe.
  useEffect(() => {
    const sync = () => setReportTheme(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    sync();
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    try {
      const reportDocument = iframeRef.current?.contentDocument;
      if (reportDocument) reportDocument.documentElement.dataset.theme = reportTheme;
    } catch { /* A browser may block access to a sandboxed document. */ }
  }, [reportTheme, content, tab]);

  const printReport = () => {
    setPrintError('');
    // Print the isolated report itself, not the surrounding React application.
    // The browser dialog offers Save as PDF on Chrome, Edge and Safari.
    try {
      const reportWindow = iframeRef.current?.contentWindow;
      if (!reportWindow || !content) throw new Error('Open the report preview before exporting.');
      reportWindow.focus();
      reportWindow.print();
    } catch {
      setPrintError('Printing was blocked. Choose Open, then use Command+P (Mac) or Control+P to save the HTML report as a PDF.');
    }
  };

  useEffect(() => {
    setContent(null);
    setError(null);
    if (!previewableArtifact(artifact)) return;
    const controller = new AbortController();
    setLoading(true);
    fetch(url, {credentials: 'same-origin', signal: controller.signal})
      .then(async response => {
        if (!response.ok) throw new Error(`Preview unavailable (HTTP ${response.status})`);
        const text = await response.text();
        if (format === 'html') {
          if (text.length > 1500000) throw new Error('This HTML output is too large for an embedded preview. Use Open to view the full file.');
          return text;
        }
        if (format !== 'json') return text.slice(0, 400000) + (text.length > 400000 ? '\n\n[Preview truncated]' : '');
        try {return JSON.stringify(JSON.parse(text) as unknown, null, 2).slice(0, 400000);} catch {return text.slice(0, 400000);}
      })
      .then(value => {if (!controller.signal.aborted) setContent(value);})
      .catch(err => {if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [artifact, format, url]);

  return <div className="ae-preview-overlay" onMouseDown={event => {if (event.target === event.currentTarget) onClose();}}>
    <section className="ae-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="ae-preview-title">
      <div className="ae-preview-head">
        <span className="ae-preview-file-icon"><FileText size={21}/></span>
        <div className="ae-preview-heading"><span className="ae-kicker">ARTIFACT PREVIEW · {nice(artifact.type)}</span><h2 id="ae-preview-title">{artifactTitle(artifact)}</h2><p>{artifactDescription(artifact)} · {artifactSize(artifact)}</p></div>
        <div className="ae-preview-head-actions">
          {format === 'html' && <button type="button" className="btn ae-pdf-button" disabled={loading || !content || tab !== 'preview'} title="Print this report. Select Save as PDF in the browser dialog." onClick={printReport}><FileDown size={15}/> Save as PDF</button>}
          {previewableArtifact(artifact) && <><a className="btn btn-secondary" href={url} target="_blank" rel="noopener noreferrer"><ArrowUpRight size={15}/> Open</a><a className="btn btn-primary" href={api.artifactUrl(artifact.run_id, artifact.id, true)}><Download size={15}/> Download</a></>}
          <button ref={closeRef} type="button" className="ae-close" aria-label="Close preview" onClick={onClose}><X size={20}/></button>
        </div>
      </div>
      {printError && <div className="ae-pdf-warning" role="alert">{printError}</div>}
      <div className="ae-preview-tabs" role="tablist" aria-label="Artifact information">
        {([['preview','Preview'],['details','Details'],['lineage','Lineage']] as const).map(([key,label]) => <button type="button" role="tab" aria-selected={tab === key} key={key} className={tab===key?'selected':''} onClick={()=>setTab(key)}>{key==='lineage'?<GitBranch size={15}/>:key==='details'?<Info size={15}/>:<FileText size={15}/>} {label}</button>)}
      </div>
      <div className="ae-preview-body" role="tabpanel">
        {tab === 'preview' ? !previewableArtifact(artifact) ? <div className="ae-preview-empty">This is a dataset reference, not a downloadable generated output. The source URI is available in Details.</div> : loading ? <div className="ae-preview-state"><LoaderCircle size={19} className="spin"/> Loading artifact…</div> : error ? <div className="ae-preview-error" role="alert">{error}</div> : format === 'html' ? <div className="ae-iframe-wrap"><div className="ae-iframe-note">Read-only preview · PDF uses your browser’s print dialog · Scripts and navigation stay disabled</div><iframe ref={iframeRef} className="ae-artifact-iframe" title={`Preview: ${artifactTitle(artifact)}`} srcDoc={content ?? ''} sandbox="allow-same-origin allow-modals" referrerPolicy="no-referrer" onLoad={() => {try {const doc = iframeRef.current?.contentDocument;if (doc) doc.documentElement.dataset.theme = reportTheme;} catch { /* Sandbox does not grant scripts or navigation. */ }}}/></div> : format === 'markdown' ? <MarkdownContent content={content ?? ''}/> : <pre className="ae-code-preview">{content ?? 'Empty output'}</pre>
        : tab === 'details' ? <div className="ae-detail-grid"><dl>
          {[['Original filename', artifactFilename(artifact)], ['Artifact ID', artifact.id], ['Type', nice(artifact.type)], ['Created', new Date(artifact.created_at).toLocaleString()], ['Producer agent', artifact.producer_node_id ?? 'External source'], ['Content type', artifact.content_type ?? 'Not specified'], ['Size', artifactSize(artifact)], ['Storage', artifact.storage_backend ?? 'Reference'], ['Source URI', artifact.uri]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl><div><h3>Recorded metadata</h3><pre className="ae-code-preview">{JSON.stringify(artifact.metadata, null, 2)}</pre><button className="btn btn-secondary" onClick={()=>{void navigator.clipboard?.writeText(artifact.id);}}><Copy size={14}/> Copy artifact ID</button></div></div>
        : <div className="ae-lineage"><h3>Artifact relationships</h3><p>Connections are based on the lineage saved by your agents.</p><div className="ae-lineage-grid"><div><strong>Source artifacts ({artifact.source_artifact_ids.length})</strong>{artifact.source_artifact_ids.length ? artifact.source_artifact_ids.map(id=><div className="ae-lineage-item" key={id}><GitBranch size={15}/>{sourceMap.has(id)?artifactTitle(sourceMap.get(id)!):id}</div>) : <p>No recorded upstream artifacts.</p>}</div><div><strong>Derived artifacts ({children.length})</strong>{children.length ? children.map(a=><div className="ae-lineage-item" key={a.id}><GitBranch size={15}/>{artifactTitle(a)}</div>) : <p>No downstream artifacts recorded in this run.</p>}</div></div>{parents.length > 0 && <p className="ae-lineage-foot">{parents.length} source records are available in this workflow.</p>}</div>}
      </div>
    </section>
  </div>;
}
