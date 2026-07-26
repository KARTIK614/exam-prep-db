import { useQuery } from '@tanstack/react-query';

import { api } from './client';
import type {
  ConsistencyResponse,
  ErrorDistResponse,
  HeatmapResponse,
  MasteryResponse,
  NextTopicsResponse,
  PacingResponse,
  PaperPerfResponse,
} from './types';

/**
 * `/api/v1/analytics/*` hooks. Backend implementation is still pending
 * per R4 §3.9 — these hooks target the endpoint URLs from the plan; if
 * an endpoint 404s the caller renders an empty state.
 */

export const analyticsApi = {
  mastery: (paper?: string) => {
    const suffix = paper ? `?paper=${encodeURIComponent(paper)}` : '';
    return api.get<MasteryResponse>(`/api/v1/analytics/mastery${suffix}`);
  },
  nextTopics: (limit?: number) => {
    const suffix = limit ? `?limit=${limit}` : '';
    return api.get<NextTopicsResponse>(
      `/api/v1/analytics/next-weak-topic${suffix}`,
    );
  },
  consistency: (params?: { days?: number; denom?: number }) => {
    const qs = new URLSearchParams();
    if (params?.days) qs.set('days', String(params.days));
    if (params?.denom) qs.set('denom', String(params.denom));
    const suffix = qs.toString() ? `?${qs}` : '';
    return api.get<ConsistencyResponse>(`/api/v1/analytics/consistency${suffix}`);
  },
  errorDist: () =>
    api.get<ErrorDistResponse>('/api/v1/analytics/error-dist'),
  heatmap: (dim: 'difficulty' | 'recency') =>
    api.get<HeatmapResponse>(`/api/v1/analytics/heatmap?dim=${dim}`),
  pacing: () => api.get<PacingResponse>('/api/v1/analytics/pacing'),
  paperPerformance: () =>
    api.get<PaperPerfResponse>('/api/v1/analytics/paper-performance'),
};

export function useMastery(paper?: string) {
  return useQuery({
    queryKey: ['analytics', 'mastery', paper ?? null],
    queryFn: () => analyticsApi.mastery(paper),
    staleTime: 60_000,
    retry: false,
  });
}

export function useNextTopics(limit?: number) {
  return useQuery({
    queryKey: ['analytics', 'next-topics', limit ?? null],
    queryFn: () => analyticsApi.nextTopics(limit),
    staleTime: 60_000,
    retry: false,
  });
}

export function useConsistency(params?: { days?: number; denom?: number }) {
  return useQuery({
    queryKey: ['analytics', 'consistency', params ?? null],
    queryFn: () => analyticsApi.consistency(params),
    staleTime: 60_000,
    retry: false,
  });
}

export function useErrorDist() {
  return useQuery({
    queryKey: ['analytics', 'error-dist'],
    queryFn: () => analyticsApi.errorDist(),
    staleTime: 60_000,
    retry: false,
  });
}

export function useHeatmap(dim: 'difficulty' | 'recency') {
  return useQuery({
    queryKey: ['analytics', 'heatmap', dim],
    queryFn: () => analyticsApi.heatmap(dim),
    staleTime: 60_000,
    retry: false,
  });
}

export function usePacing() {
  return useQuery({
    queryKey: ['analytics', 'pacing'],
    queryFn: () => analyticsApi.pacing(),
    staleTime: 60_000,
    retry: false,
  });
}

export function usePaperPerformance() {
  return useQuery({
    queryKey: ['analytics', 'paper-performance'],
    queryFn: () => analyticsApi.paperPerformance(),
    staleTime: 60_000,
    retry: false,
  });
}
