import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './client';
import type { QType, ReviewCard, ReviewQueueResponse } from './types';

/**
 * `/api/v1/review/*` — Leitner SR queue.
 *
 * The Rust backend returns cards as `{card_id, question: {...}, box, due_at}`
 * and serves answers at `/review/answers/{card_id}`. The page works with the
 * flat `ReviewCard` shape, so the queue is adapted here (the "if you got it /
 * missed" previews use the same Leitner table as `services/sr.rs`).
 */

interface WireReviewQuestion {
  id: number;
  question_text: string | null;
  option_a: string | null;
  option_b: string | null;
  option_c: string | null;
  option_d: string | null;
  correct_option: string | null;
  explanation: string | null;
  topic_name: string | null;
  qtype?: QType | null;
  image_url?: string | null;
}

interface WireReviewCard {
  card_id: number;
  question: WireReviewQuestion;
  box: number;
  due_at: string | null;
}

interface WireQueue {
  summary: ReviewQueueResponse['summary'];
  cards: WireReviewCard[];
}

const BOX_DAYS: Record<number, number> = { 1: 1, 2: 3, 3: 7, 4: 14, 5: 30 };
const DROP_ON_MISS: Record<number, number> = { 1: 1, 2: 1, 3: 1, 4: 2, 5: 3 };

function adapt(c: WireReviewCard): ReviewCard {
  const box = c.box || 1;
  const okBox = Math.min(box + 1, 5);
  const noBox = DROP_ON_MISS[box] ?? 1;
  return {
    error_id: c.card_id,
    question_id: c.question.id,
    question_text: c.question.question_text,
    option_a: c.question.option_a,
    option_b: c.question.option_b,
    option_c: c.question.option_c,
    option_d: c.question.option_d,
    correct_option: c.question.correct_option,
    explanation: c.question.explanation,
    topic_name: c.question.topic_name,
    qtype: c.question.qtype ?? 'MCQ',
    image_url: c.question.image_url ?? null,
    sr_box: box,
    sr_due_at: c.due_at,
    if_ok_box: okBox,
    if_ok_days: BOX_DAYS[okBox] ?? 1,
    if_no_box: noBox,
    if_no_days: BOX_DAYS[noBox] ?? 1,
  };
}

export const reviewApi = {
  queue: async (params?: { limit?: number; box?: number }): Promise<ReviewQueueResponse> => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.box) qs.set('box', String(params.box));
    const suffix = qs.toString() ? `?${qs}` : '';
    const wire = await api.get<WireQueue>(`/api/v1/review/queue${suffix}`);
    return { summary: wire.summary, cards: wire.cards.map(adapt) };
  },
  answer: (cardId: number, body: { correct: boolean }) =>
    api.post<{
      box: number;
      next_due_at: string;
      days_until_due: number;
    }>(`/api/v1/review/answers/${cardId}`, body),
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
