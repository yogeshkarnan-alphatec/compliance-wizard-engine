import { QueryClient } from '@tanstack/react-query';
import { HttpError } from './api';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      // Don't retry client errors (4xx) — only transient/server failures.
      retry: (failureCount, error) => {
        if (error instanceof HttpError && error.status >= 400 && error.status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});
