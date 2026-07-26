import { Outlet } from 'react-router-dom';

import { useTheme } from '@/hooks/useTheme';

/**
 * Root <App /> element.
 *
 * Providers (QueryClient, Router) are mounted in `main.tsx` so they wrap
 * the router itself. This component sits *inside* the router tree so its
 * children can call react-router hooks (which is why the theme sync lives
 * here — it doesn't need router, but this is a convenient shared root).
 *
 * The layout shell (sidebar/topbar) is provided by `<Layout />` under
 * `<ProtectedRoute />`, not here — public pages render full-bleed.
 */
export function App() {
  // Side-effect only: syncs `data-theme` on <html>. Reading it into a var
  // is unnecessary; the hook mutates the DOM on mount + on change.
  useTheme();

  return <Outlet />;
}
