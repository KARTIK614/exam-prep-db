/**
 * POST /api/v1/questions/{id}/deep-dive
 *
 * Uses Gemini REST (server-side) to produce a structured explanation:
 * `explanation`, `key_facts[]`, `exam_tips[]`, `follow_up_suggestions[]`.
 * On backend failure the server returns 502 with the standard error
 * envelope `{ error: { code, message, request_id } }` — surfaced here
 * as an `ApiError`.
 */
import { useMutation } from '@tanstack/react-query';
import { api } from './client';

export interface DeepDiveResponse {
  explanation: string;
  key_facts: string[];
  exam_tips: string[];
  follow_up_suggestions: string[];
  cached: boolean;
}

export const deepDiveApi = {
  ask: (questionId: number) =>
    api.post<DeepDiveResponse>(
      `/api/v1/questions/${questionId}/deep-dive`,
      {},
    ),
};

/**
 * Per-question mutation. Keyed by questionId so multiple cards can be
 * expanded in parallel without stomping each other's state.
 */
export function useDeepDive() {
  return useMutation({
    mutationFn: (questionId: number) => deepDiveApi.ask(questionId),
  });
}
