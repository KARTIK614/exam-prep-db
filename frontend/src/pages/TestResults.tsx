import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Check, Loader2, Printer, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { DeepDiveButton } from '@/components/DeepDiveButton';
import { ConfidenceBadge, QuestionBody } from '@/components/QuestionView';
import { useTestResults, useUpdateNote } from '@/lib/api/tests';
import type { ResultsQuestionRow } from '@/lib/api/types';
import { TYPE_LABEL, formatAnswer } from '@/lib/utils/grading';
import { cn } from '@/lib/utils/cn';

type Filter = 'all' | 'wrong' | 'guessed' | 'skipped';

/**
 * TestResults — R4 §3.4 `GET /tests/{id}/results`. Renders:
 *   1. Overall score card
 *   2. Negative-marking breakdown (only if neg_ratio > 0)
 *   3. Print button (window.print())
 *   4. Per-topic breakdown table
 *   5. Per-question review list with correct/wrong markers, explanations,
 *      and time_spent.
 */
export default function TestResults() {
  const { id } = useParams<{ id: string }>();
  const testId = Number(id);
  const navigate = useNavigate();
  const results = useTestResults(testId);
  const updateNote = useUpdateNote(testId);
  const [filter, setFilter] = useState<Filter>('all');

  const qs = results.data?.questions ?? [];
  const stats = useMemo(() => {
    let lost = 0;
    let earned = 0;
    let luckyGuesses = 0;
    for (const q of qs) {
      const m = q.marks_awarded ?? 0;
      if (m < 0) lost += -m;
      else earned += m;
      if (q.is_correct && q.confidence === 'guess') luckyGuesses += 1;
    }
    return { lost, earned, luckyGuesses };
  }, [qs]);
  const shown = qs.filter((q) => matches(q, filter));

  if (results.isLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" /> Loading results…
      </div>
    );
  }
  if (results.isError || !results.data) {
    return (
      <div className="mx-auto max-w-md space-y-2 p-6 text-center">
        <p className="text-lg font-medium">Couldn't load these results.</p>
        <Button onClick={() => navigate('/dashboard')}>Back to dashboard</Button>
      </div>
    );
  }

  const r = results.data;
  const isPaper = r.questions.some((q) => q.q_number !== null);
  const hasNeg = r.negative_ratio > 0 || stats.lost > 0;
  const maxMarks = r.max_marks || r.correct + r.wrong + r.unanswered;

  return (
    <div className="mx-auto max-w-5xl space-y-4 pb-16">
      {/* Header + print */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Results · Test #{testId}</h1>
          <p className="text-sm text-muted-foreground">
            {r.correct + r.wrong + r.unanswered} questions ·{' '}
            {hasNeg ? 'exam' : 'practice'} mode
          </p>
        </div>
        <div className="flex gap-2 print:hidden">
          <Button variant="secondary" onClick={() => window.print()}>
            <Printer className="mr-1 h-4 w-4" /> Print
          </Button>
          <Button asChild variant="ghost">
            <Link to="/dashboard">Dashboard</Link>
          </Button>
        </div>
      </div>

      {/* Score card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Overall</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <ScoreCell
              label="Marks"
              value={`${r.raw_marks.toFixed(2)} / ${maxMarks}`}
              hint={hasNeg ? 'after negative marking' : ''}
            />
            <ScoreCell label="Score" value={`${Math.round(r.score_pct)}%`} />
            <ScoreCell label="Correct" value={String(r.correct)} accent="success" />
            <ScoreCell
              label="Wrong · skipped"
              value={`${r.wrong} · ${r.unanswered}`}
              accent="danger"
            />
          </div>
        </CardContent>
      </Card>

      {/* Neg-marking breakdown */}
      {hasNeg ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Negative marking</CardTitle>
            <CardDescription>
              {isPaper
              ? 'GATE rule: −1/3 of the marks for a wrong single-answer question; none for multiple-correct or numerical.'
              : `Ratio ${r.negative_ratio.toFixed(3)} · deducted for wrong answers.`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-md bg-muted p-3 font-mono text-sm">
              marks earned − marks lost to wrong answers ={' '}
              <b>{stats.earned.toFixed(2)}</b> − <b>{stats.lost.toFixed(2)}</b> ={' '}
              <b>{r.raw_marks.toFixed(2)}</b>
            </div>
            {stats.luckyGuesses > 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">
                {stats.luckyGuesses} correct answer{stats.luckyGuesses === 1 ? ' was' : 's were'} marked
                as a guess. Treat them as gaps, not wins.
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {/* Per-topic breakdown */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">By topic</CardTitle>
        </CardHeader>
        <CardContent>
          {r.breakdown_by_topic.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No topic breakdown available.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-2 py-2">Topic</th>
                    <th className="px-2 py-2 text-right">Correct</th>
                    <th className="px-2 py-2 text-right">Total</th>
                    <th className="px-2 py-2 text-right">Accuracy</th>
                  </tr>
                </thead>
                <tbody>
                  {r.breakdown_by_topic.map((row, i) => (
                    <tr key={i} className="border-b border-border last:border-0">
                      <td className="px-2 py-2">
                        {row.topic_name ?? '(no topic)'}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {row.correct}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {row.total}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {Math.round(row.accuracy_pct)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Per-question review */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Question review</CardTitle>
          <CardDescription>
            Your answer, the key, the marks and your note for each question. Add a line
            on why you picked each wrong or guessed answer while it's fresh.
          </CardDescription>
          <div className="flex flex-wrap gap-2 pt-2 print:hidden">
            {(
              [
                ['all', `All ${qs.length}`],
                ['wrong', `Wrong ${qs.filter((q) => matches(q, 'wrong')).length}`],
                ['guessed', `Guessed ${qs.filter((q) => matches(q, 'guessed')).length}`],
                ['skipped', `Skipped ${qs.filter((q) => matches(q, 'skipped')).length}`],
              ] as [Filter, string][]
            ).map(([f, label]) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={cn(
                  'rounded-full border px-3 py-1 text-xs',
                  filter === f ? 'border-primary bg-primary/10' : 'border-border text-muted-foreground',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {shown.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing in this filter.</p>
          ) : (
            shown.map((q) => {
              const i = qs.indexOf(q);
              const correct = q.is_correct;
              const attempted = q.selected_option !== null;
              return (
                <div
                  key={q.question_id}
                  className={cn(
                    'rounded-md border p-3',
                    correct
                      ? 'border-success/40 bg-success/5'
                      : attempted
                        ? 'border-destructive/40 bg-destructive/5'
                        : 'border-border',
                  )}
                >
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <div className="text-sm font-medium">
                      Q{q.q_number ?? i + 1}
                      {q.image_url ? (
                        <span className="ml-2 text-xs font-normal text-muted-foreground">
                          {q.paper_section} · {q.marks} mark{q.marks === 1 ? '' : 's'} ·{' '}
                          {TYPE_LABEL[q.qtype]}
                        </span>
                      ) : (
                        <>. {q.question_text ?? '(question missing)'}</>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <ConfidenceBadge value={q.confidence} />
                      {correct ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-success/20 px-2 py-0.5 text-xs text-success">
                          <Check className="h-3 w-3" /> Correct
                        </span>
                      ) : attempted ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-destructive/20 px-2 py-0.5 text-xs text-destructive">
                          <X className="h-3 w-3" /> Wrong
                        </span>
                      ) : (
                        <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                          Skipped
                        </span>
                      )}
                    </div>
                  </div>
                  {q.image_url ? (
                    <details open={!correct} className="mb-2">
                      <summary className="cursor-pointer text-xs text-muted-foreground print:hidden">
                        Question
                      </summary>
                      <QuestionBody q={q} className="mt-2" />
                    </details>
                  ) : null}
                  <div className="text-xs text-muted-foreground">
                    Your answer: <b>{formatAnswer(q.qtype, q.selected_option)}</b> · Key:{' '}
                    <b>{formatAnswer(q.qtype, q.correct_option)}</b>
                    {q.marks_awarded !== null ? (
                      <>
                        {' '}
                        · Marks:{' '}
                        <b className={cn(q.marks_awarded < 0 && 'text-destructive')}>
                          {q.marks_awarded > 0 ? '+' : ''}
                          {Number(q.marks_awarded.toFixed(2))}
                        </b>
                      </>
                    ) : null}{' '}
                    · {q.topic_name ?? 'general'} ·{' '}
                    {q.time_spent_sec !== null && q.time_spent_sec !== undefined
                      ? formatDuration(q.time_spent_sec)
                      : '—'}
                  </div>
                  {q.explanation ? (
                    <div className="mt-2 whitespace-pre-wrap rounded bg-bg-secondary p-2 text-xs">
                      {q.explanation}
                    </div>
                  ) : null}
                  <NoteEditor
                    initial={q.note ?? ''}
                    prompt={
                      correct && q.confidence !== 'guess'
                        ? 'Note (optional)'
                        : 'Why did you pick that? Your reasoning at the time, in one line.'
                    }
                    saving={updateNote.isPending}
                    onSave={(note) =>
                      updateNote.mutate({ questionId: q.question_id, note: note || null })
                    }
                  />
                  <DeepDiveButton questionId={q.question_id} />
                </div>
              );
            })
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function matches(q: ResultsQuestionRow, f: Filter): boolean {
  if (f === 'wrong') return q.selected_option !== null && !q.is_correct;
  if (f === 'guessed') return q.confidence === 'guess';
  if (f === 'skipped') return q.selected_option === null;
  return true;
}

function formatDuration(sec: number): string {
  const s = Math.round(sec);
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}

function NoteEditor({
  initial,
  prompt,
  saving,
  onSave,
}: {
  initial: string;
  prompt: string;
  saving: boolean;
  onSave: (note: string) => void;
}) {
  const [draft, setDraft] = useState(initial);
  const dirty = draft.trim() !== initial.trim();
  return (
    <div className="mt-2 print:hidden">
      <input
        aria-label={prompt}
        value={draft}
        maxLength={500}
        placeholder={prompt}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => dirty && onSave(draft.trim())}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            // Enter only commits this field; don't let the page-level
            // "Enter = save & next" shortcut see it once focus has left.
            e.preventDefault();
            e.stopPropagation();
            (e.target as HTMLInputElement).blur();
          }
        }}
        className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
      />
      {dirty ? (
        <div className="mt-0.5 text-[11px] text-muted-foreground">
          {saving ? 'Saving…' : 'Press Enter or click away to save.'}
        </div>
      ) : null}
    </div>
  );
}

function ScoreCell({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: 'success' | 'danger';
}) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          'text-3xl font-bold tabular-nums',
          accent === 'success' && 'text-success',
          accent === 'danger' && 'text-destructive',
        )}
      >
        {value}
      </div>
      {hint ? <div className="text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}
