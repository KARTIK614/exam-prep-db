import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merge Tailwind class names — clsx for conditional composition,
 * tailwind-merge for de-duplicating conflicting utilities. Standard
 * shadcn/ui convention; every UI primitive imports this from
 * `@/lib/utils/cn`.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
