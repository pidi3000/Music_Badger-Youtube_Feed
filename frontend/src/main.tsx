import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { initTheme } from './hooks/useTheme';
import { ToastProvider } from './context/ToastContext';
import './styles/global.css';

// Applied before the first render so there's no flash of the wrong theme.
initTheme();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Background jobs (sync, backfill, updates) keep changing server
      // state on their own, so cached data is considered stale
      // immediately — every page mount (i.e. every nav to that page) and
      // window refocus triggers a silent background refetch rather than
      // showing data that might already be outdated. Cached data is still
      // shown instantly while that refetch is in flight, so this doesn't
      // introduce loading flicker.
      staleTime: 0,
      gcTime: 1000 * 60 * 30, // 30 minutes (formerly cacheTime)
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <App />
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
