import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './client';
import type { ReviewQueueResponse } from './types';

/**
 * `/api/v1/review/*` — Leitner SR queue.
 */

export const reviewApi = {
  queue: (params?: { limit?: number; box?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.box) qs.set('box', String(params.box));
    const suffix = qs.toString() ? `?${qs}` : '';
    return api.get<ReviewQueueResponse>(`/api/v1/review/queue${suffix}`);
  },
  answer: (cardId: number, body: { correct: boolean }) =>
    api.post<{
      new_box: number;
      new_due_at: string;
      days_until_next: number;
    }>(`/api/v1/review/${cardId}`, body),
};

export function useReviewQueue(params?: { limit?: number; box?: number }) {
  return useQuery({
    queryKey: ['review', 'queue', params ?? null],
    queryFn: () => reviewApi.queue(params),
    staleTime: 30_000,
    retry: false,
  });
}

export function useReviewAnswer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ cardId, correct }: { cardId: number; correct: boolean }) =>
      reviewApi.answer(cardId, { correct }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review'] });
    },
  });
}
