import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  BarChart3,
  BookMarked,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  PenSquare,
  Repeat,
  Search,
  Shield,
  User,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ThemeToggle } from '@/components/ThemeToggle';
import { useAuth } from '@/hooks/useAuth';
import { useLogout } from '@/lib/api/auth';
import { useReviewQueue } from '@/lib/api/review';
import { cn } from '@/lib/utils/cn';
import { shortcutsEnabled } from '@/lib/utils/keyboard';

/**
 * Authenticated app shell — sidebar + main content column.
 *
 * Phase 9 additions:
 *   - "Take Test" link routes to `/test/new`.
 *   - "Review" link with an SR-due badge (from `GET /review/queue`).
 *   - Admin link shown only when `user.role === 'admin'`.
 *   - Mobile bottom-nav at <= sm breakpoint (Dashboard/Test/Analytics/
 *     Search/Profile icons).
 *   - Cmd-K / Ctrl-K jumps to /search (modal deferred to a later phase).
 */
const BASE_NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/test/new', label: 'Take Test', icon: PenSquare },
  { to: '/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/review', label: 'Review', icon: Repeat },
  { to: '/errors', label: 'Error Log', icon: History },
  { to: '/bookmarks', label: 'Bookmarks', icon: BookMarked },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/profile', label: 'Profile', icon: User },
] as const;

const BOTTOM_NAV = [
  { to: '/dashboard', label: 'Home', icon: LayoutDashboard },
  { to: '/test/new', label: 'Test', icon: PenSquare },
  { to: '/analytics', label: 'Stats', icon: BarChart3 },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/profile', label: 'Me', icon: User },
] as const;

export function Layout() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const logout = useLogout();
  const [mobileOpen, setMobileOpen] = useState(false);

  // SR-due badge — light-touch fetch on mount; failure is non-fatal.
  const review = useReviewQueue({ limit: 0 });
  const dueToday = review.data?.summary?.due_today ?? 0;

  const isAdmin = user?.role === 'admin';

  const handleLogout = async () => {
    await logout.mutateAsync();
    navigate('/login', { replace: true });
  };

  // Cmd-K / Ctrl-K → /search
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        navigate('/search');
        return;
      }
      // Global "g s" style shortcut skipped; keep it simple.
      if (!shortcutsEnabled()) return;
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [navigate]);

  return (
    <div className="flex h-screen w-screen bg-bg-primary text-text-primary">
      {/* Sidebar (desktop) */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-bg-secondary md:flex">
        <div className="flex h-14 items-center border-b border-border px-4 font-semibold">
          Exam Prep
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {BASE_NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'relative flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-text-primary hover:bg-muted',
                )
              }
            >
              <Icon className="h-4 w-4" />
              <span>{label}</span>
              {to === '/review' && dueToday > 0 ? (
                <span className="ml-auto rounded-full bg-warning/25 px-1.5 text-xs text-warning">
                  {dueToday}
                </span>
              ) : null}
            </NavLink>
          ))}
          {isAdmin ? (
            <NavLink
              to="/admin"
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-text-primary hover:bg-muted',
                )
              }
            >
              <Shield className="h-4 w-4" />
              <span>Admin</span>
            </NavLink>
          ) : null}
        </nav>
        <div className="border-t border-border p-3 text-sm">
          <div className="mb-2 truncate text-muted-foreground">
            {user?.username ?? '—'}
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start"
            onClick={handleLogout}
            disabled={logout.isPending}
          >
            <LogOut className="mr-2 h-4 w-4" /> Log out
          </Button>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              aria-label="Toggle navigation"
              onClick={() => setMobileOpen((v) => !v)}
            >
              <Menu className="h-4 w-4" />
            </Button>
            <div className="font-semibold md:hidden">Exam Prep</div>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
          </div>
        </header>

        {/* Mobile drawer */}
        {mobileOpen && (
          <nav className="space-y-1 border-b border-border bg-bg-secondary p-2 md:hidden">
            {BASE_NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2 rounded-md px-3 py-2 text-sm',
                    isActive
                      ? 'bg-primary text-primary-foreground'
                      : 'text-text-primary hover:bg-muted',
                  )
                }
              >
                <Icon className="h-4 w-4" />
                <span>{label}</span>
                {to === '/review' && dueToday > 0 ? (
                  <span className="ml-auto rounded-full bg-warning/25 px-1.5 text-xs text-warning">
                    {dueToday}
                  </span>
                ) : null}
              </NavLink>
            ))}
            {isAdmin ? (
              <NavLink
                to="/admin"
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2 rounded-md px-3 py-2 text-sm',
                    isActive
                      ? 'bg-primary text-primary-foreground'
                      : 'text-text-primary hover:bg-muted',
                  )
                }
              >
                <Shield className="h-4 w-4" />
                <span>Admin</span>
              </NavLink>
            ) : null}
            <Button
              variant="ghost"
              size="sm"
              className="mt-2 w-full justify-start"
              onClick={handleLogout}
              disabled={logout.isPending}
            >
              <LogOut className="mr-2 h-4 w-4" /> Log out
            </Button>
          </nav>
        )}

        <main className="min-h-0 flex-1 overflow-y-auto p-4 pb-24 sm:p-6 sm:pb-6">
          <Outlet />
        </main>

        {/* Mobile bottom nav (<= sm) */}
        <nav
          className="fixed bottom-0 left-0 right-0 z-40 flex items-stretch border-t border-border bg-bg-secondary sm:hidden"
          aria-label="Bottom navigation"
        >
          {BOTTOM_NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex flex-1 flex-col items-center justify-center gap-1 py-2 text-[10px]',
                  isActive ? 'text-primary' : 'text-muted-foreground',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
