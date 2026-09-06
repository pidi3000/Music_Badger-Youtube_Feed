import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from './client';

export interface Settings {
  sync_interval_minutes: number;
  backfill_worker_interval_seconds: number;
  upload_retention_days: number;
  live_recheck_interval_minutes: number;
  rss_fallback_enabled: boolean;
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
    upload_retention_days: number;
    live_recheck_interval_minutes: number;
    rss_fallback_enabled: boolean;
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
      // Changing sync_interval_minutes (or the backfill worker interval)
      // reschedules the live APScheduler job immediately — but without
      // this, the "Last sync / Next sync" display on this same page kept
      // showing whatever was fetched before the change, i.e. a next-run
      // time computed under the old interval.
      queryClient.invalidateQueries({ queryKey: ['sync'] });
    },
  });
}

// How often to refresh the Feed while a rescan is still in flight. The
// backend commits each batch of up to 50 uploads as it goes (see
// reclassify_service.rescan_recent_uploads) rather than waiting for the
// whole rescan to finish, but a single REST call has no way to push that
// progress to the browser as it happens — polling the feed query on this
// interval is what actually surfaces each already-committed batch instead
// of everything appearing to change at once when the request finally
// resolves.
const RESCAN_FEED_REFRESH_INTERVAL_MS = 3000;

export function useRescanShorts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const interval = setInterval(() => {
        queryClient.invalidateQueries({ queryKey: ['feed'] });
      }, RESCAN_FEED_REFRESH_INTERVAL_MS);
      try {
        return await rescanShorts();
      } finally {
        clearInterval(interval);
      }
    },
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
