import { useQuery, useMutation, useQueryClient, UseQueryOptions } from '@tanstack/react-query';
import { apiCall } from './client';

export interface SyncLog {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: 'success' | 'error' | 'running';
  channels_added: number;
  channels_marked_unsubscribed: number;
  rss_fallback_channels: number;
  error: string | null;
}

export interface SyncStatus {
  last_sync: SyncLog | null;
  is_running: boolean;
  next_scheduled_at: string | null;
  unacknowledged_unsubscribed_count: number;
}

export async function startSync(): Promise<{ sync_log_id: number; status: string }> {
  return apiCall('/api/sync', {
    method: 'POST',
  });
}

export async function getSyncStatus(): Promise<SyncStatus> {
  return apiCall<SyncStatus>('/api/sync/status');
}

export function useSyncStatus(options?: Omit<UseQueryOptions, 'queryKey' | 'queryFn'>) {
  return useQuery({
    queryKey: ['sync', 'status'],
    queryFn: getSyncStatus,
    ...options,
  });
}

export function useStartSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startSync,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync'] });
    },
  });
}
