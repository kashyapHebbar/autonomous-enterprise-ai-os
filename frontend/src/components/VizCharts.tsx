import { useRef, useState } from 'react';
import type { RefObject } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Area, AreaChart, ResponsiveContainer, XAxis, YAxis, Tooltip, Pie, PieChart, Scatter, ScatterChart, ZAxis, Treemap } from 'recharts';
import { Download, Expand, Table2 } from 'lucide-react';
import type { VizKind, VizSpec, VizUnit } from '../lib/vizModels';
import { formatViz } from '../lib/vizModels';

const palette=['#9d89ff','#46cbbb','#f2bb69','#69a9ff','#ed91ad','#ad98ed','#79c0ba','#e4a267','#7788f8','#c4d975'];
const tick={fontSize:11,fill:'var(--text-muted)'};
const tooltipStyle={background:'var(--tooltip-bg)',border:'1px solid var(--border)',color:'var(--text)',borderRadius:12,fontSize:12};
const compact=(value:unknown)=>Number(value).toLocaleString('en-US',{notation:'compact',maximumFractionDigits:1});

function DownloadSvg({target,title}:{target:RefObject<HTMLDivElement|null>;title:string}){
  const [message,setMessage]=useState('');
  function download(format:'svg'|'png'){
    const svg=target.current?.querySelector('svg');
    if(!svg){setMessage('Chart image unavailable. Use CSV or the table view.');return;}
    const clone=svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute('xmlns','http://www.w3.org/2000/svg');
    clone.setAttribute('width',String(Math.max(svg.getBoundingClientRect().width,520)));
    clone.setAttribute('height',String(Math.max(svg.getBoundingClientRect().height,300)));
    // Export a light background even if the dashboard is dark.
    clone.setAttribute('style','background:#151b2b;color:#e8eaff;font-family:Arial,sans-serif');
    const xml=new XMLSerializer().serializeToString(clone);
    const safeName=title.toLowerCase().replace(/[^a-z0-9]+/g,'-').slice(0,65);
    if(format==='svg'){
      const blob=new Blob([xml],{type:'image/svg+xml;charset=utf-8'});
      saveBlob(blob,`${safeName}.svg`);setMessage('SVG downloaded');return;
    }
    const url=URL.createObjectURL(new Blob([xml],{type:'image/svg+xml;charset=utf-8'}));
    const img=new Image();
    img.onload=()=>{
      const canvas=document.createElement('canvas');canvas.width=Math.ceil(img.width*2);canvas.height=Math.ceil(img.height*2);
      const context=canvas.getContext('2d');if(!context){setMessage('PNG export not supported in this browser.');URL.revokeObjectURL(url);return;}
      context.scale(2,2);context.fillStyle='#151b2b';context.fillRect(0,0,img.width,img.height);context.drawImage(img,0,0);
      canvas.toBlob(blob=>{if(blob){saveBlob(blob,`${safeName}.png`);setMessage('PNG downloaded')}else setMessage('Unable to export PNG');},'image/png');
      URL.revokeObjectURL(url);
    };
    img.onerror=()=>{setMessage('PNG export unavailable; try SVG.');URL.revokeObjectURL(url);};
    img.src=url;
  }
  return <div className="vz-export"><button type="button" title="Export SVG image" onClick={()=>download('svg')}><Download size={13}/> SVG</button><button type="button" title="Export PNG image" onClick={()=>download('png')}>PNG</button>{message&&<span role="status">{message}</span>}</div>;
}
export function saveBlob(blob:Blob,filename:string){const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);}
export function downloadChartCSV(spec:VizSpec){
  const columns=['name','value',...Array.from(new Set([...(spec.series||[]),...(spec.data.some(r=>r.secondary!==undefined)?['secondary']:[])]))];
  const quote=(v:unknown)=>{const raw=String(v??'');const safe=/^\s*[=+@\-\t\r]/.test(raw)?`'${raw}`:raw;return `"${safe.replace(/"/g,'""')}"`;};
  const content=[columns.map(quote).join(','),...spec.data.map(row=>columns.map(k=>quote(row[k])).join(','))].join('\r\n');
  saveBlob(new Blob(['\uFEFF'+content],{type:'text/csv;charset=utf-8'}),`${spec.id}.csv`);
}
const centerValue=(v:number,unit:VizUnit,currency:string)=>formatViz(v,unit,currency);
function CustomHeatmap({spec,currency}:{spec:VizSpec;currency:string}){
  const rows=spec.data.slice(0,16);const columns=(spec.series||[]).slice(0,12);
  const max=Math.max(...rows.flatMap(row=>columns.map(k=>Number(row[k])||0)),1);
  const w=160+columns.length*72,h=60+rows.length*36;
  return <div className="vz-heat-scroll"><svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img" aria-label={spec.title}>
    {columns.map((c,j)=><text key={c} x={165+j*72} y={27} textAnchor="middle" fontSize="10" fill="#c1c7df">{c.slice(0,12)}</text>)}
    {rows.map((row,i)=><g key={row.name}><text x="150" y={53+i*36} fontSize="10" textAnchor="end" fill="#c1c7df">{row.name.slice(0,21)}</text>{columns.map((col,j)=>{const value=Number(row[col])||0;const opacity=value>0?0.16+0.8*Math.sqrt(value/max):0.055;return <g key={col}><rect x={162+j*72} y={37+i*36} width="67" height="31" rx="5" fill="#9186fb" opacity={opacity}/><title>{row.name} / {col}: {centerValue(value,spec.unit,currency)}</title><text x={195+j*72} y={57+i*36} textAnchor="middle" fontSize="9" fill={opacity>0.7?'#0c1020':'#d6d9e8'}>{value>0?compact(value):'—'}</text></g>})}</g>)}
  </svg></div>;
}
function BoxPlot({spec,currency}:{spec:VizSpec;currency:string}){
  const sorted=spec.data.map(x=>x.value).filter(Number.isFinite).sort((a,b)=>a-b);if(sorted.length<4)return null;
  const quant=(fraction:number)=>{const pos=(sorted.length-1)*fraction,lo=Math.floor(pos),hi=Math.ceil(pos);return sorted[lo]+(sorted[hi]-sorted[lo])*(pos-lo)};
  const lo=sorted[0],q1=quant(.25),med=quant(.5),q3=quant(.75),hi=sorted[sorted.length-1];
  const px=(v:number)=>50+490*(v-lo)/Math.max(hi-lo,1);
  return <svg className="vz-boxplot-svg" viewBox="0 0 600 220" role="img" aria-label={`Distribution of ${sorted.length} grouped values`}>
    <line x1={px(lo)} x2={px(hi)} y1="98" y2="98" stroke="#a6a6bf" strokeWidth="2"/>
    <rect x={px(q1)} y="60" width={Math.max(1,px(q3)-px(q1))} height="76" rx="6" fill="#968dff" fillOpacity=".35" stroke="#968dff" strokeWidth="2"/>
    {[lo,med,hi].map((v,i)=><g key={i}><line x1={px(v)} x2={px(v)} y1={i===1?58:82} y2={i===1?139:115} stroke={i===1?'#55d7b9':'#968dff'} strokeWidth={i===1?3:2}/><text x={px(v)} y={i===1?45:152} fill="#cdd3e4" fontSize="11" textAnchor="middle">{compact(v)}</text></g>)}
    <text x="300" y="185" fill="#9ca5bc" fontSize="11" textAnchor="middle">Min · 25th percentile · Median · 75th percentile · Max</text>
    <title>{[lo,q1,med,q3,hi].map(v=>centerValue(v,spec.unit,currency)).join(' · ')}</title>
  </svg>;
}
function Waterfall({spec,currency}:{spec:VizSpec;currency:string}){
  const series=spec.data.map((r,i,all)=>{
    const prev=i>0?all[i-1].value:0;const diff=r.value-prev;
    return {...r,base:Math.min(r.value,prev),delta:Math.abs(diff),change:diff};
  });
  return <ResponsiveContainer width="100%" height="100%"><BarChart data={series} margin={{top:12,right:22,bottom:8,left:8}}>
    <CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeDasharray="3 6"/><XAxis dataKey="name" tick={tick} axisLine={false} tickLine={false}/>
    <YAxis tick={tick} axisLine={false} tickLine={false} tickFormatter={compact}/>
    <Tooltip contentStyle={tooltipStyle} formatter={(_v,_n,item)=>centerValue(Number(item.payload.change),spec.unit,currency)} labelFormatter={label=>`Change at ${label}`}/>
    <Bar dataKey="base" stackId="stack" fill="transparent" isAnimationActive={false}/>
    <Bar dataKey="delta" stackId="stack" isAnimationActive={false}>{series.map((x,i)=><Cell key={i} fill={x.change<0?'#f099a9':'#4dccb6'}/>)}</Bar>
  </BarChart></ResponsiveContainer>;
}
export function VizCanvas({spec,kind,currency,onSelect}:{spec:VizSpec;kind:VizKind;currency:string;onSelect?:(label:string)=>void}){
  const data=spec.data.slice(0,24);const chartMargin={top:15,right:17,bottom:18,left:4};
  const tooltip=<Tooltip contentStyle={tooltipStyle} formatter={v=>centerValue(Number(v),spec.unit,currency)}/>;
  const axisX=<XAxis dataKey="name" tick={tick} axisLine={false} tickLine={false} interval={0} angle={data.length>7?-24:0} textAnchor={data.length>7?'end':'middle'} height={data.length>7?65:38}/>;
  const axisY=<YAxis tick={tick} axisLine={false} tickLine={false} tickFormatter={compact}/>;
  if(kind==='heatmap')return <CustomHeatmap spec={spec} currency={currency}/>;
  if(kind==='box')return <BoxPlot spec={spec} currency={currency}/>;
  if(kind==='waterfall')return <Waterfall spec={spec} currency={currency}/>;
  if(kind==='donut')return <ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data.filter(d=>d.value>0)} nameKey="name" dataKey="value" innerRadius="48%" outerRadius="77%" paddingAngle={2} onClick={point=>onSelect?.(String(point.name))}>{data.map((r,i)=><Cell key={r.name} fill={palette[i%palette.length]}/>)}</Pie>{tooltip}</PieChart></ResponsiveContainer>;
  if(kind==='treemap')return <ResponsiveContainer width="100%" height="100%"><Treemap data={data.filter(d=>d.value>0)} dataKey="value" nameKey="name" aspectRatio={4/3} stroke="#171b2b" fill="#9d89ff">{tooltip}</Treemap></ResponsiveContainer>;
  if(kind==='scatter')return <ResponsiveContainer width="100%" height="100%"><ScatterChart margin={chartMargin}><CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 6"/><XAxis type="number" dataKey="secondary" name="Spending" tick={tick} tickFormatter={compact}/><YAxis type="number" dataKey="value" name="Risk score" tick={tick}/><ZAxis range={[75,180]}/><Tooltip cursor={{strokeDasharray:'3 3'}} contentStyle={tooltipStyle}/><Scatter data={data} fill="#9d89ff" name="Supplier">{data.map((p,i)=><Cell key={p.name} fill={palette[i%palette.length]}/>)}</Scatter></ScatterChart></ResponsiveContainer>;
  if(kind==='stacked')return <ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{...chartMargin,bottom:50}}><CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeDasharray="3 6"/>{axisX}{axisY}{tooltip}{(spec.series||[]).slice(0,12).map((key,i)=><Bar key={key} dataKey={key} name={key} stackId="s" fill={palette[i%palette.length]} maxBarSize={64}/>)}</BarChart></ResponsiveContainer>;
  if(kind==='line'||kind==='area')return <ResponsiveContainer width="100%" height="100%">{kind==='line'?<LineChart data={data} margin={chartMargin}><CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 6"/>{axisX}{axisY}{tooltip}<Line dataKey="value" name="Value" stroke="#a38fff" strokeWidth={3} dot={data.length<20?{r:3}:false} type="monotone"/></LineChart>:<AreaChart data={data} margin={chartMargin}><defs><linearGradient id={`vz-${spec.id}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#968aff" stopOpacity=".44"/><stop offset="1" stopColor="#968aff" stopOpacity=".025"/></linearGradient></defs><CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 6"/>{axisX}{axisY}{tooltip}<Area dataKey="value" name="Value" stroke="#a38fff" strokeWidth={3} fill={`url(#vz-${spec.id})`} type="monotone"/></AreaChart>}</ResponsiveContainer>;
  if(kind==='horizontal')return <ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{top:8,right:22,bottom:6,left:15}}><CartesianGrid horizontal={false} stroke="var(--chart-grid)" strokeDasharray="3 6"/><XAxis type="number" tick={tick} tickFormatter={compact}/><YAxis type="category" dataKey="name" width={115} tick={tick}/>{tooltip}<Bar dataKey="value" fill="#56c9b8" maxBarSize={23} radius={[0,5,5,0]} onClick={r=>onSelect?.(String(r.name))}/></BarChart></ResponsiveContainer>;
  return <ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={chartMargin}><CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeDasharray="3 6"/>{axisX}{axisY}{tooltip}<Bar dataKey="value" name="Value" fill="#988afa" radius={[5,5,0,0]} maxBarSize={55} onClick={r=>onSelect?.(String(r.name))}/></BarChart></ResponsiveContainer>;
}

