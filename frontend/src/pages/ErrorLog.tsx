import { Link } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { useErrorLog } from '@/lib/api/errors';
import { useReviewQueue } from '@/lib/api/review';

/**
 * ErrorLog — R4 §3.7 `GET /errors`. Displays wrong-answer history along
 * with an SRS "due today" card that links into `/review`.
 */
export default function ErrorLog() {
  const errors = useErrorLog({ limit: 50 });
  const review = useReviewQueue({ limit: 100 });
  const due = review.data?.summary?.due_today ?? 0;

  return (
    <div className="mx-auto max-w-5xl space-y-4 pb-16">
      <div>
        <h1 className="text-2xl font-semibold">Error log</h1>
        <p className="text-sm text-muted-foreground">
          Everything you've gotten wrong, sorted by most recent.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Review queue</CardTitle>
          <CardDescription>
            Spaced-repetition cards derived from your errors.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <div>
            <div className="text-3xl font-bold tabular-nums">{due}</div>
            <div className="text-xs text-muted-foreground">due today</div>
          </div>
          <Button asChild>
            <Link to="/review">Start review</Link>
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Errors</CardTitle>
        </CardHeader>
        <CardContent>
          {errors.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          ) : errors.isError ? (
            <p className="text-sm text-destructive">Failed to load.</p>
          ) : errors.data?.errors?.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No errors logged. Nice work — take a test to keep the streak.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {errors.data?.errors.map((err) => (
                <li key={err.id} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="line-clamp-2 text-sm font-medium">
                        {err.question_text ?? '(question missing)'}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {err.topic_name ?? 'general'} ·{' '}
                        {err.error_type ?? 'unclassified'} ·{' '}
                        {err.created_at ?? ''}
                      </div>
                    </div>
                    {err.sr_box !== null ? (
                      <span className="shrink-0 rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                        Box {err.sr_box}
                      </span>
                    ) : null}
                  </div>
                  {err.explanation ? (
                    <div className="mt-2 line-clamp-2 rounded bg-bg-secondary p-2 text-xs">
                      {err.explanation}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
