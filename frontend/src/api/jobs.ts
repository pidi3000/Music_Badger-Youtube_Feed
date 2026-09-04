import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { apiCall } from './client';

export type JobKind = 'backfill' | 'sync_api' | 'sync_rss' | 'import_subscriptions';

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

export async function getJobs(): Promise<Job[]> {
  return apiCall<Job[]>('/api/jobs');
}

export function useJobs(options?: Omit<UseQueryOptions, 'queryKey' | 'queryFn'>) {
  return useQuery({
    queryKey: ['jobs'],
    queryFn: getJobs,
    ...options,
  });
}
