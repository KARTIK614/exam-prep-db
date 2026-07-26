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
import { useTestResults } from '@/lib/api/tests';
import { cn } from '@/lib/utils/cn';

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
  const hasNeg = r.negative_ratio > 0;

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
            <ScoreCell label="Score" value={`${Math.round(r.score_pct)}%`} />
            <ScoreCell
              label="Raw marks"
              value={r.raw_marks.toFixed(2)}
              hint={hasNeg ? 'after negative marking' : ''}
            />
            <ScoreCell label="Correct" value={String(r.correct)} accent="success" />
            <ScoreCell label="Wrong" value={String(r.wrong)} accent="danger" />
          </div>
        </CardContent>
      </Card>

      {/* Neg-marking breakdown */}
      {hasNeg ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Negative marking</CardTitle>
            <CardDescription>
              {`Ratio ${r.negative_ratio.toFixed(3)} · deducted for wrong answers.`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-md bg-muted p-3 font-mono text-sm">
              raw_marks = correct − wrong × ratio ={' '}
              <b>{r.correct}</b> − <b>{r.wrong}</b> ×{' '}
              <b>{r.negative_ratio.toFixed(3)}</b> ={' '}
              <b>{r.raw_marks.toFixed(2)}</b>
            </div>
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
            Full breakdown per question with the correct answer and
            explanation.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {r.questions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No question-level data.
            </p>
          ) : (
            r.questions.map((q, i) => {
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
                  <div className="mb-1 flex items-start justify-between gap-2">
                    <div className="text-sm font-medium">
                      Q{i + 1}. {q.question_text ?? '(question missing)'}
                    </div>
                    <div className="shrink-0">
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
                  <div className="text-xs text-muted-foreground">
                    Your answer:{' '}
                    <b>{q.selected_option ?? '—'}</b> · Correct:{' '}
                    <b>{q.correct_option ?? '—'}</b> ·{' '}
                    {q.topic_name ?? 'general'} ·{' '}
                    {q.time_spent_sec !== null && q.time_spent_sec !== undefined
                      ? `${Math.round(q.time_spent_sec)}s`
                      : '—'}
                  </div>
                  {q.explanation ? (
                    <div className="mt-2 whitespace-pre-wrap rounded bg-bg-secondary p-2 text-xs">
                      {q.explanation}
                    </div>
                  ) : null}
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
