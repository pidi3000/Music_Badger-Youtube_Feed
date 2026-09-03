import {
  useQuery,
  useMutation,
  useQueryClient,
  UseQueryOptions,
} from '@tanstack/react-query';
import { apiCall } from './client';
import { Tag } from './tags';

export interface Channel {
  id: number;
  youtube_channel_id: string;
  title: string;
  handle: string | null;
  thumbnail_url: string | null;
  source: 'subscription' | 'manual' | 'both';
  subscription_status: 'subscribed' | 'unsubscribed';
  unsubscribed_at: string | null;
  unsubscribed_ack: boolean;
  upload_fetch_method: 'api' | 'rss' | null;
  effective_fetch_method: 'api' | 'rss';
  backfill_completed_at: string | null;
  backfill_status: 'not_started' | 'queued' | 'in_progress' | 'paused_quota' | 'completed' | 'failed';
  upload_count: number;
  oldest_upload_at: string | null;
  last_synced_at: string | null;
  tags: Tag[];
  added_at: string;
  updated_at: string;
}

export interface GetChannelsQuery {
  tag_id?: number;
  status?: 'subscribed' | 'unsubscribed';
  fetch_method?: 'api' | 'rss';
}

export async function getChannels(query?: GetChannelsQuery): Promise<Channel[]> {
  const params = new URLSearchParams();
  if (query?.tag_id) params.append('tag_id', String(query.tag_id));
  if (query?.status) params.append('status', query.status);
  if (query?.fetch_method) params.append('fetch_method', query.fetch_method);

  const url = `/api/channels${params.size > 0 ? '?' + params.toString() : ''}`;
  return apiCall<Channel[]>(url);
}

export async function getChannel(id: number): Promise<Channel> {
  return apiCall(`/api/channels/${id}`);
}

export async function createChannel(payload: { channel_link: string; tag_ids?: number[] }): Promise<Channel> {
  return apiCall('/api/channels', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateChannel(
  id: number,
  payload: Partial<{ tag_ids: number[]; upload_fetch_method: 'api' | 'rss' | null }>,
): Promise<Channel> {
  return apiCall(`/api/channels/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function deleteChannel(id: number): Promise<void> {
  return apiCall(`/api/channels/${id}`, {
    method: 'DELETE',
  });
}

export async function ackUnsubscribe(id: number): Promise<Channel> {
  return apiCall(`/api/channels/${id}/ack-unsubscribe`, {
    method: 'POST',
  });
}

export function useChannels(
  query?: GetChannelsQuery,
  options?: Omit<UseQueryOptions, 'queryKey' | 'queryFn'>,
) {
  return useQuery({
    queryKey: ['channels', query],
    queryFn: () => getChannels(query),
    ...options,
  });
}

export function useChannel(id: number) {
  return useQuery({
    queryKey: ['channels', id],
    queryFn: () => getChannel(id),
  });
}

export function useCreateChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createChannel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['channels'] });
    },
  });
}

export function useUpdateChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Partial<{ tag_ids: number[]; upload_fetch_method: 'api' | 'rss' | null }> }) =>
      updateChannel(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['channels'] });
    },
  });
}

export function useDeleteChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteChannel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['channels'] });
    },
  });
}

export function useAckUnsubscribe() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ackUnsubscribe,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['channels'] });
    },
  });
}
