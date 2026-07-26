import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { useReviewAnswer, useReviewQueue } from '@/lib/api/review';
import { shortcutsEnabled } from '@/lib/utils/keyboard';
import { cn } from '@/lib/utils/cn';

/**
 * Review — Leitner SRS single-card queue (R4 §3.6).
 *
 * Flow per card:
 *   1. Show question + 4 options (no correctness indicator).
 *   2. On Reveal (or Space) → show correct answer, explanation, box +
 *      due-date estimate.
 *   3. User grades themselves: "Missed" (POST correct=false) or
 *      "Got it" (POST correct=true). J = missed, K = got it, N = skip
 *      to next.
 *
 * Card-by-card local index — we fetch a batch of ~100 cards on mount and
 * page through them. When we exhaust the batch we refetch.
 */
export default function Review() {
  const queue = useReviewQueue({ limit: 100 });
  const answer = useReviewAnswer();
  const [cursor, setCursor] = useState(0);
  const [revealed, setRevealed] = useState(false);

  const cards = queue.data?.cards ?? [];
  const card = cards[cursor];

  const dueToday = queue.data?.summary?.due_today ?? 0;

  const advance = useCallback(() => {
    setRevealed(false);
    setCursor((c) => c + 1);
  }, []);

  const grade = useCallback(
    async (correct: boolean) => {
      if (!card) return;
      try {
        await answer.mutateAsync({ cardId: card.error_id, correct });
      } catch {
        // Non-blocking: still advance.
      }
      advance();
    },
    [answer, advance, card],
  );

  // Reset when a new queue payload arrives (after answer invalidates it).
  useEffect(() => {
    setCursor(0);
    setRevealed(false);
  }, [queue.data?.cards]);

  // Keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!shortcutsEnabled()) return;
      switch (e.key.toLowerCase()) {
        case ' ':
          e.preventDefault();
          setRevealed(true);
          break;
        case 'j':
          if (revealed) {
            e.preventDefault();
            grade(false);
          }
          break;
        case 'k':
          if (revealed) {
            e.preventDefault();
            grade(true);
          }
          break;
        case 'n':
          e.preventDefault();
          advance();
          break;
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [advance, grade, revealed]);

  const optionLetters = useMemo(() => ['A', 'B', 'C', 'D'] as const, []);

  if (queue.isLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" /> Loading review queue…
      </div>
    );
  }

  if (!card) {
    return (
      <div className="mx-auto max-w-md space-y-2 p-6 text-center">
        <p className="text-lg font-medium">All caught up.</p>
        <p className="text-sm text-muted-foreground">
          Nothing left to review right now. Check back tomorrow.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4 pb-16">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Review</h1>
          <p className="text-sm text-muted-foreground">
            {dueToday} due today · card {cursor + 1} of {cards.length}
          </p>
        </div>
        <Button variant="ghost" onClick={advance}>
          Skip
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {card.topic_name ?? 'general'}
          </CardTitle>
          <CardDescription>Box {card.sr_box}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="whitespace-pre-wrap text-base leading-relaxed">
            {card.question_text ?? '(no text)'}
          </div>
          <div className="mt-4 space-y-2">
            {optionLetters.map((opt) => {
              const text = card[`option_${opt.toLowerCase()}` as
                | 'option_a'
                | 'option_b'
                | 'option_c'
                | 'option_d'];
              if (!text) return null;
              const isRight = revealed && card.correct_option === opt;
              return (
                <div
                  key={opt}
                  className={cn(
                    'flex items-start gap-3 rounded-md border p-3 text-sm',
                    isRight
                      ? 'border-success/60 bg-success/10'
                      : 'border-border bg-bg-primary',
                  )}
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border text-xs font-semibold">
                    {opt}
                  </span>
                  <span className="whitespace-pre-wrap">{text}</span>
                </div>
              );
            })}
          </div>

          {revealed ? (
            <div className="mt-4 space-y-3">
              {card.explanation ? (
                <div className="rounded-md bg-bg-secondary p-3 text-sm">
                  <div className="mb-1 text-xs font-medium text-muted-foreground">
                    Explanation
                  </div>
                  <div className="whitespace-pre-wrap">{card.explanation}</div>
                </div>
              ) : null}
              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <div className="rounded bg-muted p-2">
                  <div className="font-medium">If you missed</div>
                  <div>
                    → Box {card.if_no_box}, due in {card.if_no_days}d
                  </div>
                </div>
                <div className="rounded bg-muted p-2">
                  <div className="font-medium">If you got it</div>
                  <div>
                    → Box {card.if_ok_box}, due in {card.if_ok_days}d
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {revealed ? (
        <div className="grid grid-cols-2 gap-3">
          <Button
            size="lg"
            variant="destructive"
            onClick={() => grade(false)}
            disabled={answer.isPending}
          >
            Missed (J)
          </Button>
          <Button
            size="lg"
            onClick={() => grade(true)}
            disabled={answer.isPending}
          >
            Got it (K)
          </Button>
        </div>
      ) : (
        <Button
          size="lg"
          className="w-full"
          onClick={() => setRevealed(true)}
        >
          Reveal (Space)
        </Button>
      )}
    </div>
  );
}
