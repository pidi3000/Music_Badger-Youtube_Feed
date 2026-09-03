import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from './client';

export interface ApiKey {
  id: number;
  label: string;
  group: 'background' | 'active';
  status: 'active' | 'exhausted' | 'disabled';
  quota_resets_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export async function getApiKeys(): Promise<ApiKey[]> {
  return apiCall<ApiKey[]>('/api/api-keys');
}

export async function createApiKey(payload: {
  label: string;
  group: 'background' | 'active';
  key_value: string;
}): Promise<ApiKey> {
  return apiCall('/api/api-keys', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateApiKey(
  id: number,
  payload: Partial<{
    label: string;
    group: 'background' | 'active';
    status: 'active' | 'disabled';
  }>,
): Promise<ApiKey> {
  return apiCall(`/api/api-keys/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function deleteApiKey(id: number): Promise<void> {
  return apiCall(`/api/api-keys/${id}`, {
    method: 'DELETE',
  });
}

export function useApiKeys() {
  return useQuery({
    queryKey: ['api-keys'],
    queryFn: getApiKeys,
  });
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
    },
  });
}

export function useUpdateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: number;
      payload: Partial<{ label: string; group: 'background' | 'active'; status: 'active' | 'disabled' }>;
    }) => updateApiKey(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
    },
  });
}

export function useDeleteApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
    },
  });
}
