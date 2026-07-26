import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { adminApi, useAdminReviewQueue } from '@/lib/api/admin';

/**
 * AdminReview — mid-confidence question review, Anki-style.
 * Chips: medium | with_notes | synthetic | deferred | non_high.
 */
const FILTERS = ['medium', 'with_notes', 'synthetic', 'deferred', 'non_high'] as const;
type Filter = (typeof FILTERS)[number];

export default function AdminReview() {
  const [filter, setFilter] = useState<Filter>('medium');
  const queue = useAdminReviewQueue(filter);
  const [cursor, setCursor] = useState(0);
  const items = queue.data?.items ?? [];
  const q = items[cursor];

  const advance = () => {
    setCursor((c) => c + 1);
  };
  const doConfirm = async () => {
    if (!q) return;
    await adminApi.confirmReview(q.id);
    advance();
  };
  const doDefer = async () => {
    if (!q) return;
    await adminApi.deferReview(q.id);
    advance();
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4 pb-16">
      <h1 className="text-2xl font-semibold">Review queue</h1>
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <Button
            key={f}
            size="sm"
            variant={filter === f ? 'default' : 'secondary'}
            onClick={() => {
              setFilter(f);
              setCursor(0);
            }}
          >
            {f}{' '}
            <span className="ml-1 rounded bg-black/20 px-1 text-xs">
              {queue.data?.counts?.[f] ?? 0}
            </span>
          </Button>
        ))}
      </div>

      <Card>
        <CardContent className="p-4">
          {queue.isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : !q ? (
            <p className="text-sm text-muted-foreground">
              Nothing left in this bucket.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="text-xs text-muted-foreground">
                Q#{q.id} · card {cursor + 1} / {items.length}
              </div>
              <div className="whitespace-pre-wrap text-base">
                {q.question_text}
              </div>
              <ol className="space-y-1 text-sm">
                {(['a', 'b', 'c', 'd'] as const).map((k) => {
                  const t = q[`option_${k}` as keyof typeof q] as string | null;
                  if (!t) return null;
                  return (
                    <li key={k}>
                      <b>{k.toUpperCase()}.</b> {t}
                    </li>
                  );
                })}
              </ol>
              <div className="text-xs text-muted-foreground">
                Correct: {q.correct_option} · Explanation:{' '}
                {q.explanation ?? '—'}
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={doDefer}>
                  Defer
                </Button>
                <Button onClick={doConfirm}>Confirm high-confidence</Button>
                <Button variant="ghost" onClick={advance}>
                  Skip
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
