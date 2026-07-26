import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './client';
import type {
  ForgotPasswordRequest,
  ForgotPasswordResponse,
  LoginRequest,
  LogoutRequest,
  MeResponse,
  RefreshRequest,
  RefreshResponse,
  RegisterRequest,
  RegisterResponse,
  ResetPasswordRequest,
  TokenResponse,
  UpdateMeRequest,
} from './types';
import { useAuthStore } from '@/stores/authStore';

/**
 * Thin endpoint wrappers + TanStack Query hooks for `/api/v1/auth/*` and
 * `/api/v1/me`. Handlers stay dumb — write tokens to the auth store on
 * success and let router-level effects handle navigation.
 *
 * All raw request/response types are declared in `./types.ts`. This file
 * only composes them into hooks + plain-callable functions.
 */

// ---------- raw functions (usable from outside React) --------------------

export const authApi = {
  register: (body: RegisterRequest) =>
    api.post<RegisterResponse>('/api/v1/auth/register', body, { skipAuth: true }),

  login: (body: LoginRequest) =>
    api.post<TokenResponse>('/api/v1/auth/login', body, { skipAuth: true }),

  refresh: (body: RefreshRequest) =>
    api.post<RefreshResponse>('/api/v1/auth/refresh', body, {
      skipAuth: true,
      skipRefresh: true,
    }),

  logout: (body: LogoutRequest = {}) =>
    api.post<void>('/api/v1/auth/logout', body, { skipRefresh: true }),

  forgotPassword: (body: ForgotPasswordRequest) =>
    api.post<ForgotPasswordResponse>('/api/v1/auth/forgot-password', body, {
      skipAuth: true,
    }),

  resetPassword: (token: string, body: ResetPasswordRequest) =>
    api.post<void>(`/api/v1/auth/reset-password/${encodeURIComponent(token)}`, body, {
      skipAuth: true,
    }),

  me: () => api.get<MeResponse>('/api/v1/me'),

  updateMe: (body: UpdateMeRequest) => api.patch<MeResponse>('/api/v1/me', body),
};

// ---------- React Query hooks ---------------------------------------------

/**
 * Fetch the current user (`/api/v1/me`). The query is enabled only when we
 * have an access token; on 401 the API client will attempt refresh and
 * clear the store if that fails.
 */
export function useMe() {
  const accessToken = useAuthStore((s) => s.accessToken);
  return useQuery({
    queryKey: ['me'],
    queryFn: authApi.me,
    enabled: Boolean(accessToken),
    staleTime: 60_000,
    retry: false,
  });
}

export function useRegister() {
  const setSession = useAuthStore((s) => s.setSession);
  return useMutation({
    mutationFn: authApi.register,
    onSuccess: (data) => {
      setSession({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
      });
    },
  });
}

export function useLogin() {
  const setSession = useAuthStore((s) => s.setSession);
  return useMutation({
    mutationFn: authApi.login,
    onSuccess: (data) => {
      setSession({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
      });
    },
  });
}

export function useLogout() {
  const clear = useAuthStore((s) => s.clear);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      authApi.logout(refreshToken ? { refresh_token: refreshToken } : {}),
    // Clear local state regardless of server response — logout must feel
    // instantaneous, and the server call is idempotent best-effort anyway.
    onSettled: () => {
      clear();
      qc.clear();
    },
  });
}

export function useForgotPassword() {
  return useMutation({ mutationFn: authApi.forgotPassword });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: ({ token, body }: { token: string; body: ResetPasswordRequest }) =>
      authApi.resetPassword(token, body),
  });
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: (data) => {
      qc.setQueryData(['me'], data);
    },
  });
}
