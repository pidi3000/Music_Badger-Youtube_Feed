import {
  useQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import { apiCall } from './client';

export interface Tag {
  id: number;
  name: string;
  color: string;
}

export async function getTags(): Promise<Tag[]> {
  return apiCall<Tag[]>('/api/tags');
}

export async function createTag(payload: { name: string; color: string }): Promise<Tag> {
  return apiCall('/api/tags', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateTag(id: number, payload: Partial<{ name: string; color: string }>): Promise<Tag> {
  return apiCall(`/api/tags/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function deleteTag(id: number): Promise<void> {
  return apiCall(`/api/tags/${id}`, {
    method: 'DELETE',
  });
}

export function useTags() {
  return useQuery({
    queryKey: ['tags'],
    queryFn: getTags,
  });
}

export function useCreateTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createTag,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] });
    },
  });
}

export function useUpdateTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Partial<{ name: string; color: string }> }) =>
      updateTag(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] });
    },
  });
}

export function useDeleteTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteTag,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] });
    },
  });
}
