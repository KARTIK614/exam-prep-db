import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type Theme = 'light' | 'dark';

/**
 * Theme store: `light` | `dark`, mirrored to localStorage under the key
 * `theme` as a bare string via a custom storage adapter (so the inline
 * script in `index.html` can read it before React mounts).
 *
 * The store does NOT touch the DOM itself; `useTheme` in `hooks/useTheme.ts`
 * subscribes and mirrors the value onto `<html data-theme=...>`. Keeping the
 * DOM mutation in a hook makes the store trivially unit-testable.
 */
interface ThemeState {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
}

// Custom storage that writes the theme as a bare string, not a JSON
// envelope — so the FOUC script in index.html reads `localStorage.getItem('theme')`
// and gets `'light'` / `'dark'` directly.
const themeStorage = {
  getItem: (name: string): string | null => {
    const value = localStorage.getItem(name);
    if (value === 'light' || value === 'dark') {
      // Wrap the bare value in the Zustand persist envelope on the fly.
      return JSON.stringify({ state: { theme: value }, version: 0 });
    }
    return null;
  },
  setItem: (name: string, value: string): void => {
    try {
      const parsed = JSON.parse(value) as { state?: { theme?: Theme } };
      const theme = parsed?.state?.theme;
      if (theme === 'light' || theme === 'dark') {
        localStorage.setItem(name, theme);
      }
    } catch {
      // Ignore malformed input; keep whatever's there.
    }
  },
  removeItem: (name: string): void => {
    localStorage.removeItem(name);
  },
};

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'light',
      setTheme: (theme) => set({ theme }),
      toggle: () =>
        set((s) => ({ theme: s.theme === 'light' ? 'dark' : 'light' })),
    }),
    {
      name: 'theme',
      storage: createJSONStorage(() => themeStorage),
      partialize: (state) => ({ theme: state.theme }),
    },
  ),
);