export function VizCard({spec,currency,kind,onKindChange,onSelect}:{spec:VizSpec;currency:string;kind:VizKind;onKindChange:(kind:VizKind)=>void;onSelect?:(label:string)=>void}){
  const ref=useRef<HTMLDivElement>(null),[fullscreen,setFullscreen]=useState(false),[table,setTable]=useState(false);
  return <article className={`vz-card ${fullscreen?'vz-fullscreen':''}`} aria-label={spec.title}>
    <div className="vz-card-head"><div><h3>{spec.title}</h3><p>{spec.description}</p></div><div className="vz-card-controls"><label className="vz-visual-select"><span>Chart</span><select aria-label={`Chart type for ${spec.title}`} value={kind} onChange={e=>onKindChange(e.target.value as VizKind)}>{spec.allowed.map(x=><option key={x} value={x}>{x[0].toUpperCase()+x.slice(1)}</option>)}</select></label>
      <button type="button" title={table?'View graph':'View table'} aria-label={`Toggle data table for ${spec.title}`} onClick={()=>setTable(v=>!v)}><Table2 size={15}/></button>
      <button type="button" title={fullscreen?'Exit full screen':'Expand chart'} aria-label={`Expand ${spec.title}`} onClick={()=>setFullscreen(v=>!v)}><Expand size={15}/></button>
    </div></div>
    {table?<div className="vz-table-wrap"><table><thead><tr><th>Group</th><th>Value</th>{spec.series?.map(s=><th key={s}>{s}</th>)}</tr></thead><tbody>{spec.data.map((p,i)=><tr key={`${p.name}-${i}`}><td>{p.name}</td><td>{centerValue(p.value,spec.unit,currency)}</td>{spec.series?.map(s=><td key={s}>{centerValue(Number(p[s]||0),spec.unit,currency)}</td>)}</tr>)}</tbody></table></div>:<div className="vz-chart-area" ref={ref}><VizCanvas spec={spec} kind={kind} currency={currency} onSelect={onSelect}/></div>}
    <div className="vz-card-foot"><div><span>{spec.data.length} recorded groups</span>{spec.note&&<small>{spec.note}</small>}</div><div className="vz-foot-actions"><button type="button" onClick={()=>downloadChartCSV(spec)}><Download size={13}/> CSV</button>{!table&&<DownloadSvg target={ref} title={spec.title}/>}</div></div>
    {fullscreen&&<button className="vz-fullscreen-backdrop" type="button" onClick={()=>setFullscreen(false)} aria-label="Close expanded chart"/>}
  </article>;
}
