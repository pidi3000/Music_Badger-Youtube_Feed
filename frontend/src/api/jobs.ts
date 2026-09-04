import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { apiCall } from './client';

export type JobKind = 'update' | 'backfill' | 'import_subscriptions';

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

export async function getJobs(kind?: JobKind): Promise<Job[]> {
  const params = kind ? `?kind=${kind}` : '';
  return apiCall<Job[]>(`/api/jobs${params}`);
}

export function useJobs(kind?: JobKind, options?: Omit<UseQueryOptions, 'queryKey' | 'queryFn'>) {
  return useQuery({
    queryKey: ['jobs', kind],
    queryFn: () => getJobs(kind),
    ...options,
  });
}
