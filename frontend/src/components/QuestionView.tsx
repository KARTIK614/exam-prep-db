import { useEffect, useState } from 'react';

import type { Confidence, QType } from '@/lib/api/types';
import { formatAnswer, toggleLetter } from '@/lib/utils/grading';
import { cn } from '@/lib/utils/cn';

/**
 * Shared question pieces for TakeTest, Review and TestResults.
 *
 * Official papers are stored as images (`image_url`) so maths and diagrams
 * stay exactly as printed. Their options live inside the image, so the
 * answer buttons show letters only.
 */

type Letter = 'A' | 'B' | 'C' | 'D';
const LETTERS: Letter[] = ['A', 'B', 'C', 'D'];

export interface QuestionLike {
  question_text: string | null;
  image_url?: string | null;
  option_a?: string | null;
  option_b?: string | null;
  option_c?: string | null;
  option_d?: string | null;
}

export function QuestionBody({ q, className }: { q: QuestionLike; className?: string }) {
  if (q.image_url) {
    return (
      <div className={cn('overflow-x-auto rounded-md bg-white p-2 sm:p-3', className)}>
        <img
          src={q.image_url}
          alt={q.question_text ?? 'Question'}
          className="mx-auto h-auto w-full max-w-[760px] select-none"
          loading="lazy"
          draggable={false}
        />
      </div>
    );
  }
  return (
    <div className={cn('whitespace-pre-wrap text-base leading-relaxed', className)}>
      {q.question_text ?? '(question text missing)'}
    </div>
  );
}

function optionText(q: QuestionLike, l: Letter): string | null {
  return (q[`option_${l.toLowerCase()}` as 'option_a'] as string | null | undefined) ?? null;
}

/**
 * Answer control for MCQ (one letter), MSQ (any set of letters) and NAT
 * (a number). `value` uses the stored encoding: "B", "A;C", "2.5".
 *
 * `reveal` (review/results) colours the key green and a wrong pick red.
 */
