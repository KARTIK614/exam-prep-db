import { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { AnswerInput, QuestionBody } from '@/components/QuestionView';
import { useReviewAnswer, useReviewQueue } from '@/lib/api/review';
import { formatAnswer, isCorrect } from '@/lib/utils/grading';
import { shortcutsEnabled } from '@/lib/utils/keyboard';
import { cn } from '@/lib/utils/cn';

/**
 * Review — Leitner SRS single-card queue (R4 §3.6).
 *
 * Flow per card:
 *   1. Show the question; the student answers it again (MCQ / MSQ / NAT).
 *   2. Check (or Space) → the answer is graded against the key, and the
 *      key, explanation and box + due-date estimate appear.
 *   3. The student confirms: "Missed" (POST correct=false) or "Got it"
 *      (POST correct=true). The auto-grade is the highlighted default.
 *      J = missed, K = got it, N = skip to next.
 *
 * Card-by-card local index — we fetch a batch of ~100 cards on mount and
 * page through them. When we exhaust the batch we refetch.
 */
export default function Review() {
  const queue = useReviewQueue({ limit: 100 });
  const answer = useReviewAnswer();
  const [cursor, setCursor] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [attempt, setAttempt] = useState<string | null>(null);

  const cards = queue.data?.cards ?? [];
  const card = cards[cursor];

  const dueToday = queue.data?.summary?.due_today ?? 0;

  const advance = useCallback(() => {
    setRevealed(false);
    setAttempt(null);
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
    setAttempt(null);
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

  const autoCorrect = isCorrect(card.qtype, card.correct_option, attempt);

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
          <QuestionBody q={card} />
          <div className="mt-4">
            <AnswerInput
              key={card.error_id}
              qtype={card.qtype}
              q={card}
              value={attempt}
              onChange={setAttempt}
              disabled={revealed}
              reveal={revealed ? { key: card.correct_option ?? null } : undefined}
            />
          </div>
          {revealed ? (
            <div
              className={cn(
                'mt-3 rounded-md p-2 text-sm font-medium',
                autoCorrect ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive',
              )}
            >
              {attempt === null
                ? `Not answered. Key: ${formatAnswer(card.qtype, card.correct_option)}`
                : autoCorrect
                  ? 'Correct.'
                  : `Not quite. Key: ${formatAnswer(card.qtype, card.correct_option)}`}
            </div>
          ) : null}

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
            variant={autoCorrect ? 'secondary' : 'destructive'}
            onClick={() => grade(false)}
            disabled={answer.isPending}
          >
            Missed (J)
          </Button>
          <Button
            size="lg"
            variant={autoCorrect ? 'default' : 'secondary'}
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
          {attempt === null ? 'Reveal (Space)' : 'Check (Space)'}
        </Button>
      )}
    </div>
  );
}
