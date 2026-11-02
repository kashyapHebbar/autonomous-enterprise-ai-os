import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowRight, BellRing, CheckCircle2, RadioTower, ShieldCheck } from 'lucide-react';
import { api } from '../api';
import '../monitoring.css';

export default function MonitoringSnapshot(){
  const q=useQuery({queryKey:['monitoring-summary'],queryFn:api.monitoringSummary,refetchInterval:20000,retry:1});
  const data=q.data;
  return <section className="monitor-home-block">
    <div className="section-title"><div><span className="eyebrow">AUTONOMOUS INTELLIGENCE</span><h2>Monitoring & important alerts</h2><p>Actual scheduled checks and findings from your persistent workspace.</p></div><Link to="/monitoring" className="text-action">Monitoring Center <ArrowRight size={15}/></Link></div>
    <div className="monitor-home-layout">
      <div className="monitor-home-card"><div className="monitor-home-title"><RadioTower size={20}/><strong>Scheduled monitoring</strong></div><div className="monitor-home-count">{data?.enabled_monitors??'—'} <small>enabled monitors</small></div><p>{q.isError?'Monitoring service unavailable':data?.worker_online?'Monitoring worker connected':data?.monitor_count?'Worker offline — start the monitoring worker to run schedules':'Create your first monitor to start recurring checks'}</p><Link to="/monitoring">Manage monitors <ArrowRight size={14}/></Link></div>
      <div className="monitor-home-card"><div className="monitor-home-title"><BellRing size={20}/><strong>Alerts needing review</strong></div><div className="monitor-home-count">{data?.open_alerts??'—'} <small>open alerts</small></div>{data?.recent_alerts?.length?data.recent_alerts.filter(a=>a.status==='open').slice(0,3).map(a=><Link key={a.id} to="/monitoring" className="monitor-home-alert"><ShieldCheck size={16}/><span>{a.title}</span></Link>):<p><CheckCircle2 size={15}/> No open alerts. Completed checks will appear here when a configured threshold is crossed.</p>}</div>
    </div>
  </section>;
}
