import { useMutation } from '@tanstack/react-query';

import { api } from './client';
import type { FlagQuestionRequest } from './types';

/**
 * `/api/v1/questions/:id/flag` — user-side flag submission. Distinct from
 * admin flag resolution (`admin.ts`). The category enum + note-required
 * rules live in the UI form; the backend rejects invalid payloads with
 * `note_required_for_other`.
 */

export const flagsApi = {
  submit: (questionId: number, body: FlagQuestionRequest) =>
    api.post<{ flag_id: number }>(`/api/v1/questions/${questionId}/flag`, body),
};

export function useSubmitFlag() {
  return useMutation({
    mutationFn: ({ questionId, body }: { questionId: number; body: FlagQuestionRequest }) =>
      flagsApi.submit(questionId, body),
  });
}
