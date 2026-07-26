import { useEffect } from 'react';

import { useThemeStore, type Theme } from '@/stores/themeStore';

/**
 * `useTheme` — read + write the active theme.
 *
 * Side-effect: mirrors the current theme onto `<html data-theme=...>` so
 * every Tailwind rule that references our CSS variables picks up the new
 * palette. Persistence and cross-tab sync are handled by the store.
 */
export function useTheme() {
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);
  const toggle = useThemeStore((s) => s.toggle);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  return {
    theme,
    setTheme: (t: Theme) => setTheme(t),
    toggle,
  };
}
