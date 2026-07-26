import { useEffect } from 'react';

import { useMe } from '@/lib/api/auth';
import { useAuthStore } from '@/stores/authStore';

/**
 * `useAuth` — public interface for auth state.
 *
 * Composes the Zustand store with a `useMe()` query that runs whenever we
 * have an access token but no cached user. Any consumer can read
 * `{ user, isAuthenticated, isLoading }` without worrying about hydration
 * timing.
 */
export function useAuth() {
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const setHydrated = useAuthStore((s) => s.setHydrated);
  const hydrated = useAuthStore((s) => s.hydrated);

  const meQuery = useMe();

  // Mirror the query result into the Zustand store so components that
  // subscribe to `user` (without pulling in Query) see updates.
  useEffect(() => {
    if (meQuery.data) {
      setUser(meQuery.data);
      setHydrated(true);
    } else if (meQuery.isError) {
      // API client already handled 401; here we just flip hydrated.
      setHydrated(true);
    } else if (!accessToken) {
      setHydrated(true);
    }
  }, [meQuery.data, meQuery.isError, accessToken, setUser, setHydrated]);

  return {
    user,
    accessToken,
    isAuthenticated: Boolean(accessToken && user),
    isLoading: Boolean(accessToken) && meQuery.isPending && !user,
    hydrated,
  };
}
