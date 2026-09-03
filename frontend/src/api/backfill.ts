import { useQuery, useMutation, useQueryClient, UseQueryOptions } from '@tanstack/react-query';
import { apiCall } from './client';

export interface BackfillTask {
  id: number;
  channel: {
    id: number;
    title: string;
    thumbnail_url: string | null;
  };
  status: 'queued' | 'in_progress' | 'paused_quota' | 'completed' | 'failed';
  fetched_count: number;
  target_min_count: number;
  target_after: string;
  oldest_fetched_published_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface GetBackfillTasksQuery {
  status?: 'queued' | 'in_progress' | 'paused_quota' | 'completed' | 'failed';
}

export async function getBackfillTasks(query?: GetBackfillTasksQuery): Promise<BackfillTask[]> {
  const params = new URLSearchParams();
  if (query?.status) params.append('status', query.status);

  const url = `/api/backfill-tasks${params.size > 0 ? '?' + params.toString() : ''}`;
  return apiCall<BackfillTask[]>(url);
}

export async function retryBackfillTask(id: number): Promise<BackfillTask> {
  return apiCall(`/api/backfill-tasks/${id}/retry`, {
    method: 'POST',
  });
}

export function useBackfillTasks(
  query?: GetBackfillTasksQuery,
  options?: Omit<UseQueryOptions, 'queryKey' | 'queryFn'>,
) {
  return useQuery({
    queryKey: ['backfill-tasks', query],
    queryFn: () => getBackfillTasks(query),
    ...options,
  });
}

export function useRetryBackfillTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: retryBackfillTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backfill-tasks'] });
    },
  });
}
