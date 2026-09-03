import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { apiCall } from './client';

export interface Upload {
  id: number;
  channel: {
    id: number;
    title: string;
    thumbnail_url: string | null;
  };
  youtube_video_id: string;
  title: string;
  published_at: string;
  thumbnail_url: string | null;
  fetched_via: 'api' | 'rss';
}

export interface FeedResponse {
  items: Upload[];
  next_cursor: string | null;
}

export interface GetFeedQuery {
  tag_id?: number;
  channel_id?: number;
  cursor?: string;
  limit?: number;
}

export async function getFeed(query?: GetFeedQuery): Promise<FeedResponse> {
  const params = new URLSearchParams();
  if (query?.tag_id) params.append('tag_id', String(query.tag_id));
  if (query?.channel_id) params.append('channel_id', String(query.channel_id));
  if (query?.cursor) params.append('cursor', query.cursor);
  if (query?.limit) params.append('limit', String(query.limit));

  const url = `/api/feed${params.size > 0 ? '?' + params.toString() : ''}`;
  return apiCall<FeedResponse>(url);
}

export function useFeed(
  query?: GetFeedQuery,
  options?: Omit<UseQueryOptions, 'queryKey' | 'queryFn'>,
) {
  return useQuery({
    queryKey: ['feed', query],
    queryFn: () => getFeed(query),
    ...options,
  });
}
