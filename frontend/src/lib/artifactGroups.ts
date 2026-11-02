import type { Artifact } from '../types';

export type ArtifactGroupKey = 'reports' | 'dashboards' | 'charts' | 'analysis' | 'technical';
export interface ArtifactGroupDefinition {
  key: ArtifactGroupKey;
  label: string;
  description: string;
  icon: 'report' | 'dashboard' | 'chart' | 'analysis' | 'technical';
}

export const ARTIFACT_GROUPS: ArtifactGroupDefinition[] = [
  {key: 'reports', label: 'Reports & recommendations', description: 'Findings explained in plain language', icon: 'report'},
  {key: 'dashboards', label: 'Dashboards', description: 'Explore key results at a glance', icon: 'dashboard'},
  {key: 'charts', label: 'Charts', description: 'Visual breakdowns of the data', icon: 'chart'},
  {key: 'analysis', label: 'Facts & quality checks', description: 'Numbers and checks behind the findings', icon: 'analysis'},
  {key: 'technical', label: 'Technical files', description: 'Supporting code and source references', icon: 'technical'},
];

const metadataString = (artifact: Artifact, key: string): string => {
  const value = artifact.metadata?.[key];
  return typeof value === 'string' ? value.trim() : '';
};

export function artifactGroup(artifact: Artifact): ArtifactGroupKey {
  // JSON evidence is supporting data, not a human-readable executive report.
  if (metadataString(artifact, 'edition') === 'investigation_evidence') return 'analysis';
  if (artifact.type === 'report') return 'reports';
  if (artifact.type === 'dashboard') return 'dashboards';
  if (artifact.type === 'chart') return 'charts';
  if (['kpi_table', 'schema_profile', 'quality_report', 'evaluation'].includes(artifact.type)) return 'analysis';
  return 'technical';
}

export function artifactFilename(artifact: Artifact): string {
  const metadataFile = artifact.metadata?.filename;
  if (typeof metadataFile === 'string' && metadataFile.trim()) return metadataFile.split('/').at(-1) ?? metadataFile;
  return artifact.storage_key?.split('/').at(-1) ?? artifact.uri?.split('/').at(-1) ?? artifact.id;
}

export function isHtmlArtifact(artifact: Artifact): boolean {
  return artifact.content_type?.toLowerCase().includes('text/html') === true ||
    artifact.metadata?.format === 'html' || /\.html?$/i.test(artifactFilename(artifact));
}

export function artifactTitle(artifact: Artifact): string {
  const edition = metadataString(artifact, 'edition');
  const generic = metadataString(artifact, 'analysis_type') === 'generic';
  // Saved original titles are NOT changed. These are UI-only display names.
  if (edition === 'investigation_report') return 'AI Investigation Findings';
  if (edition === 'investigation_evidence') return 'Evidence Supporting the Findings';
  if (edition === 'ai_briefing') return 'AI Insights & Next Steps';
  if (edition === 'executive') return generic ? 'Executive Data Summary' : 'Executive Spending Report';
  if (artifact.type === 'dashboard') return generic ? 'Data Insights Dashboard' : 'Spending & Risk Dashboard';
  if (artifact.type === 'schema_profile') return 'Dataset Overview';
  if (artifact.type === 'quality_report') return 'Data Quality Check';
  if (artifact.type === 'kpi_table') return generic ? 'Key Numbers & Trends' : 'Spending Figures & Findings';
  if (artifact.type === 'evaluation') return 'Report Quality Check';
  if (artifact.type === 'code') return 'Analysis Script (Technical)';
  if (artifact.type === 'dataset') return 'Original Dataset (Reference)';
  if (artifact.type === 'report' && artifact.metadata?.format === 'markdown') return 'Detailed Analysis (Text Version)';
  // Existing chart titles are already meaningful and dataset-specific.
  const name = metadataString(artifact, 'title');
  if (name) return name;
  if (artifact.type === 'report' && isHtmlArtifact(artifact)) return 'Executive Report';
  return artifactFilename(artifact).replace(/\.[^/.]+$/, '').replaceAll('_', ' ').replaceAll('-', ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export function artifactDescription(artifact: Artifact): string {
  const edition = metadataString(artifact, 'edition');
  if (edition === 'investigation_report') return 'Read the extra checks and findings selected by AI';
  if (edition === 'investigation_evidence') return 'Verified figures and source references for the investigation';
  if (edition === 'ai_briefing') return 'AI-written explanation of what deserves attention';
  if (edition === 'executive') return 'A complete business summary with recommendations';
  switch (artifact.type) {
    case 'dashboard': return 'Explore your results using interactive visuals';
    case 'chart': return 'A closer look at one pattern in your data';
    case 'schema_profile': return 'See columns, types and how the dataset is organized';
    case 'quality_report': return 'Find missing values and possible data issues';
    case 'kpi_table': return 'Calculated figures and analysis results';
    case 'evaluation': return 'See whether the report passed its checks';
    case 'code': return 'Python code used for the analysis';
    case 'dataset': return 'The source dataset used in this workflow';
    case 'report': return 'A detailed written summary of the analysis';
    default: return 'Supporting file produced by the workflow';
  }
}

export function previewableArtifact(artifact: Artifact): boolean { return artifact.type !== 'dataset'; }

export function artifactFormat(artifact: Artifact): 'html' | 'json' | 'markdown' | 'text' {
  if (isHtmlArtifact(artifact)) return 'html';
  const filename = artifactFilename(artifact).toLowerCase();
  const ct = String(artifact.content_type ?? '').toLowerCase();
  if (ct.includes('json') || filename.endsWith('.json')) return 'json';
  if (ct.includes('markdown') || filename.endsWith('.md')) return 'markdown';
  return 'text';
}

export function artifactSize(artifact: Artifact): string {
  if (artifact.size_bytes == null) return 'External reference';
  if (artifact.size_bytes < 1024) return `${artifact.size_bytes} B`;
  if (artifact.size_bytes < 1024 * 1024) return `${(artifact.size_bytes / 1024).toFixed(1)} KB`;
  return `${(artifact.size_bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function artifactsByGroup(artifacts: Artifact[]): Record<ArtifactGroupKey, Artifact[]> {
  const groups: Record<ArtifactGroupKey, Artifact[]> = {reports: [], dashboards: [], charts: [], analysis: [], technical: []};
  for (const artifact of artifacts) groups[artifactGroup(artifact)].push(artifact);
  for (const key of Object.keys(groups) as ArtifactGroupKey[]) {
    groups[key].sort((a, b) => {
      if (key === 'reports' && isHtmlArtifact(a) !== isHtmlArtifact(b)) return isHtmlArtifact(a) ? -1 : 1;
      return +new Date(b.created_at) - +new Date(a.created_at);
    });
  }
  return groups;
}
