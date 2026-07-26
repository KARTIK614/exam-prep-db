import { useQuery } from '@tanstack/react-query';

import { api } from './client';
import type { ErrorLogResponse } from './types';

/**
 * `/api/v1/errors` — the error log (wrong-answer history + SRS metadata).
 */

export const errorsApi = {
  list: (params?: { cursor?: string; limit?: number; topic_id?: number }) => {
    const qs = new URLSearchParams();
    if (params?.cursor) qs.set('cursor', params.cursor);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.topic_id) qs.set('topic_id', String(params.topic_id));
    const suffix = qs.toString() ? `?${qs}` : '';
    return api.get<ErrorLogResponse>(`/api/v1/errors${suffix}`);
  },
};

export function useErrorLog(params?: {
  cursor?: string;
  limit?: number;
  topic_id?: number;
}) {
  return useQuery({
    queryKey: ['errors', params ?? null],
    queryFn: () => errorsApi.list(params),
    staleTime: 30_000,
    retry: false,
  });
}
