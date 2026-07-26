import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './client';
import type {
  AdminFlag,
  AdminStatsResponse,
  AdminUpload,
  AdminUser,
  DuplicatesResponse,
  Question,
} from './types';

/**
 * `/api/v1/admin/*` hooks. Endpoints are pulled from R4 §3.10; the Rust
 * backend has not yet implemented most of them so every hook is written
 * defensively (retry: false, empty state on 4xx/5xx).
 */

export const adminApi = {
  stats: () => api.get<AdminStatsResponse>('/api/v1/admin/stats'),

  questions: (params?: {
    topic_id?: number;
    difficulty?: string;
    cursor?: string;
    limit?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.topic_id) qs.set('topic_id', String(params.topic_id));
    if (params?.difficulty) qs.set('difficulty', params.difficulty);
    if (params?.cursor) qs.set('cursor', params.cursor);
    if (params?.limit) qs.set('limit', String(params.limit));
    const suffix = qs.toString() ? `?${qs}` : '';
    return api.get<{ items: Question[]; next_cursor: string | null }>(
      `/api/v1/admin/questions${suffix}`,
    );
  },
  updateQuestion: (id: number, body: Partial<Question>) =>
    api.patch<Question>(`/api/v1/admin/questions/${id}`, body),
  deleteQuestion: (id: number) =>
    api.delete<void>(`/api/v1/admin/questions/${id}`),
  toggleDisabled: (id: number) =>
    api.post<{ disabled: number }>(
      `/api/v1/admin/questions/${id}/toggle-disabled`,
    ),

  flags: (params?: { status?: string; cursor?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.cursor) qs.set('cursor', params.cursor);
    if (params?.limit) qs.set('limit', String(params.limit));
    const suffix = qs.toString() ? `?${qs}` : '';
    return api.get<{ items: AdminFlag[]; next_cursor: string | null }>(
      `/api/v1/admin/flags${suffix}`,
    );
  },
  resolveFlag: (id: number) =>
    api.post<void>(`/api/v1/admin/flags/${id}/resolve`),
  dismissFlag: (id: number) =>
    api.post<void>(`/api/v1/admin/flags/${id}/dismiss`),
  disableFlagQuestion: (id: number) =>
    api.post<{ question_id_disabled: number }>(
      `/api/v1/admin/flags/${id}/disable-question`,
    ),

  reviewQueue: (filter?: string) => {
    const suffix = filter ? `?filter=${filter}` : '';
    return api.get<{ items: Question[]; counts: Record<string, number> }>(
      `/api/v1/admin/review-queue${suffix}`,
    );
  },
  confirmReview: (qid: number) =>
    api.post<void>(`/api/v1/admin/review-queue/${qid}/confirm`),
  deferReview: (qid: number) =>
    api.post<void>(`/api/v1/admin/review-queue/${qid}/defer`),

  duplicates: (params?: { threshold?: number; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.threshold) qs.set('threshold', String(params.threshold));
    if (params?.limit) qs.set('limit', String(params.limit));
    const suffix = qs.toString() ? `?${qs}` : '';
    return api.get<DuplicatesResponse>(`/api/v1/admin/duplicates${suffix}`);
  },
  disableDuplicate: (qid: number) =>
    api.post<void>(`/api/v1/admin/duplicates/${qid}/disable`),

  users: () =>
    api.get<{ items: AdminUser[] }>('/api/v1/admin/users'),
  updateUser: (uid: number, body: Partial<AdminUser>) =>
    api.patch<AdminUser>(`/api/v1/admin/users/${uid}`, body),

  uploads: () =>
    api.get<{ items: AdminUpload[] }>('/api/v1/admin/pdf-uploads'),
  uploadPdf: (form: FormData) =>
    fetch(
      (import.meta.env.VITE_API_URL ?? '') + '/api/v1/admin/pdf-uploads',
      { method: 'POST', body: form },
    ).then((r) => r.json() as Promise<AdminUpload>),
  importFromUpload: (id: number, selectedIds: number[]) =>
    api.post<{ imported: number }>(
      `/api/v1/admin/pdf-uploads/${id}/import`,
      { selected_ids: selectedIds },
    ),

  synthesize: (body: { topic_id: number; count: number; sub_topics?: string }) =>
    api.post<{ batch_id: number; n_generated: number }>(
      '/api/v1/admin/synthesize',
      body,
    ),
  synthesizePreview: (batchId: number) =>
    api.get<{ questions: Question[] }>(
      `/api/v1/admin/synthesize/${batchId}`,
    ),
  synthesizeCommit: (batchId: number, selectedIds: number[]) =>
    api.post<{ imported: number }>(
      `/api/v1/admin/synthesize/${batchId}/commit`,
      { selected_ids: selectedIds },
    ),
};

// -------- hooks ------------

export function useAdminStats() {
  return useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => adminApi.stats(),
    staleTime: 30_000,
    retry: false,
  });
}
export function useAdminQuestions(params?: {
  topic_id?: number;
  difficulty?: string;
}) {
  return useQuery({
    queryKey: ['admin', 'questions', params ?? null],
    queryFn: () => adminApi.questions(params),
    staleTime: 30_000,
    retry: false,
  });
}
export function useAdminFlags(params?: { status?: string }) {
  return useQuery({
    queryKey: ['admin', 'flags', params ?? null],
    queryFn: () => adminApi.flags(params),
    staleTime: 30_000,
    retry: false,
  });
}
export function useAdminReviewQueue(filter?: string) {
  return useQuery({
    queryKey: ['admin', 'review-queue', filter ?? null],
    queryFn: () => adminApi.reviewQueue(filter),
    staleTime: 30_000,
    retry: false,
  });
}
export function useAdminDuplicates(params?: {
  threshold?: number;
  limit?: number;
}) {
  return useQuery({
    queryKey: ['admin', 'duplicates', params ?? null],
    queryFn: () => adminApi.duplicates(params),
    staleTime: 30_000,
    retry: false,
  });
}
export function useAdminUsers() {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => adminApi.users(),
    staleTime: 30_000,
    retry: false,
  });
}
export function useAdminUploads() {
  return useQuery({
    queryKey: ['admin', 'uploads'],
    queryFn: () => adminApi.uploads(),
    staleTime: 30_000,
    retry: false,
  });
}

export function useResolveFlag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => adminApi.resolveFlag(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'flags'] }),
  });
}
export function useDismissFlag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => adminApi.dismissFlag(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'flags'] }),
  });
}
export function useDisableFlagQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => adminApi.disableFlagQuestion(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'flags'] }),
  });
}
