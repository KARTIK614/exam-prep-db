import { Moon, Sun } from 'lucide-react';

import { useTheme } from '@/hooks/useTheme';
import { Button } from '@/components/ui/button';

/** Icon-button toggle between the light and dark themes. */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const isDark = theme === 'dark';
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
