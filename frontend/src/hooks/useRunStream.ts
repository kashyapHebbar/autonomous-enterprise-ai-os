import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import type { RunDetail, RunProgressSnapshot, WorkflowJob } from '../types';

/** Subscribe to authenticated, same-origin SSE, with React Query polling fallback. */
export function useRunStream(runId: string, enabled: boolean) {
  const queryClient = useQueryClient();
  const [connection, setConnection] = useState<'connecting' | 'live' | 'fallback'>('connecting');
  const [jobs, setJobs] = useState<WorkflowJob[]>([]);

  useEffect(() => {
    if (!runId || !enabled || typeof EventSource === 'undefined') {
      setConnection('fallback');
      return;
    }
    setConnection('connecting');
    const stream = new EventSource(api.streamUrl(runId));
    let lastEventCount = -1;
    const onSnapshot = (event: MessageEvent) => {
      try {
        const snapshot = JSON.parse(event.data) as RunProgressSnapshot;
        setConnection('live');
        setJobs(snapshot.jobs);
        queryClient.setQueryData<RunDetail>(['run', runId], current =>
          current ? { ...current, ...snapshot.run } : current,
        );
        queryClient.setQueryData(['graph', runId], snapshot.nodes);
        queryClient.setQueryData(['jobs', runId], snapshot.jobs);
        if (lastEventCount !== snapshot.event_count) {
          lastEventCount = snapshot.event_count;
          void queryClient.invalidateQueries({ queryKey: ['events', runId] });
        }
        if (['completed', 'failed', 'waiting_for_approval'].includes(snapshot.run.status)) {
          void queryClient.invalidateQueries({ queryKey: ['run', runId] });
          void queryClient.invalidateQueries({ queryKey: ['runs'] });
          stream.close();
        }
      } catch {
        setConnection('fallback');
        stream.close();
      }
    };
    stream.addEventListener('snapshot', onSnapshot as EventListener);
    stream.addEventListener('finished', () => stream.close());
    stream.onerror = () => {setConnection('fallback'); stream.close();};
    return () => stream.close();
  }, [runId, enabled, queryClient]);

  return { connection, jobs };
}
