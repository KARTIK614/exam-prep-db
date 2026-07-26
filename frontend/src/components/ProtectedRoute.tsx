import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { useAuth } from '@/hooks/useAuth';

/**
 * Router guard for authenticated routes.
 *
 * Behaviour:
 *   - While `hydrated === false` we render a minimal splash so we don't
 *     flash the login page for an already-signed-in user.
 *   - If unauthenticated after hydration, redirect to `/login?next=<current>`.
 *   - Otherwise render the nested `<Outlet />`.
 *
 * Admin gating (`requireAdmin`) is stubbed until Phase 9; today it only
 * checks `user.role === 'admin'` and redirects unauthorized users to
 * `/dashboard`.
 */
interface ProtectedRouteProps {
  requireAdmin?: boolean;
}

export function ProtectedRoute({ requireAdmin = false }: ProtectedRouteProps) {
  const { user, isAuthenticated, hydrated, isLoading } = useAuth();
  const location = useLocation();

  if (!hydrated || isLoading) {
    return (
      <div
        role="status"
        aria-busy="true"
        className="flex h-screen items-center justify-center text-muted-foreground"
      >
        Loading…
      </div>
    );
  }

  if (!isAuthenticated) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  if (requireAdmin && user?.role !== 'admin') {
    // Phase 9 will render a proper Forbidden page.
    return <Navigate to="/dashboard" replace />;
  }

  return <Outlet />;
}

/**
 * Redirects already-authenticated users away from public-only routes
 * (login/signup/forgot/reset). Used by `router.tsx` around those pages.
 */
export function PublicOnlyRoute() {
  const { isAuthenticated, hydrated } = useAuth();
  if (!hydrated) {
    return (
      <div className="flex h-screen items-center justify-center text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }
  return <Outlet />;
}
