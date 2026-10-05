import type { QType } from '@/lib/api/types';

/**
 * Client-side mirror of `backend/src/services/grading.rs`, used where the
 * FE grades on its own (review re-attempts) and to display answers.
 *
 * Encoding: MCQ "B" (or "A;B" = either accepted, "MTA" = marks to all),
 * MSQ "A;C" (exact set, no partial credit), NAT "lo:hi" inclusive range.
 */

const letters = (s: string) =>
  Array.from(new Set(s.toUpperCase().match(/[A-D]/g) ?? [])).sort();

function natRange(key: string): [number, number] | null {
  const parts = key.includes(':') ? key.split(':') : key.split(/\s+to\s+/);
  const nums = parts.map((p) => Number(p.trim()));
  const a = nums[0];
  const b = nums.length === 2 ? nums[1] : a;
  if (a === undefined || b === undefined || nums.length > 2 || Number.isNaN(a) || Number.isNaN(b)) return null;
  return [Math.min(a, b), Math.max(a, b)];
}

export function isCorrect(qtype: QType, key: string | null | undefined, response: string | null | undefined): boolean {
  const k = key?.trim() ?? '';
  const r = response?.trim() ?? '';
  if (!k || !r) return false;
  if (k.toUpperCase() === 'MTA') return true;
  if (qtype === 'MSQ') {
    const kk = letters(k);
    return kk.length > 0 && kk.join(';') === letters(r).join(';');
  }
  if (qtype === 'NAT') {
    const range = natRange(k);
    const v = Number(r);
    return range !== null && !Number.isNaN(v) && v >= range[0] - 1e-9 && v <= range[1] + 1e-9;
  }
  return k.split(';').some((x) => x.trim().toUpperCase() === r.toUpperCase());
}

/** Human-readable answer: "A, C" for MSQ, "0.32 – 0.34" for a NAT range. */
export function formatAnswer(qtype: QType, value: string | null | undefined): string {
  if (!value) return '—';
  if (value.toUpperCase() === 'MTA') return 'Marks to all';
  if (qtype === 'NAT' && value.includes(':')) {
    const [lo = '', hi = ''] = value.split(':');
    return lo === hi ? lo : `${lo} – ${hi}`;
  }
  if (qtype === 'MSQ' || value.includes(';')) return value.split(';').join(', ');
  return value;
}

/** Toggle one letter in an MSQ answer string ("A;C" + "B" → "A;B;C"). */
export function toggleLetter(current: string | null, letter: string): string | null {
  const set = new Set(current ? current.split(';').filter(Boolean) : []);
  if (set.has(letter)) set.delete(letter);
  else set.add(letter);
  return set.size ? Array.from(set).sort().join(';') : null;
}

export const TYPE_LABEL: Record<QType, string> = {
  MCQ: 'Single answer',
  MSQ: 'Multiple correct',
  NAT: 'Numerical',
};
