import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, CircleCheck } from 'lucide-react';
import { api } from '../api';
import '../operations.css';

export default function OperationsBanner() {
  const q = useQuery({queryKey:['operations'],queryFn:api.operations,refetchInterval:10000,retry:false});
  const data = q.data;
  if (!data) return null;
  const waiting = data.queue.queued;
  const offline = !data.workflow_worker.online;
  return <section className={`ops-home-status ${offline&&waiting?'ops-home-warning':''}`} aria-live="polite">
    {offline&&waiting?<AlertTriangle size={20}/>:<CircleCheck size={20}/>}
    <div><strong>{offline&&waiting?`${waiting} investigation${waiting===1?' is':'s are'} waiting for a worker`:
      waiting?`${waiting} investigation${waiting===1?' is':'s are'} queued for execution`:'Background execution is ready'}</strong>
      <p>{data.guidance}</p></div>
    <Link to="/operations">View Operations Center <ArrowRight size={16}/></Link>
  </section>;
}
