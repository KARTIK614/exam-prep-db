import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { RouterProvider } from 'react-router-dom';

import { router } from '@/router';
import '@/styles/globals.css';

/**
 * React entry point.
 *
 * Provider order (outer → inner): StrictMode → QueryClient → Router.
 * Anything below the router can call `useQuery` / `useMutation` and any
 * react-router hooks.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retry once on transient errors; 401 is handled by the API client
      // itself (silent refresh), so we don't want to retry those.
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
    mutations: {
      retry: 0,
    },
  },
});

const rootEl = document.getElementById('root');
if (!rootEl) {
  throw new Error('#root element missing from index.html');
}

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  </StrictMode>,
);
