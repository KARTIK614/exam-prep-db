import { useQuery } from '@tanstack/react-query';

import { api } from './client';

/**
 * `/api/v1/exam-presets` — one-click exam bundles (BCI, SSC CGL, GATE, ...).
 *
 * Static list served by the Rust backend. See `backend/src/api/exam_presets.rs`.
 * We wire this to TanStack Query with a very long stale time since the list
 * only changes when the backend redeploys.
 */

export interface DifficultyMix {
  easy: number;
  medium: number;
  hard: number;
}

export interface ExamPreset {
  slug: string;
  name: string;
  description: string;
  topic_ids: number[]; // empty = all Paper II topics
  question_count: number;
  test_mode: 'exam' | 'practice';
  neg_marking_preset: 'none' | 'third' | 'quarter' | 'fifth' | 'custom';
  pyq_only: boolean;
  difficulty_mix: DifficultyMix;
  suggested_minutes: number;
}

export interface ExamPresetsResponse {
  items: ExamPreset[];
}

const LAST_PRESET_KEY = 'lastExamPresetSlug';

export function getLastPresetSlug(): string | null {
  try {
    return localStorage.getItem(LAST_PRESET_KEY);
  } catch {
    return null;
  }
}

export function setLastPresetSlug(slug: string) {
  try {
    localStorage.setItem(LAST_PRESET_KEY, slug);
  } catch {
    /* localStorage unavailable — silently ignore */
  }
}

export const presetsApi = {
  list: () => api.get<ExamPresetsResponse>('/api/v1/exam-presets'),
};

export function useExamPresets() {
  return useQuery({
    queryKey: ['exam-presets'],
    queryFn: presetsApi.list,
    staleTime: 60 * 60_000, // 1h — server-static list
    retry: false,           // if it 404s pre-deploy, show empty state
  });
}
