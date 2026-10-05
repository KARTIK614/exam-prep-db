import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Coffee, Flag, HelpCircle, Loader2, Pause, Play } from 'lucide-react';

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
  AnswerInput,
  ConfidencePicker,
  QuestionBody,
} from '@/components/QuestionView';
import {
  useFinishTest,
  useMarkForReview,
  useSubmitAnswer,
  useTest,
} from '@/lib/api/tests';
import { useSubmitFlag } from '@/lib/api/flags';
import { shortcutsEnabled } from '@/lib/utils/keyboard';
import { cn } from '@/lib/utils/cn';
import type { Confidence, FlagCategory } from '@/lib/api/types';
import { TYPE_LABEL, toggleLetter } from '@/lib/utils/grading';

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
 *   A/B/C/D  → MCQ: select, save, advance · MSQ: toggle that option
 *   S/U/G    → confidence: sure / unsure / guess
 *   P        → pause / resume (the question is hidden while paused)
 *   Enter    → save + next (finish confirm on last)
 *   ← →      → prev / next (also 1..9 for jump to palette cell)
 *   M        → toggle mark for review
 *   F        → open flag modal
 *   ?        → open help modal
 *   Ctrl+Enter → finish (with confirm)
 *
 * Pomodoro: active time (paused time excluded) runs in 50-minute blocks.
 * At the end of a block the test pauses itself and shows a 10-minute
 * break clock; resume whenever. Leaving the tab also pauses.
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

/** Stored answer encoding: MCQ "B", MSQ "A;C", NAT "2.5". */
type Selection = string | null;
interface LocalAnswer {
  selected: Selection;
  marked: boolean;
  timeSpent: number;
  visited: boolean;
  confidence: Confidence | null;
  note: string;
}

