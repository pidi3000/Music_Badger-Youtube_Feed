export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function apiCall<T>(
  endpoint: string,
  options: RequestInit & { skipErrorHandling?: boolean } = {}
): Promise<T> {
  const { skipErrorHandling, ...fetchOptions } = options;

  const response = await fetch(endpoint, {
    ...fetchOptions,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...fetchOptions.headers,
    },
  });

  if (!response.ok) {
    if (response.status === 401 && !skipErrorHandling) {
      // Redirect to login on 401
      window.location.href = '/login';
      throw new ApiError(401, 'Unauthorized');
    }

    const error = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, error.detail || response.statusText);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}
