import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Flag, HelpCircle, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  useFinishTest,
  useMarkForReview,
  useSubmitAnswer,
  useTest,
} from '@/lib/api/tests';
import { useSubmitFlag } from '@/lib/api/flags';
import { shortcutsEnabled } from '@/lib/utils/keyboard';
import { cn } from '@/lib/utils/cn';
import type { FlagCategory } from '@/lib/api/types';

/**
 * TakeTest — the exam-taking screen.
 *
 * Layout:
 *   ┌───────────────────────────────────────┬──────────────┐
 *   │ Question card                         │ Palette      │
 *   │ (statement, options, actions)         │ (180px wide) │
 *   │                                       │              │
 *   ├───────────────────────────────────────┴──────────────┤
 *   │ Bottom bar: Prev / Save+Next / Mark / Clear / Finish │
 *   └──────────────────────────────────────────────────────┘
 *
 * Timer runs top-right (count-up per question).
 *
 * Keyboard shortcuts (see `useEffect` block below):
 *   A/B/C/D  → select option, save, advance
 *   Enter    → save + next (finish confirm on last)
 *   ← →      → prev / next (also 1..9 for jump to palette cell)
 *   M        → toggle mark for review
 *   F        → open flag modal
 *   ?        → open help modal
 *   Ctrl+Enter → finish (with confirm)
 *
 * State model: we maintain a local mirror of {selection, marked, time}
 * per question so the UI can respond immediately, then POST autosave to
 * `/api/v1/tests/:id/answers` on every change. `GET /tests/:id` on mount
 * hydrates the mirror from the server (resume after refresh).
 *
 * Palette colour spec (TCS-iON conventions):
 *   not_visited      grey  #a0a0a0
 *   not_answered     red   #e74c3c   (visited but no selection)
 *   answered         green #27ae60
 *   review           purple #8b3a97  (marked, no selection)
 *   answered_review  green + green-corner dot
 *   current          blue outline
 */

type Selection = 'A' | 'B' | 'C' | 'D' | null;
interface LocalAnswer {
  selected: Selection;
  marked: boolean;
  timeSpent: number;
  visited: boolean;
}

