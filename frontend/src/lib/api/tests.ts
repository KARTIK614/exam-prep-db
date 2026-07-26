import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './client';
import type {
  CreateTestRequest,
  CreateTestResponse,
  FinishResponse,
  MarkForReviewRequest,
  ResultsResponse,
  SubmitAnswerRequest,
  TestListResponse,
  TestStateResponse,
} from './types';

/**
 * `/api/v1/tests/*` hooks. Tests are the exam-flow resource — create,
 * fetch (resume), submit answers, mark for review, finish, and view
 * results.
 */

export const testsApi = {
  create: (body: CreateTestRequest) =>
    api.post<CreateTestResponse>('/api/v1/tests', body),

  list: (params?: { status?: string; cursor?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.cursor) qs.set('cursor', params.cursor);
    if (params?.limit) qs.set('limit', String(params.limit));
    const suffix = qs.toString() ? `?${qs}` : '';
    return api.get<TestListResponse>(`/api/v1/tests${suffix}`);
  },

  get: (id: number) => api.get<TestStateResponse>(`/api/v1/tests/${id}`),

  submitAnswer: (id: number, body: SubmitAnswerRequest) =>
    api.post<{ status: string }>(`/api/v1/tests/${id}/answers`, body),

  markForReview: (id: number, body: MarkForReviewRequest) =>
    api.post<{ status: string }>(`/api/v1/tests/${id}/mark-for-review`, body),

  finish: (id: number) =>
    api.post<FinishResponse>(`/api/v1/tests/${id}/finish`),

  results: (id: number) =>
    api.get<ResultsResponse>(`/api/v1/tests/${id}/results`),
};

export function useCreateTest() {
  return useMutation({ mutationFn: testsApi.create });
}

export function useTestList(params?: {
  status?: string;
  cursor?: string;
  limit?: number;
}) {
  return useQuery({
    queryKey: ['tests', params ?? null],
    queryFn: () => testsApi.list(params),
    staleTime: 30_000,
  });
}

export function useTest(id: number | null | undefined) {
  return useQuery({
    queryKey: ['tests', id],
    queryFn: () => testsApi.get(id as number),
    enabled: id !== null && id !== undefined,
    // In-progress test state can change under our feet; short stale.
    staleTime: 0,
  });
}

export function useSubmitAnswer(testId: number) {
  return useMutation({
    mutationFn: (body: SubmitAnswerRequest) =>
      testsApi.submitAnswer(testId, body),
  });
}

export function useMarkForReview(testId: number) {
  return useMutation({
    mutationFn: (body: MarkForReviewRequest) =>
      testsApi.markForReview(testId, body),
  });
}

export function useFinishTest(testId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => testsApi.finish(testId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tests'] });
      qc.invalidateQueries({ queryKey: ['analytics'] });
    },
  });
}

export function useTestResults(id: number | null | undefined) {
  return useQuery({
    queryKey: ['tests', id, 'results'],
    queryFn: () => testsApi.results(id as number),
    enabled: id !== null && id !== undefined,
    staleTime: 5 * 60_000,
  });
}
