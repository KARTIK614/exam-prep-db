import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './client';
import type {
  FlagQuestionRequest,
  Question,
  QuestionListResponse,
} from './types';

/**
 * `/api/v1/questions/*` hooks — list, get, flag, bookmark-toggle.
 */

export interface QuestionListParams {
  topic_id?: number;
  topic_ids?: string;
  difficulty?: string;
  pyq_only?: boolean;
  pyq_year_min?: number;
  pyq_year_max?: number;
  pyq_exam?: string;
  confidence?: string;
  search?: string;
  cursor?: string;
  limit?: number;
}

function buildQuery(params: QuestionListParams | undefined): string {
  if (!params) return '';
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    qs.set(k, String(v));
  }
  return qs.toString() ? `?${qs}` : '';
}

export const questionsApi = {
  list: (params?: QuestionListParams) =>
    api.get<QuestionListResponse>(`/api/v1/questions${buildQuery(params)}`),

  get: (id: number) => api.get<Question>(`/api/v1/questions/${id}`),

  flag: (id: number, body: FlagQuestionRequest) =>
    api.post<{ flag_id: number }>(`/api/v1/questions/${id}/flag`, body),

  bookmark: (id: number) =>
    api.post<{ bookmarked: boolean; bookmark_id: number }>(
      `/api/v1/questions/${id}/bookmark`,
    ),

  unbookmark: (id: number) =>
    api.delete<void>(`/api/v1/questions/${id}/bookmark`),
};

export function useQuestions(params?: QuestionListParams) {
  return useQuery({
    queryKey: ['questions', params ?? null],
    queryFn: () => questionsApi.list(params),
    staleTime: 30_000,
  });
}

export function useQuestion(id: number | null | undefined) {
  return useQuery({
    queryKey: ['questions', id],
    queryFn: () => questionsApi.get(id as number),
    enabled: id !== null && id !== undefined,
  });
}

export function useFlagQuestion() {
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: FlagQuestionRequest }) =>
      questionsApi.flag(id, body),
  });
}

export function useToggleBookmark() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, isBookmarked }: { id: number; isBookmarked: boolean }) => {
      // Both branches normalized to void — caller only cares about invalidation.
      if (isBookmarked) {
        await questionsApi.unbookmark(id);
      } else {
        await questionsApi.bookmark(id);
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bookmarks'] });
    },
  });
}