export default function TakeTest() {
  const { id } = useParams<{ id: string }>();
  const testId = Number(id);
  const navigate = useNavigate();
  const test = useTest(testId);
  const submitAnswer = useSubmitAnswer(testId);
  const markForReview = useMarkForReview(testId);
  const finish = useFinishTest(testId);
  const submitFlag = useSubmitFlag();

  const questions = test.data?.questions ?? [];
  const total = questions.length;

  // ---------- local mirror --------------------------------
  const [answers, setAnswers] = useState<Record<number, LocalAnswer>>({});
  const [currentIdx, setCurrentIdx] = useState(0);
  const [showFinish, setShowFinish] = useState(false);
  const [showFlag, setShowFlag] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [flagCategory, setFlagCategory] = useState<FlagCategory>('wrong_answer');
  const [flagNote, setFlagNote] = useState('');

  // Timer: per-question count-up.
  const [elapsed, setElapsed] = useState(0);
  const questionStartRef = useRef<number>(Date.now());

  // Hydrate local mirror from server on load.
  useEffect(() => {
    if (!test.data) return;
    const seed: Record<number, LocalAnswer> = {};
    for (const q of test.data.questions) {
      seed[q.id] = {
        selected: null,
        marked: false,
        timeSpent: 0,
        visited: false,
      };
    }
    for (const r of test.data.responses) {
      seed[r.question_id] = {
        selected: (r.selected_option as Selection) ?? null,
        marked: r.marked_for_review,
        timeSpent: r.time_spent_sec ?? 0,
        visited: true,
      };
    }
    // Current index defaults to first non-answered.
    setAnswers(seed);
    const firstUnanswered = test.data.questions.findIndex(
      (q) => !seed[q.id]?.selected,
    );
    setCurrentIdx(firstUnanswered < 0 ? 0 : firstUnanswered);
    questionStartRef.current = Date.now();
    setElapsed(0);
  }, [test.data]);

  const currentQ = questions[currentIdx];

  // Per-question timer ticker.
  useEffect(() => {
    if (!currentQ) return;
    const t = setInterval(() => {
      setElapsed(Math.floor((Date.now() - questionStartRef.current) / 1000));
    }, 1000);
    return () => clearInterval(t);
  }, [currentQ, currentIdx]);

  // Reset timer when question changes.
  useEffect(() => {
    questionStartRef.current = Date.now();
    setElapsed(0);
    // Mark visited on entry.
    if (currentQ) {
      setAnswers((prev) => ({
        ...prev,
        [currentQ.id]: { ...(prev[currentQ.id] ?? blank()), visited: true },
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentIdx]);

  // ---------- server sync helpers -------------------------

  const persistAnswer = useCallback(
    (qid: number, patch: Partial<LocalAnswer>) => {
      setAnswers((prev) => {
        const before = prev[qid] ?? blank();
        const next = { ...before, ...patch };
        // Fire and forget — errors are swallowed since local state is authoritative.
        submitAnswer.mutate({
          question_id: qid,
          selected_option: next.selected ?? null,
          marked_for_review: next.marked,
          time_spent_sec: Math.round(next.timeSpent),
        });
        return { ...prev, [qid]: next };
      });
    },
    [submitAnswer],
  );

  const snapshotElapsed = useCallback(() => {
    if (!currentQ) return 0;
    const seconds = Math.floor((Date.now() - questionStartRef.current) / 1000);
    return (answers[currentQ.id]?.timeSpent ?? 0) + seconds;
  }, [answers, currentQ]);

  const goto = useCallback(
    (nextIdx: number) => {
      if (!currentQ) return;
      if (nextIdx < 0 || nextIdx >= total) return;
      // Flush current time-spent before switching.
      persistAnswer(currentQ.id, { timeSpent: snapshotElapsed() });
      setCurrentIdx(nextIdx);
    },
    [currentQ, total, persistAnswer, snapshotElapsed],
  );

  const selectOption = useCallback(
    (opt: 'A' | 'B' | 'C' | 'D') => {
      if (!currentQ) return;
      persistAnswer(currentQ.id, {
        selected: opt,
        timeSpent: snapshotElapsed(),
      });
    },
    [currentQ, persistAnswer, snapshotElapsed],
  );

  const clearSelection = useCallback(() => {
    if (!currentQ) return;
    persistAnswer(currentQ.id, { selected: null, timeSpent: snapshotElapsed() });
  }, [currentQ, persistAnswer, snapshotElapsed]);

  const toggleMark = useCallback(() => {
    if (!currentQ) return;
    const now = !answers[currentQ.id]?.marked;
    persistAnswer(currentQ.id, { marked: now, timeSpent: snapshotElapsed() });
    markForReview.mutate({ question_id: currentQ.id, marked: now });
  }, [answers, currentQ, markForReview, persistAnswer, snapshotElapsed]);

  const saveAndNext = useCallback(() => {
    if (!currentQ) return;
    persistAnswer(currentQ.id, { timeSpent: snapshotElapsed() });
    if (currentIdx === total - 1) {
      setShowFinish(true);
    } else {
      setCurrentIdx((i) => Math.min(i + 1, total - 1));
    }
  }, [currentIdx, currentQ, persistAnswer, snapshotElapsed, total]);

  const handleFinish = useCallback(async () => {
    try {
      // Persist last question's timer.
      if (currentQ) {
        persistAnswer(currentQ.id, { timeSpent: snapshotElapsed() });
      }
      await finish.mutateAsync();
      navigate(`/test/${testId}/results`);
    } catch (err) {
      console.error('finish failed', err);
    }
  }, [currentQ, finish, navigate, persistAnswer, snapshotElapsed, testId]);

  // ---------- keyboard shortcuts --------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!shortcutsEnabled()) return;
      const key = e.key;

      if (e.ctrlKey && (key === 'Enter' || key === 'Return')) {
        e.preventDefault();
        setShowFinish(true);
        return;
      }

      if (key === '?') {
        e.preventDefault();
        setShowHelp(true);
        return;
      }

      switch (key.toLowerCase()) {
        case 'a':
          e.preventDefault();
          selectOption('A');
          setTimeout(saveAndNext, 100);
          break;
        case 'b':
          e.preventDefault();
          selectOption('B');
          setTimeout(saveAndNext, 100);
          break;
        case 'c':
          e.preventDefault();
          selectOption('C');
          setTimeout(saveAndNext, 100);
          break;
        case 'd':
          e.preventDefault();
          selectOption('D');
          setTimeout(saveAndNext, 100);
          break;
        case 'enter':
          e.preventDefault();
          saveAndNext();
          break;
        case 'arrowleft':
          e.preventDefault();
          goto(currentIdx - 1);
          break;
        case 'arrowright':
          e.preventDefault();
          goto(currentIdx + 1);
          break;
        case 'm':
          e.preventDefault();
          toggleMark();
          break;
        case 'f':
          e.preventDefault();
          setShowFlag(true);
          break;
        default:
          // 1-9 → jump to palette cell
          if (/^[1-9]$/.test(key)) {
            e.preventDefault();
            goto(Number(key) - 1);
          }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [currentIdx, goto, saveAndNext, selectOption, toggleMark]);

  // ---------- palette --------------------------------------

  const paletteEntries = useMemo(() => {
    return questions.map((q, idx) => {
      const a = answers[q.id];
      const state = paletteState(a);
      return { idx, id: q.id, state, current: idx === currentIdx };
    });
  }, [answers, currentIdx, questions]);

  // ---------- render ---------------------------------------

  if (test.isLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" /> Loading test…
      </div>
    );
  }
  if (test.isError || !test.data || !currentQ) {
    return (
      <div className="mx-auto max-w-md space-y-2 p-6 text-center">
        <p className="text-lg font-medium">Couldn't load this test.</p>
        <p className="text-sm text-muted-foreground">
          It may have been finished or belong to another account.
        </p>
        <Button onClick={() => navigate('/dashboard')}>Back to dashboard</Button>
      </div>
    );
  }

  const timerColor =
    elapsed >= 90
      ? 'text-destructive'
      : elapsed >= 60
        ? 'text-warning'
        : 'text-text-primary';

  const current = answers[currentQ.id] ?? blank();

  return (
    <div className="flex h-full flex-col lg:flex-row lg:gap-6">
      {/* Main question column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top row: progress + timer */}
        <div className="mb-4 flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            Question {currentIdx + 1} of {total}
          </div>
          <div className="flex items-center gap-3">
            <div className={cn('font-mono text-sm tabular-nums', timerColor)}>
              {formatSec(elapsed)}
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setShowHelp(true)}
              aria-label="Show keyboard shortcuts"
            >
              <HelpCircle className="h-4 w-4" />
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setShowFinish(true)}
            >
              Finish
            </Button>
          </div>
        </div>

        {/* Question card */}
        <div className="flex-1 rounded-lg border border-border bg-bg-secondary p-4 sm:p-6">
          <div className="whitespace-pre-wrap text-base leading-relaxed">
            {currentQ.question_text ?? '(question text missing)'}
          </div>
          <div className="mt-4 space-y-2">
            {(['A', 'B', 'C', 'D'] as const).map((opt) => {
              const text = currentQ[`option_${opt.toLowerCase()}` as
                | 'option_a'
                | 'option_b'
                | 'option_c'
                | 'option_d'];
              if (!text) return null;
              const on = current.selected === opt;
              return (
                <button
                  type="button"
                  key={opt}
                  onClick={() => selectOption(opt)}
                  className={cn(
                    'flex w-full items-start gap-3 rounded-md border p-3 text-left text-sm transition-colors',
                    on
                      ? 'border-primary bg-primary/10'
                      : 'border-border bg-bg-primary hover:bg-muted',
                  )}
                >
                  <span
                    className={cn(
                      'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold',
                      on
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border',
                    )}
                  >
                    {opt}
                  </span>
                  <span className="whitespace-pre-wrap">{text}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Bottom actions */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => goto(currentIdx - 1)}
            disabled={currentIdx === 0}
          >
            Prev
          </Button>
          <Button onClick={saveAndNext}>
            {currentIdx === total - 1 ? 'Save & Finish' : 'Save & Next'}
          </Button>
          <Button
            variant={current.marked ? 'default' : 'secondary'}
            onClick={toggleMark}
          >
            {current.marked ? 'Unmark' : 'Mark for review'}
          </Button>
          <Button variant="ghost" onClick={clearSelection}>
            Clear
          </Button>
          <Button variant="ghost" onClick={() => setShowFlag(true)}>
            <Flag className="mr-1 h-4 w-4" /> Flag
          </Button>
        </div>
      </div>

      {/* Palette sidebar */}
      <aside className="mt-6 shrink-0 rounded-lg border border-border bg-bg-secondary p-3 lg:mt-0 lg:w-[220px]">
        <div className="mb-2 text-xs font-medium text-muted-foreground">
          Palette
        </div>
        <div className="grid grid-cols-5 gap-1.5 lg:grid-cols-5">
          {paletteEntries.map((p) => (
            <PaletteCell key={p.id} entry={p} onClick={() => goto(p.idx)} />
          ))}
        </div>
        <PaletteLegend />
      </aside>

      {/* Finish confirmation modal */}
      <Dialog open={showFinish} onOpenChange={setShowFinish}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Finish this test?</DialogTitle>
            <DialogDescription>
              You'll see your score and per-topic breakdown next. This action is
              not reversible.
            </DialogDescription>
          </DialogHeader>
          <div className="text-sm">
            <span className="font-medium">Answered:</span>{' '}
            {countAnswered(answers, questions.map((q) => q.id))} / {total}
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setShowFinish(false)}>
              Keep going
            </Button>
            <Button onClick={handleFinish} disabled={finish.isPending}>
              {finish.isPending ? 'Submitting…' : 'Finish'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Flag modal */}
      <Dialog open={showFlag} onOpenChange={setShowFlag}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Flag this question</DialogTitle>
            <DialogDescription>
              Tell an admin what's wrong. We'll review it.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <fieldset className="space-y-1">
              <legend className="mb-1 text-sm font-medium">Category</legend>
              {(
                [
                  ['wrong_answer', 'Wrong answer'],
                  ['ambiguous', 'Ambiguous / unclear'],
                  ['typo_question', 'Typo in question'],
                  ['typo_options', 'Typo in options'],
                  ['explanation_missing', 'Explanation missing / wrong'],
                  ['duplicate', 'Duplicate of another question'],
                  ['other', 'Other'],
                ] as [FlagCategory, string][]
              ).map(([val, label]) => (
                <label
                  key={val}
                  className="flex items-center gap-2 text-sm"
                >
                  <input
                    type="radio"
                    name="flag-category"
                    checked={flagCategory === val}
                    onChange={() => setFlagCategory(val)}
                  />
                  {label}
                </label>
              ))}
            </fieldset>
            <div>
              <Label htmlFor="flag-note">
                Note{flagCategory === 'other' ? ' (required)' : ''}
              </Label>
              <textarea
                id="flag-note"
                value={flagNote}
                onChange={(e) => setFlagNote(e.target.value)}
                rows={3}
                className="mt-1 w-full rounded-md border border-input bg-background p-2 text-sm"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setShowFlag(false)}>
              Cancel
            </Button>
            <Button
              onClick={async () => {
                if (flagCategory === 'other' && !flagNote.trim()) return;
                await submitFlag.mutateAsync({
                  questionId: currentQ.id,
                  body: {
                    category: flagCategory,
                    note: flagNote.trim() || undefined,
                    test_id: testId,
                  },
                });
                setShowFlag(false);
                setFlagNote('');
              }}
              disabled={
                submitFlag.isPending ||
                (flagCategory === 'other' && !flagNote.trim())
              }
            >
              {submitFlag.isPending ? 'Submitting…' : 'Submit'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Help modal */}
      <Dialog open={showHelp} onOpenChange={setShowHelp}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Keyboard shortcuts</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <ShortcutRow keys="A / B / C / D" desc="Select option & advance" />
            <ShortcutRow keys="Enter" desc="Save & next" />
            <ShortcutRow keys="← / →" desc="Prev / next question" />
            <ShortcutRow keys="1–9" desc="Jump to that question" />
            <ShortcutRow keys="M" desc="Mark for review" />
            <ShortcutRow keys="F" desc="Flag question" />
            <ShortcutRow keys="?" desc="This help" />
            <ShortcutRow keys="Ctrl+Enter" desc="Finish test" />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------- palette helpers ------------------------------

function paletteState(a: LocalAnswer | undefined): PaletteState {
  if (!a || !a.visited) return 'not_visited';
  if (a.marked && a.selected) return 'answered_review';
  if (a.marked) return 'review';
  if (a.selected) return 'answered';
  return 'not_answered';
}

type PaletteState =
  | 'not_visited'
  | 'not_answered'
  | 'answered'
  | 'review'
  | 'answered_review';

const PALETTE_STYLE: Record<PaletteState, string> = {
  not_visited: 'bg-[#a0a0a0] text-white',
  not_answered: 'bg-[#e74c3c] text-white',
  answered: 'bg-[#27ae60] text-white',
  review: 'bg-[#8b3a97] text-white',
  answered_review: 'bg-[#27ae60] text-white',
};

function PaletteCell({
  entry,
  onClick,
}: {
  entry: { idx: number; state: PaletteState; current: boolean };
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'relative flex h-8 w-full items-center justify-center rounded text-xs font-medium transition-transform hover:scale-105',
        PALETTE_STYLE[entry.state],
        entry.current && 'ring-2 ring-blue-500 ring-offset-1',
      )}
      aria-label={`Question ${entry.idx + 1}, ${entry.state.replace('_', ' ')}`}
      aria-current={entry.current ? 'true' : undefined}
    >
      {entry.idx + 1}
      {entry.state === 'answered_review' ? (
        <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-[#8b3a97] ring-1 ring-white" />
      ) : null}
    </button>
  );
}

function PaletteLegend() {
  const items: [PaletteState, string][] = [
    ['not_visited', 'Not visited'],
    ['not_answered', 'Not answered'],
    ['answered', 'Answered'],
    ['review', 'Marked'],
    ['answered_review', 'Answered + marked'],
  ];
  return (
    <ul className="mt-3 space-y-1 text-[11px]">
      {items.map(([state, label]) => (
        <li key={state} className="flex items-center gap-2">
          <span
            className={cn('h-3 w-3 rounded-sm', PALETTE_STYLE[state])}
            aria-hidden
          />
          <span>{label}</span>
        </li>
      ))}
    </ul>
  );
}

function ShortcutRow({ keys, desc }: { keys: string; desc: string }) {
  return (
    <>
      <div className="rounded bg-muted px-2 py-1 font-mono text-xs">{keys}</div>
      <div className="py-1">{desc}</div>
    </>
  );
}

function formatSec(s: number): string {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

function blank(): LocalAnswer {
  return { selected: null, marked: false, timeSpent: 0, visited: false };
}

function countAnswered(
  answers: Record<number, LocalAnswer>,
  qids: number[],
): number {
  return qids.filter((qid) => answers[qid]?.selected).length;
}
