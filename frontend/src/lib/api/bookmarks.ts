import { useQuery } from '@tanstack/react-query';

import { api } from './client';
import type { BookmarksResponse } from './types';

/**
 * `/api/v1/bookmarks` — list of starred questions.
 * The toggle mutation itself lives in `questions.ts` (POST/DELETE on
 * `/questions/{id}/bookmark`) so the same hook can be called from any
 * question-detail context.
 */

export const bookmarksApi = {
  list: (params?: { cursor?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.cursor) qs.set('cursor', params.cursor);
    if (params?.limit) qs.set('limit', String(params.limit));
    const suffix = qs.toString() ? `?${qs}` : '';
    return api.get<BookmarksResponse>(`/api/v1/bookmarks${suffix}`);
  },
};

export function useBookmarks(params?: { cursor?: string; limit?: number }) {
  return useQuery({
    queryKey: ['bookmarks', params ?? null],
    queryFn: () => bookmarksApi.list(params),
    staleTime: 30_000,
    retry: false,
  });
}
