import type { Analysis, VisualizationCell, VisualizationCube } from '../types';

export type VizSection = 'spending' | 'risk' | 'opportunities' | 'quality' | 'relationships';
export type VizKind = 'bar' | 'horizontal' | 'line' | 'area' | 'donut' | 'treemap' | 'stacked' | 'heatmap' | 'scatter' | 'waterfall' | 'box';
export type VizUnit = 'money' | 'count' | 'score' | 'percent';
export interface VizDatum { name: string; value: number; secondary?: number; count?: number; [key: string]: string | number | undefined }
export interface VizSpec {
  id: string; section: VizSection; title: string; description: string;
  kind: VizKind; allowed: VizKind[]; unit: VizUnit; data: VizDatum[];
  series?: string[]; note?: string;
}
export type VizFilters = {supplier: string; category: string; department: string; month: string};
export const EMPTY_FILTERS: VizFilters = {supplier:'',category:'',department:'',month:''};
export const SECTION_LABELS: Record<VizSection,string> = {
  spending:'Spending',risk:'Risk & anomalies',opportunities:'Savings & forecasts',
  quality:'Data quality',relationships:'Comparisons',
};
const num=(x:unknown):number|null=>typeof x==='number'&&Number.isFinite(x)?x:null;
const obj=(x:unknown):Record<string,unknown>=>x&&typeof x==='object'&&!Array.isArray(x)?x as Record<string,unknown>:{};
const list=(x:unknown):Record<string,unknown>[]=>Array.isArray(x)?x.map(obj):[];
const txt=(x:unknown):string=>typeof x==='string'?x.slice(0,90):'';
const points=(entries:Record<string,unknown>[],label:string,measure:string):VizDatum[]=>entries.map(e=>({name:txt(e[label]),value:num(e[measure])??NaN})).filter(p=>p.name&&Number.isFinite(p.value)).slice(0,60);
const spec=(section:VizSection,id:string,title:string,description:string,kind:VizKind,allowed:VizKind[],unit:VizUnit,data:VizDatum[],note?:string,series?:string[]):VizSpec|null=>
  data.length?{section,id,title,description,kind,allowed,unit,data,note,series}:null;

export function visibleCells(cube:VisualizationCube|undefined, filters:VizFilters):VisualizationCell[] {
  return (cube?.cells??[]).filter(c=>(Object.keys(filters) as Array<keyof VizFilters>).every(k=>!filters[k]||c[k]===filters[k]));
}
export function valuesFor(cube:VisualizationCube|undefined,key:keyof VizFilters):string[]{
  return [...new Set((cube?.cells??[]).map(c=>c[key]).filter(Boolean))].sort((a,b)=>a.localeCompare(b)).slice(0,120);
}
function aggregate(cells:VisualizationCell[],key:keyof VizFilters):VizDatum[]{
  const groups=new Map<string,{value:number;count:number}>();
  for(const c of cells){const label=c[key];if(!label)continue;const old=groups.get(label)||{value:0,count:0};old.value+=c.amount;old.count+=c.transactions;groups.set(label,old);}
  return [...groups].map(([name,v])=>({name,value:Number(v.value.toFixed(4)),count:v.count}));
}
function grid(cells:VisualizationCell[],row:keyof VizFilters,column:keyof VizFilters):VizDatum[]{
  const groups=new Map<string,VizDatum>();
  for(const c of cells){const a=c[row],b=c[column];if(!a||!b)continue;
    const old=groups.get(a)||{name:a,value:0};old[b]=((old[b] as number)||0)+c.amount;old.value+=c.amount;groups.set(a,old);
  }
  return [...groups.values()].map(v=>({...v,value:Number(v.value.toFixed(4))}));
}
const riskScore=(e:Record<string,unknown>)=>({name:txt(e.supplier),value:num(e.risk_score)??NaN,secondary:num(e.spend)??undefined});