const BLOCK_SEC = 50 * 60;
const BREAK_SEC = 10 * 60;

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
  const [paused, setPaused] = useState(false);
  const [onBreak, setOnBreak] = useState(false);
  const [breakLeft, setBreakLeft] = useState(BREAK_SEC);
  const [showNote, setShowNote] = useState(false);
  const blocksDoneRef = useRef<number | null>(null);

  // Timer: per-question count-up.
  const [elapsed, setElapsed] = useState(0);
  const questionStartRef = useRef<number>(Date.now());

  // Hydrate local mirror from server on load.
  useEffect(() => {
    if (!test.data) return;
    const seed: Record<number, LocalAnswer> = {};
    for (const q of test.data.questions) {
      seed[q.id] = blank();
    }
    for (const r of test.data.responses) {
      seed[r.question_id] = {
        selected: r.selected_option ?? null,
        marked: r.marked_for_review,
        timeSpent: r.time_spent_sec ?? 0,
        visited: (r.visit_count ?? 0) > 0 || r.selected_option !== null,
        confidence: r.confidence ?? null,
        note: r.note ?? '',
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

  // Per-question timer ticker (stopped while paused).
  useEffect(() => {
    if (!currentQ || paused) return;
    const t = setInterval(() => {
      setElapsed(Math.floor((Date.now() - questionStartRef.current) / 1000));
    }, 1000);
    return () => clearInterval(t);
  }, [currentQ, currentIdx, paused]);

  // Reset timer when question changes.
  useEffect(() => {
    questionStartRef.current = Date.now();
    setElapsed(0);
    setShowNote(false);
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
          confidence: next.confidence,
          note: next.note.trim() || null,
        });
        return { ...prev, [qid]: next };
      });
    },
    [submitAnswer],
  );

  const snapshotElapsed = useCallback(() => {
    if (!currentQ) return 0;
    const seconds = paused ? 0 : Math.floor((Date.now() - questionStartRef.current) / 1000);
    return (answers[currentQ.id]?.timeSpent ?? 0) + seconds;
  }, [answers, currentQ, paused]);

  // Bank the running clock into the current question; the clock restarts
  // from "now" so the same seconds are never counted twice.
  const bankTime = useCallback(() => {
    const t = snapshotElapsed();
    questionStartRef.current = Date.now();
    setElapsed(0);
    return t;
  }, [snapshotElapsed]);

  const goto = useCallback(
    (nextIdx: number) => {
      if (!currentQ) return;
      if (nextIdx < 0 || nextIdx >= total) return;
      // Flush current time-spent before switching.
      persistAnswer(currentQ.id, { timeSpent: bankTime() });
      setCurrentIdx(nextIdx);
    },
    [currentQ, total, persistAnswer, bankTime],
  );

  const setSelection = useCallback(
    (value: Selection) => {
      if (!currentQ || paused) return;
      persistAnswer(currentQ.id, { selected: value, timeSpent: bankTime() });
    },
    [currentQ, paused, persistAnswer, bankTime],
  );

  const setConfidence = useCallback(
    (c: Confidence | null) => {
      if (!currentQ || paused) return;
      persistAnswer(currentQ.id, { confidence: c, timeSpent: bankTime() });
    },
    [currentQ, paused, persistAnswer, bankTime],
  );

  const saveNote = useCallback(
    (note: string) => {
      if (!currentQ) return;
      persistAnswer(currentQ.id, { note, timeSpent: bankTime() });
    },
    [currentQ, persistAnswer, bankTime],
  );

  const clearSelection = useCallback(() => {
    if (!currentQ) return;
    persistAnswer(currentQ.id, { selected: null, timeSpent: bankTime() });
  }, [currentQ, persistAnswer, bankTime]);

  const toggleMark = useCallback(() => {
    if (!currentQ) return;
    const now = !answers[currentQ.id]?.marked;
    persistAnswer(currentQ.id, { marked: now, timeSpent: bankTime() });
    markForReview.mutate({ question_id: currentQ.id, marked: now });
  }, [answers, currentQ, markForReview, persistAnswer, bankTime]);

  const saveAndNext = useCallback(() => {
    if (!currentQ) return;
    persistAnswer(currentQ.id, { timeSpent: bankTime() });
    if (currentIdx === total - 1) {
      setShowFinish(true);
    } else {
      setCurrentIdx((i) => Math.min(i + 1, total - 1));
    }
  }, [currentIdx, currentQ, persistAnswer, bankTime, total]);

  // ---------- pause + pomodoro -----------------------------

  const pause = useCallback(
    (asBreak = false) => {
      if (paused || !currentQ) return;
      persistAnswer(currentQ.id, { timeSpent: snapshotElapsed() });
      setPaused(true);
      setElapsed(0);
      if (asBreak) {
        setOnBreak(true);
        setBreakLeft(BREAK_SEC);
      }
    },
    [currentQ, paused, persistAnswer, snapshotElapsed],
  );

  const resume = useCallback(() => {
    questionStartRef.current = Date.now();
    setElapsed(0);
    setPaused(false);
    setOnBreak(false);
  }, []);

  // Active seconds across the whole test (paused time is never counted).
  const activeSec = useMemo(() => {
    let sum = 0;
    for (const q of questions) sum += answers[q.id]?.timeSpent ?? 0;
    return sum + (paused ? 0 : elapsed);
  }, [answers, elapsed, paused, questions]);
  const blockIdx = Math.floor(activeSec / BLOCK_SEC);
  const blockSec = activeSec - blockIdx * BLOCK_SEC;

  // Auto-break at each 50-minute boundary (not on load / resume-after-refresh).
  useEffect(() => {
    if (!test.data) return;
    if (blocksDoneRef.current === null) {
      blocksDoneRef.current = blockIdx;
      return;
    }
    if (blockIdx > blocksDoneRef.current) {
      blocksDoneRef.current = blockIdx;
      pause(true);
    }
  }, [blockIdx, pause, test.data]);

  // Break clock.
  useEffect(() => {
    if (!onBreak) return;
    const t = setInterval(() => setBreakLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [onBreak]);

  // Leaving the tab pauses the clock.
  useEffect(() => {
    const onVis = () => {
      if (document.hidden) pause(false);
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [pause]);

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

  const currentSelection = currentQ ? (answers[currentQ.id]?.selected ?? null) : null;

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

      if (key.toLowerCase() === 'p') {
        e.preventDefault();
        if (paused) resume();
        else pause(false);
        return;
      }
      if (paused) return;

      const qtype = currentQ?.qtype ?? 'MCQ';
      switch (key.toLowerCase()) {
        case 'a':
        case 'b':
        case 'c':
        case 'd': {
          if (qtype === 'NAT') break;
          e.preventDefault();
          const letter = key.toUpperCase();
          if (qtype === 'MSQ') {
            setSelection(toggleLetter(currentSelection, letter));
          } else {
            setSelection(letter);
            setTimeout(saveAndNext, 100);
          }
          break;
        }
        case 's':
          e.preventDefault();
          setConfidence('sure');
          break;
        case 'u':
          e.preventDefault();
          setConfidence('unsure');
          break;
        case 'g':
          e.preventDefault();
          setConfidence('guess');
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
  }, [
    currentIdx,
    currentQ,
    currentSelection,
    goto,
    pause,
    paused,
    resume,
    saveAndNext,
    setConfidence,
    setSelection,
    toggleMark,
  ]);

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

  // GATE pace targets: ~2 min per 1-mark, ~4 min per 2-mark question.
  const isPaper = Boolean(test.data.paper_code);
  const targetSec = isPaper ? (currentQ.marks >= 2 ? 240 : 120) : 60;
  const qElapsed = (answers[currentQ.id]?.timeSpent ?? 0) + (paused ? 0 : elapsed);
  const timerColor =
    qElapsed >= targetSec * 1.5
      ? 'text-destructive'
      : qElapsed >= targetSec
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
            {isPaper ? (
              <span className="ml-2 hidden sm:inline">
                · {currentQ.paper_section ?? ''} · {currentQ.marks} mark
                {currentQ.marks === 1 ? '' : 's'} · {TYPE_LABEL[currentQ.qtype]}
                {currentQ.qtype === 'MCQ' ? ` · −${(currentQ.marks / 3).toFixed(2)} if wrong` : ' · no negative'}
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-3">
            <div
              className="hidden font-mono text-xs tabular-nums text-muted-foreground sm:block"
              title="Active time in this 50-minute block (paused time not counted)"
            >
              Block {blockIdx + 1} · {formatSec(blockSec)} / 50:00
            </div>
            <div
              className={cn('font-mono text-sm tabular-nums', timerColor)}
              title={`Time on this question · target ${formatSec(targetSec)}`}
            >
              {formatSec(qElapsed)}
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => (paused ? resume() : pause(false))}
              aria-label={paused ? 'Resume (P)' : 'Pause (P)'}
              title={paused ? 'Resume (P)' : 'Pause (P)'}
            >
              {paused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
            </Button>
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
        <div className="relative flex-1 rounded-lg border border-border bg-bg-secondary p-4 sm:p-6">
          {isPaper && currentQ.qtype !== 'MCQ' ? (
            <div className="mb-2 sm:hidden text-xs text-muted-foreground">
              {currentQ.marks} mark{currentQ.marks === 1 ? '' : 's'} · {TYPE_LABEL[currentQ.qtype]}
            </div>
          ) : null}
          {paused ? (
            <PausePanel onBreak={onBreak} breakLeft={breakLeft} blockIdx={blockIdx} onResume={resume} />
          ) : (
            <>
              <QuestionBody q={currentQ} />
              <div className="mt-4">
                <AnswerInput
                  key={currentQ.id}
                  qtype={currentQ.qtype}
                  q={currentQ}
                  value={current.selected}
                  onChange={setSelection}
                />
              </div>
              <div className="mt-4 space-y-2 border-t border-border pt-3">
                <ConfidencePicker value={current.confidence} onChange={setConfidence} />
                {showNote || current.note ? (
                  <NoteField key={currentQ.id} initial={current.note} onSave={saveNote} />
                ) : (
                  <button
                    type="button"
                    className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                    onClick={() => setShowNote(true)}
                  >
                    + Why did you pick this? (optional, one line)
                  </button>
                )}
              </div>
            </>
          )}
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
            <ShortcutRow keys="A / B / C / D" desc="Select (MCQ: & advance · MSQ: toggle)" />
            <ShortcutRow keys="S / U / G" desc="Sure / Unsure / Guess" />
            <ShortcutRow keys="P" desc="Pause / resume" />
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
  return {
    selected: null,
    marked: false,
    timeSpent: 0,
    visited: false,
    confidence: null,
    note: '',
  };
}

function PausePanel({
  onBreak,
  breakLeft,
  blockIdx,
  onResume,
}: {
  onBreak: boolean;
  breakLeft: number;
  blockIdx: number;
  onResume: () => void;
}) {
  return (
    <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 text-center">
      {onBreak ? (
        <>
          <Coffee className="h-8 w-8 text-muted-foreground" />
          <div className="text-lg font-medium">Block {blockIdx} done. Take your 10-minute break.</div>
          <div
            className={cn(
              'font-mono text-4xl tabular-nums',
              breakLeft === 0 ? 'text-warning' : 'text-text-primary',
            )}
          >
            {formatSec(breakLeft)}
          </div>
          <p className="max-w-sm text-sm text-muted-foreground">
            Water, walk, no screens. The question stays hidden and the clock is stopped.
          </p>
        </>
      ) : (
        <>
          <Pause className="h-8 w-8 text-muted-foreground" />
          <div className="text-lg font-medium">Paused</div>
          <p className="max-w-sm text-sm text-muted-foreground">
            The clock is stopped and the question is hidden.
          </p>
        </>
      )}
      <Button onClick={onResume}>
        <Play className="mr-1 h-4 w-4" /> Resume (P)
      </Button>
    </div>
  );
}

/** One-line reasoning note. Saved on blur / Enter, not per keystroke. */
function NoteField({ initial, onSave }: { initial: string; onSave: (note: string) => void }) {
  const [draft, setDraft] = useState(initial);
  const commit = () => {
    if (draft.trim() !== initial.trim()) onSave(draft.trim());
  };
  return (
    <div>
      <label htmlFor="answer-note" className="text-xs text-muted-foreground">
        Why did you pick this? One line is enough; voice dictation works.
      </label>
      <input
        id="answer-note"
        value={draft}
        maxLength={500}
        autoComplete="off"
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
        placeholder="e.g. used P(A|B)=P(B|A) without the base rate"
        className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
      />
    </div>
  );
}

function countAnswered(
  answers: Record<number, LocalAnswer>,
  qids: number[],
): number {
  return qids.filter((qid) => answers[qid]?.selected).length;
}
