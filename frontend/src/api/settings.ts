import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from './client';

export interface Settings {
  sync_interval_minutes: number;
  backfill_worker_interval_seconds: number;
  upload_fetch_method: 'api' | 'rss';
  backfill_days: number;
  backfill_min_count: number;
  strict_shorts_detection: boolean;
  youtube_connected: boolean;
  youtube_channel_title: string | null;
}

export async function getSettings(): Promise<Settings> {
  return apiCall<Settings>('/api/settings');
}

export async function updateSettings(
  payload: Partial<{
    sync_interval_minutes: number;
    backfill_worker_interval_seconds: number;
    upload_fetch_method: 'api' | 'rss';
    backfill_days: number;
    backfill_min_count: number;
    strict_shorts_detection: boolean;
  }>,
): Promise<Settings> {
  return apiCall('/api/settings', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export interface RescanShortsResult {
  checked: number;
  reclassified: number;
}

export async function rescanShorts(): Promise<RescanShortsResult> {
  return apiCall('/api/settings/rescan-shorts', {
    method: 'POST',
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

export function useRescanShorts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: rescanShorts,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feed'] });
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