export function AnswerInput({
  qtype,
  q,
  value,
  onChange,
  disabled,
  reveal,
}: {
  qtype: QType;
  q: QuestionLike;
  value: string | null;
  onChange: (next: string | null) => void;
  disabled?: boolean;
  reveal?: { key: string | null };
}) {
  if (qtype === 'NAT') {
    return <NatInput value={value} onCommit={onChange} disabled={disabled} reveal={reveal} />;
  }
  const imageMode = Boolean(q.image_url);
  const chosen = new Set(value ? value.split(';') : []);
  const keySet = new Set(reveal?.key ? reveal.key.split(';') : []);
  const pick = (l: Letter) => {
    if (disabled) return;
    onChange(qtype === 'MSQ' ? toggleLetter(value, l) : value === l ? null : l);
  };

  return (
    <div>
      <div className="mb-2 text-xs text-muted-foreground">
        {qtype === 'MSQ' ? 'Select every correct option (no partial marks).' : 'Select one option.'}
      </div>
      <div className={cn(imageMode ? 'grid grid-cols-4 gap-2' : 'space-y-2')}>
        {LETTERS.map((l) => {
          const text = optionText(q, l);
          if (!imageMode && !text) return null;
          const on = chosen.has(l);
          const isKey = reveal ? keySet.has(l) : false;
          const wrongPick = reveal ? on && !isKey : false;
          return (
            <button
              type="button"
              key={l}
              onClick={() => pick(l)}
              disabled={disabled}
              aria-pressed={on}
              className={cn(
                'flex items-start gap-3 rounded-md border p-3 text-left text-sm transition-colors',
                imageMode && 'justify-center',
                isKey
                  ? 'border-success bg-success/10'
                  : wrongPick
                    ? 'border-destructive bg-destructive/10'
                    : on
                      ? 'border-primary bg-primary/10'
                      : 'border-border bg-bg-primary hover:bg-muted',
                disabled && 'cursor-default',
              )}
            >
              <span
                className={cn(
                  'flex h-6 w-6 shrink-0 items-center justify-center border text-xs font-semibold',
                  qtype === 'MSQ' ? 'rounded' : 'rounded-full',
                  on ? 'border-primary bg-primary text-primary-foreground' : 'border-border',
                )}
              >
                {l}
              </span>
              {!imageMode && text ? <span className="whitespace-pre-wrap">{text}</span> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Numeric answer. Commits on blur / Enter so autosave isn't fired per keystroke. */
function NatInput({
  value,
  onCommit,
  disabled,
  reveal,
}: {
  value: string | null;
  onCommit: (next: string | null) => void;
  disabled?: boolean;
  reveal?: { key: string | null };
}) {
  const [draft, setDraft] = useState(value ?? '');
  useEffect(() => setDraft(value ?? ''), [value]);
  const valid = draft.trim() === '' || /^-?\d*\.?\d+$|^-?\d+\.$/.test(draft.trim());
  const commit = () => {
    const v = draft.trim();
    if (!valid) return;
    if ((v || null) !== (value ?? null)) onCommit(v === '' ? null : v.replace(/\.$/, ''));
  };
  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground" htmlFor="nat-answer">
        Numerical answer (type the value; no options)
      </label>
      <input
        id="nat-answer"
        inputMode="decimal"
        autoComplete="off"
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            // Enter only commits this field; don't let the page-level
            // "Enter = save & next" shortcut see it once focus has left.
            e.preventDefault();
            e.stopPropagation();
            commit();
            (e.target as HTMLInputElement).blur();
          }
        }}
        className={cn(
          'w-48 rounded-md border bg-background px-3 py-2 font-mono text-base tabular-nums',
          valid ? 'border-input' : 'border-destructive',
        )}
        placeholder="e.g. 2.5"
      />
      {!valid ? <div className="text-xs text-destructive">Enter a number, like 12 or -0.75.</div> : null}
      {reveal ? (
        <div className="text-sm">
          Accepted: <b className="font-mono">{formatAnswer('NAT', reveal.key)}</b>
        </div>
      ) : null}
    </div>
  );
}

const CONFIDENCE: { value: Confidence; label: string; hint: string; key: string }[] = [
  { value: 'sure', label: 'Sure', hint: 'I know this', key: 'S' },
  { value: 'unsure', label: 'Unsure', hint: 'Narrowed it down', key: 'U' },
  { value: 'guess', label: 'Guess', hint: 'Lucky shot', key: 'G' },
];

/** How sure the student was. A correct guess is treated as a gap, not a win. */
export function ConfidencePicker({
  value,
  onChange,
  disabled,
}: {
  value: Confidence | null;
  onChange: (c: Confidence | null) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="How sure are you?">
      <span className="text-xs text-muted-foreground">How sure?</span>
      {CONFIDENCE.map((c) => (
        <button
          type="button"
          key={c.value}
          role="radio"
          aria-checked={value === c.value}
          disabled={disabled}
          title={`${c.hint} (${c.key})`}
          onClick={() => onChange(value === c.value ? null : c.value)}
          className={cn(
            'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
            value === c.value
              ? c.value === 'sure'
                ? 'border-success bg-success/15 text-success'
                : c.value === 'unsure'
                  ? 'border-warning bg-warning/15 text-warning'
                  : 'border-destructive bg-destructive/15 text-destructive'
              : 'border-border text-muted-foreground hover:bg-muted',
          )}
        >
          {c.label} <span className="opacity-60">{c.key}</span>
        </button>
      ))}
    </div>
  );
}

export function ConfidenceBadge({ value }: { value: Confidence | null }) {
  if (!value) return null;
  const tone =
    value === 'sure' ? 'bg-success/15 text-success' : value === 'unsure' ? 'bg-warning/15 text-warning' : 'bg-destructive/15 text-destructive';
  return <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', tone)}>{value}</span>;
}
