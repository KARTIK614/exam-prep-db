import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { api } from './client';
import type { SearchResponse } from './types';

/**
 * `/api/v1/search` — full-text question search. `useSearch` bundles the
 * standard 250 ms debounce on the query string.
 */

export interface SearchParams {
  q: string;
  topic_id?: number;
  difficulty?: string;
  confidence?: string;
  pyq_exam?: string;
  pyq_year_min?: number;
  pyq_year_max?: number;
  cursor?: string;
  limit?: number;
}

function buildQuery(params: SearchParams): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    qs.set(k, String(v));
  }
  return `?${qs}`;
}

export const searchApi = {
  search: (params: SearchParams) =>
    api.get<SearchResponse>(`/api/v1/search${buildQuery(params)}`),
};

/** Debounce a value by `delay` ms. */
export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

/** `useSearch` debounces the query and only fires when >= 2 chars. */
export function useSearch(params: SearchParams) {
  const debouncedQ = useDebounced(params.q, 250);
  const effective: SearchParams = { ...params, q: debouncedQ };
  return useQuery({
    queryKey: ['search', effective],
    queryFn: () => searchApi.search(effective),
    enabled: debouncedQ.trim().length >= 2,
    staleTime: 30_000,
    retry: false,
  });
}
