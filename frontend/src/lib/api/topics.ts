import { useQuery } from '@tanstack/react-query';

import { api } from './client';
import type { Topic, TopicWithCount } from './types';

/**
 * `/api/v1/topics` hooks.
 */
export const topicsApi = {
  list: (params?: { paper?: string; has_questions?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.paper) qs.set('paper', params.paper);
    if (params?.has_questions !== undefined)
      qs.set('has_questions', String(params.has_questions));
    const suffix = qs.toString() ? `?${qs}` : '';
    return api.get<{ items: Topic[] }>(`/api/v1/topics${suffix}`);
  },

  get: (id: number) => api.get<TopicWithCount>(`/api/v1/topics/${id}`),
};

export function useTopics(params?: { paper?: string; has_questions?: boolean }) {
  return useQuery({
    queryKey: ['topics', params ?? null],
    queryFn: () => topicsApi.list(params),
    staleTime: 5 * 60_000,
  });
}

export function useTopic(id: number | null | undefined) {
  return useQuery({
    queryKey: ['topics', id],
    queryFn: () => topicsApi.get(id as number),
    enabled: id !== null && id !== undefined,
    staleTime: 5 * 60_000,
  });
}
