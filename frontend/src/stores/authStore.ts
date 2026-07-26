import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

import type { MeResponse } from '@/lib/api/types';

/**
 * Auth store: holds the current session's access token, refresh token,
 * and cached `MeResponse`.
 *
 * Tokens are persisted to localStorage per the Phase 8 spec. This is a
 * pragmatic choice for the solo-user scaffolding stage; the R3 plan
 * §7.2 recommends migrating to httpOnly cookies once the backend
 * publishes CORS-with-credentials and a `/api/auth/me` cookie flow.
 * That migration is a swap of this store's persistence layer — the
 * `useAuth` API stays stable.
 *
 * State transitions:
 *   - `setSession()`     — called on successful login/register/refresh
 *   - `setUser()`        — called after GET /api/v1/me on boot
 *   - `clear()`          — called on logout or terminal 401
 *
 * XSS caveat: any script running in the origin can read these tokens.
 * We accept that risk for Phase 8 in exchange for a simpler backend
 * contract. Do not log the tokens.
 */

export interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: MeResponse | null;
  /** True once we've attempted the initial `/me` bootstrap. */
  hydrated: boolean;

  setSession: (tokens: { accessToken: string; refreshToken: string }) => void;
  setTokens: (tokens: { accessToken: string; refreshToken: string }) => void;
  setUser: (user: MeResponse | null) => void;
  setHydrated: (v: boolean) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      hydrated: false,

      setSession: ({ accessToken, refreshToken }) =>
        set({ accessToken, refreshToken }),

      setTokens: ({ accessToken, refreshToken }) =>
        set({ accessToken, refreshToken }),

      setUser: (user) => set({ user }),

      setHydrated: (v) => set({ hydrated: v }),

      clear: () =>
        set({
          accessToken: null,
          refreshToken: null,
          user: null,
        }),
    }),
    {
      name: 'exam-prep-auth',
      storage: createJSONStorage(() => localStorage),
      // Only persist the tokens + user; `hydrated` is a runtime concern.
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
      }),
    },
  ),
);
