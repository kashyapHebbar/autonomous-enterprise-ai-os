import { ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Bar, BarChart, Line, LineChart } from 'recharts';
import type { AnalystCalculation } from '../types';

const currencySymbol: Record<string, string> = { USD:'$', INR:'₹', GBP:'£', EUR:'€', JPY:'¥' };

export default function AnalystChart({ result }: { result: AnalystCalculation }) {
  const prefix=currencySymbol[result.currency] || '';
  const data=result.points.map(point=>({ name:point.label, amount:point.value, count:point.transactions }));
  const fmt=(value:number)=>`${prefix}${Number(value).toLocaleString('en-IN',{maximumFractionDigits:2})}`;
  const axis={fill:'var(--text-muted)',fontSize:11};
  return <div className="ux-analyst-chart" aria-label={result.chart_title} role="img">
    <ResponsiveContainer width="100%" height="100%">
      {result.chart_kind==='line'?<LineChart data={data} margin={{top:12,right:18,left:8,bottom:8}}>
        <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 5" vertical={false}/>
        <XAxis dataKey="name" tick={axis} tickLine={false} axisLine={false}/>
        <YAxis tick={axis} tickLine={false} axisLine={false} tickFormatter={v=>Number(v).toLocaleString('en-US',{notation:'compact'})}/>
        <Tooltip formatter={(v)=>fmt(Number(v))} contentStyle={{background:'var(--tooltip-bg)',border:'1px solid var(--border)',borderRadius:12,color:'var(--text)'}}/>
        <Line type="monotone" dataKey="amount" name="Spending" stroke="#968dff" strokeWidth={3} dot={{fill:'#968dff',r:4}}/>
      </LineChart>:<BarChart data={data} margin={{top:12,right:18,left:8,bottom:8}}>
        <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 5" vertical={false}/>
        <XAxis dataKey="name" tick={axis} tickLine={false} axisLine={false} interval={0} angle={data.length>6?-30:0} textAnchor={data.length>6?'end':'middle'} height={data.length>6?60:32}/>
        <YAxis tick={axis} tickLine={false} axisLine={false} tickFormatter={v=>Number(v).toLocaleString('en-US',{notation:'compact'})}/>
        <Tooltip formatter={(v)=>fmt(Number(v))} contentStyle={{background:'var(--tooltip-bg)',border:'1px solid var(--border)',borderRadius:12,color:'var(--text)'}}/>
        <Bar dataKey="amount" name="Spending" fill="#8e85ff" radius={[6,6,0,0]} maxBarSize={54}/>
      </BarChart>}
    </ResponsiveContainer>
  </div>;
}
