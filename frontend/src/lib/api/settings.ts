import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './client';
import type { UserSettings } from './types';

/**
 * `/api/v1/me/settings` — per-user preferences (target-seconds-per-question,
 * default negative-marking, dark-mode flag, etc.).
 */

export const settingsApi = {
  get: () => api.get<UserSettings>('/api/v1/me/settings'),
  update: (body: Partial<UserSettings>) =>
    api.patch<UserSettings>('/api/v1/me/settings', body),
};

export function useSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: settingsApi.get,
    staleTime: 60_000,
    retry: false,
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: settingsApi.update,
    onSuccess: (data) => {
      qc.setQueryData(['settings'], data);
    },
  });
}
