import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, CircleAlert, Database, ShieldCheck } from 'lucide-react';
import { api } from '../api';
import '../intelligence-performance.css';

export default function VerificationPanel({runId}:{runId:string}) {
  const {data,isLoading,isError} = useQuery({queryKey:['verification',runId],queryFn:()=>api.runVerification(runId)});
  return <section className="ip-run-check" aria-label="Independent financial verification"><div className="ip-run-check-head"><ShieldCheck size={18}/><strong>Independent financial verification</strong></div>
    {isLoading?<p>Loading verification results…</p>:isError?<p>Verification status is unavailable.</p>:data?.status==='not_checked'?<p>No independent source check was recorded for this run. New managed investigations are checked automatically.</p>:<><div className="ip-run-check-status"><span className={data?.status==='verified'?'ip-verified':'ip-warning'}>{data?.status?.replaceAll('_',' ')}</span><span>{data?.checks_passed != null ? `${data.checks_passed} of ${data.checks_total} checks passed` : data?.reason}</span></div>{data?.checks&&<div className="ip-check-list">{Object.entries(data.checks).map(([label,passed])=><div key={label}>{passed?<CheckCircle2 size={15}/>:<CircleAlert size={15}/>}<span>{label.replaceAll('_',' ')}</span></div>)}</div>}{data?.rows_scanned!=null&&<p className="ip-run-summary"><Database size={14}/> {data.rows_scanned.toLocaleString()} source rows scanned{data.reported_total!=null?` · reported total ${Number(data.reported_total).toLocaleString()}`:''}</p>}</>}
    <small>Checks reconcile saved procurement figures against a read-only source scan. They do not establish fraud, causation or full model correctness.</small>
  </section>;
}
