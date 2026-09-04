import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { apiCall } from './client';

export type JobKind = 'update' | 'backfill' | 'import_subscriptions';
export type JobState = 'queued' | 'running' | 'done' | 'stopped';

export interface Job {
  id: string;
  kind: JobKind;
  channel: {
    id: number;
    title: string;
    thumbnail_url: string | null;
  } | null;
  status: string;
  detail: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  fetched_count: number | null;
  target_min_count: number | null;
  backfill_task_id: number | null;
}

export interface JobsQuery {
  kind?: JobKind;
  state?: JobState;
}

export async function getJobs(query?: JobsQuery): Promise<Job[]> {
  const params = new URLSearchParams();
  if (query?.kind) params.append('kind', query.kind);
  if (query?.state) params.append('state', query.state);
  const qs = params.size > 0 ? `?${params.toString()}` : '';
  return apiCall<Job[]>(`/api/jobs${qs}`);
}

export function useJobs(query?: JobsQuery, options?: Omit<UseQueryOptions, 'queryKey' | 'queryFn'>) {
  return useQuery({
    queryKey: ['jobs', query],
    queryFn: () => getJobs(query),
    ...options,
  });
}
