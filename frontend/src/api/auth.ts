import { useQuery } from '@tanstack/react-query';
import { apiCall, ApiError } from './client';

export interface AuthStatus {
  authenticated: boolean;
  youtube_connected: boolean;
}

export async function checkAuthStatus(): Promise<AuthStatus> {
  return apiCall<AuthStatus>('/api/auth/status', { skipErrorHandling: true });
}

export async function login(secret: string): Promise<{ ok: boolean }> {
  return apiCall('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ secret }),
    skipErrorHandling: true,
  });
}

export async function logout(): Promise<{ ok: boolean }> {
  return apiCall('/api/auth/logout', {
    method: 'POST',
  });
}

export function useAuthStatus() {
  return useQuery({
    queryKey: ['auth', 'status'],
    queryFn: checkAuthStatus,
    retry: false,
  });
}

export { ApiError };