export function deriveCharts(analysis:Analysis|undefined,cube:VisualizationCube|undefined,filters:VizFilters):VizSpec[]{
  if(!analysis)return [];
  const filtered=Object.values(filters).some(Boolean);
  const candidates:Array<VizSpec|null>=[];
  const add=(chart:VizSpec|null)=>{if(chart)candidates.push(chart);};
  const cells=visibleCells(cube,filters);
  // All filtered charts refer exclusively to released multi-dimensional cohorts.
  if(filtered){
    for(const [key,title] of ([['supplier','Supplier spending'],['category','Category spending'],['department','Department spending'],['month','Monthly spending']] as const)){
      const data=aggregate(cells,key).sort((a,b)=>key==='month'?a.name.localeCompare(b.name):b.value-a.value);
      add(spec('spending',`filtered-${key}`,title,'Only privacy-eligible transactions matching all selected filters.',key==='month'?'line':'horizontal',key==='month'?['line','area','bar']:['horizontal','bar','donut','treemap'],'money',data));
    }
  }else{
    const supplier=points(list(analysis.spend_by_supplier),'supplier','spend').sort((a,b)=>b.value-a.value);
    const category=points(list(analysis.spend_by_category),'category','spend').sort((a,b)=>b.value-a.value);
    const trend=points(list(analysis.spend_trend),'month','spend').sort((a,b)=>a.name.localeCompare(b.name));
    const genericSeries=points(list(analysis.time_series),'period','value').sort((a,b)=>a.name.localeCompare(b.name));
    const measures=points(list(analysis.measure_summaries),'column','sum');
    add(spec('spending','monthly-trend','Monthly spending trend','How verified spend changes across recorded months.','area',['area','line','bar','waterfall'],'money',trend.length?trend:genericSeries));
    add(spec('spending','supplier-totals','Spending by supplier','Compare your largest suppliers and explore concentration.','horizontal',['horizontal','bar','donut','treemap'],'money',supplier.length?supplier:measures));
    add(spec('spending','category-share','Category spending mix','Where the recorded budget was allocated.','donut',['donut','bar','horizontal','treemap'],'money',category));
    add(spec('spending','monthly-change','Monthly spending changes','Contribution of each period to changes in the recorded trend.','waterfall',['waterfall','bar','line'],'money',trend.length>=2?trend:[]));
    const risks=list(analysis.supplier_risk_profiles).map(riskScore).filter(r=>r.name&&Number.isFinite(r.value)).sort((a,b)=>b.value-a.value);
    add(spec('risk','supplier-risk','Supplier risk scores','Heuristic risk scores, not confirmed fraud or compliance findings.','horizontal',['horizontal','bar','donut'],'score',risks));
    add(spec('risk','risk-vs-spend','Spending vs. risk score','Compare supplier spending and heuristic risk scores; correlation is not causation.','scatter',['scatter','bar'],'score',risks.filter(r=>r.secondary!==undefined)));
    const anomaly=list(analysis.anomalies);
    const severity=new Map<string,number>();const signals=new Map<string,number>();
    for(const a of anomaly){const s=txt(a.severity)||'Unclassified';severity.set(s,(severity.get(s)||0)+1);
      for(const signal of list(a.signals)){const name=txt(signal.label)||txt(signal.code);if(name)signals.set(name,(signals.get(name)||0)+1);}}
    add(spec('risk','anomaly-severity','Flagged items by severity','Counts of flagged transactions by rule-based severity.','donut',['donut','bar','horizontal'],'count',[...severity].map(([name,value])=>({name,value}))));
    add(spec('risk','anomaly-signals','Most common risk signals','A flagged item may have multiple signals; counts may overlap.','bar',['bar','horizontal','treemap'],'count',[...signals].map(([name,value])=>({name,value})).sort((a,b)=>b.value-a.value)));
    const opportunity=list(analysis.savings_opportunities).map((o,i)=>({name:txt(o.title)||txt(o.type).replaceAll('_',' ')||`Opportunity ${i+1}`,value:num(o.estimated_savings)??NaN})).filter(p=>Number.isFinite(p.value));
    add(spec('opportunities','savings','Estimated savings opportunities','Heuristic estimates—not confirmed or realized savings.','bar',['bar','horizontal','donut','treemap'],'money',opportunity));
    const forecast=list(obj(analysis.spend_forecast).forecast).map(f=>({name:txt(f.month),value:num(f.predicted_spend)??NaN})).filter(p=>p.name&&Number.isFinite(p.value));
    add(spec('opportunities','forecast','Baseline spending forecast','Simple projection based on recorded trends; not a guaranteed outcome.','area',['area','line','bar'],'money',forecast,'Projection only; inspect the original forecast report for uncertainty bounds.'));
    const missing=list(analysis.missing_data_risks);
    const missingCounts=new Map<string,number>();
    for(const item of missing){const role=txt(item.field_role)||txt(item.column);const count=num(item.missing_count);if(role&&count!==null)missingCounts.set(role,count);}
    const dataset=obj(analysis.dataset);const valid=num(dataset.valid_amount_rows),invalid=num(dataset.invalid_amount_rows);
    add(spec('quality','data-validity','Amount-field completeness','Valid versus invalid amount values in the recorded dataset.','donut',['donut','bar'],'count',valid!==null&&invalid!==null?[{name:'Valid amount',value:valid},{name:'Invalid amount',value:invalid}]:[]));
    add(spec('quality','missing-fields','Missing or inconsistent fields','Recorded counts from data quality checks.','horizontal',['horizontal','bar'],'count',[...missingCounts].map(([name,value])=>({name,value}))));
    add(spec('quality','monthly-distribution','Distribution of monthly totals','Distribution of aggregated monthly spending, not individual transaction amounts.','box',['box','bar'],'money',trend.length>=4?trend:[]));
  }
  // Fine-grained cross-filter views can only use released privacy-safe cohort cells.
  if(cells.length){
    const crosses: Array<[keyof VizFilters,keyof VizFilters,string,string]> = [
      ['supplier','category','Supplier × category','Supplier-category spending matrix'],
      ['month','category','Category × month','Category spending over time'],
      ['month','department','Department × month','Department spending across months'],
    ];
    for(const [row,column,title,description] of crosses){
      const data=grid(cells,row,column).sort((a,b)=>row==='month'?a.name.localeCompare(b.name):b.value-a.value);
      const series=[...new Set(cells.map(c=>c[column]).filter(Boolean))].sort();
      if(series.length<2||data.length<2)continue;
      add(spec('relationships',`${row}-${column}`,title,description,'stacked',['stacked','heatmap'],'money',data,undefined,series));
    }
  }
  return candidates.filter((x):x is VizSpec=>Boolean(x));
}

export function formatViz(value:number,unit:VizUnit,currency='USD'):string{
  const prefix=unit==='money'?({USD:'$',INR:'₹',EUR:'€',GBP:'£',JPY:'¥'} as Record<string,string>)[currency]||`${currency} `:'';
  const suffix=unit==='percent'?'%':'';
  return `${prefix}${Number(value).toLocaleString('en-IN',{maximumFractionDigits:unit==='money'?2:1})}${suffix}`;
}
