import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from './client';

export interface Settings {
  sync_interval_minutes: number;
  upload_fetch_method: 'api' | 'rss';
  backfill_days: number;
  backfill_min_count: number;
  youtube_connected: boolean;
  youtube_channel_title: string | null;
}

export async function getSettings(): Promise<Settings> {
  return apiCall<Settings>('/api/settings');
}

export async function updateSettings(
  payload: Partial<{
    upload_fetch_method: 'api' | 'rss';
    backfill_days: number;
    backfill_min_count: number;
  }>,
): Promise<Settings> {
  return apiCall('/api/settings', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function getYouTubeAuthStart(): Promise<{ authorization_url: string }> {
  return apiCall('/api/youtube/auth/start');
}

export async function deleteYouTubeAuth(): Promise<{ ok: boolean }> {
  return apiCall('/api/youtube/auth', {
    method: 'DELETE',
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
  });
}

export function useYouTubeAuthStart() {
  return useMutation({
    mutationFn: getYouTubeAuthStart,
  });
}

export function useDeleteYouTubeAuth() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteYouTubeAuth,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
  });
}
