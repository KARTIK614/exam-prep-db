import { Link } from 'react-router-dom';
import { ArrowRight, Sparkles, Target, TrendingUp } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  useConsistency,
  useMastery,
  useNextTopics,
  usePaperPerformance,
} from '@/lib/api/analytics';
import { useErrorLog } from '@/lib/api/errors';
import { useReviewQueue } from '@/lib/api/review';
import { useTestList } from '@/lib/api/tests';
import { useAuth } from '@/hooks/useAuth';
import { cn } from '@/lib/utils/cn';
import type { MasteryTile } from '@/lib/api/types';

/**
 * Dashboard — Phase 9 landing after login.
 *
 * Sections (top → bottom):
 *   1. Hero: greeting + consistency score + next-weak-topic + SR-due pill
 *   2. Mastery grid (18 tiles with weightage badges + tier borders)
 *   3. Priority review card + recent errors card (side by side on md+)
 *   4. Paper performance card
 *
 * Every widget renders an empty state when the backend endpoint 404s or
 * returns nothing — R4 §3.9 analytics endpoints are not all shipped yet.
 */
export default function Dashboard() {
  const { user } = useAuth();
  const consistency = useConsistency({ days: 28, denom: 20 });
  const nextTopics = useNextTopics(3);
  const review = useReviewQueue({ limit: 100 });
  const mastery = useMastery();
  const errors = useErrorLog({ limit: 5 });
  const paperPerf = usePaperPerformance();
  const testList = useTestList({ limit: 5 });

  const consistencyScore = consistency.data?.score ?? null;
  const nextWeakTopic = nextTopics.data?.next_topics?.[0] ?? null;
  const dueToday = review.data?.summary?.due_today ?? 0;
  const tiles: MasteryTile[] = mastery.data?.tiles ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-6 pb-16">
      {/* ---------------- Hero ---------------- */}
      <div>
        <h1 className="text-2xl font-semibold sm:text-3xl">
          Welcome back{user?.username ? `, ${user.username}` : ''}.
        </h1>
        <p className="text-sm text-muted-foreground">
          Here's where your prep stands today.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Consistency */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <TrendingUp className="h-4 w-4" /> Consistency (28d)
            </div>
          </CardHeader>
          <CardContent>
            {consistency.isLoading ? (
              <div className="h-10 w-24 animate-pulse rounded bg-muted" />
            ) : consistencyScore === null ? (
              <p className="text-sm text-muted-foreground">No data yet.</p>
            ) : (
              <div className="flex items-baseline gap-2">
                <div className="text-4xl font-bold tabular-nums">
                  {consistencyScore}
                </div>
                <div className="text-sm text-muted-foreground">
                  · {consistency.data?.active_days ?? 0} active days
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Next weak topic */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Target className="h-4 w-4" /> Next weak topic
            </div>
          </CardHeader>
          <CardContent>
            {nextTopics.isLoading ? (
              <div className="h-10 w-40 animate-pulse rounded bg-muted" />
            ) : !nextWeakTopic ? (
              <p className="text-sm text-muted-foreground">
                All topics are on track. Consider a mixed-topic test.
              </p>
            ) : (
              <div>
                <div className="text-lg font-medium">{nextWeakTopic.name}</div>
                <div className="text-xs text-muted-foreground">
                  {nextWeakTopic.reason ?? 'Suggested next focus'}
                </div>
                <Button
                  asChild
                  size="sm"
                  className="mt-3"
                  variant="secondary"
                >
                  <Link to={`/test/new?topic_id=${nextWeakTopic.topic_id}`}>
                    Start focused test <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* SR due */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Sparkles className="h-4 w-4" /> Review queue
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-3">
              <div
                className={cn(
                  'rounded-full px-3 py-1 text-sm font-medium',
                  dueToday > 0
                    ? 'bg-warning/15 text-warning'
                    : 'bg-muted text-muted-foreground',
                )}
              >
                {dueToday} due today
              </div>
              <Button asChild size="sm" variant="ghost">
                <Link to="/review">Open</Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* CTA row */}
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild>
          <Link to="/test/new">Take a test</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link to="/analytics">Detailed analytics</Link>
        </Button>
      </div>

      {/* ---------------- Mastery grid ---------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Mastery grid</CardTitle>
          <CardDescription>
            One tile per topic — border colour marks the mastery tier.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {mastery.isLoading ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} className="h-20 animate-pulse rounded-md bg-muted" />
              ))}
            </div>
          ) : tiles.length === 0 ? (
            <EmptyState
              title="No mastery data yet"
              body="Take a test to start building topic-level mastery scores."
              ctaLabel="Take a test"
              ctaHref="/test/new"
            />
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {tiles.map((tile) => (
                <MasteryTileCard key={tile.topic_id} tile={tile} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ---------------- Priority review + recent errors ---------------- */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Priority review</CardTitle>
            <CardDescription>
              Cards you'll benefit from touching first.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {review.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-10 animate-pulse rounded bg-muted" />
                ))}
              </div>
            ) : review.data?.cards?.length ? (
              <ul className="space-y-2 text-sm">
                {review.data.cards.slice(0, 5).map((card) => (
                  <li
                    key={card.error_id}
                    className="rounded-md border border-border p-2"
                  >
                    <div className="line-clamp-1 font-medium">
                      {card.question_text ?? '(no text)'}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Box {card.sr_box} · {card.topic_name ?? 'general'}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                Nothing due right now — check back tomorrow.
              </p>
            )}
            <Button asChild size="sm" variant="ghost" className="mt-3">
              <Link to="/review">Open review</Link>
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Recent errors</CardTitle>
            <CardDescription>Your last few wrong answers.</CardDescription>
          </CardHeader>
          <CardContent>
            {errors.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-10 animate-pulse rounded bg-muted" />
                ))}
              </div>
            ) : errors.data?.errors?.length ? (
              <ul className="space-y-2 text-sm">
                {errors.data.errors.slice(0, 5).map((err) => (
                  <li
                    key={err.id}
                    className="rounded-md border border-border p-2"
                  >
                    <div className="line-clamp-1 font-medium">
                      {err.question_text ?? '(no text)'}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {err.topic_name ?? 'general'} ·{' '}
                      {err.error_type ?? 'unclassified'}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                No errors logged yet — nice.
              </p>
            )}
            <Button asChild size="sm" variant="ghost" className="mt-3">
              <Link to="/errors">Full error log</Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* ---------------- Paper performance ---------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Paper performance</CardTitle>
        </CardHeader>
        <CardContent>
          {paperPerf.isLoading ? (
            <div className="h-14 animate-pulse rounded bg-muted" />
          ) : paperPerf.data?.by_paper?.length ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {paperPerf.data.by_paper.map((row) => (
                <div
                  key={row.paper}
                  className="rounded-md border border-border p-3"
                >
                  <div className="text-xs text-muted-foreground">
                    Paper {row.paper}
                  </div>
                  <div className="text-2xl font-semibold tabular-nums">
                    {Math.round(row.avg_score)}%
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {row.tests} tests
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No completed papers yet.
            </p>
          )}
        </CardContent>
      </Card>

      {/* ---------------- Recent tests list ---------------- */}
      {testList.data?.items?.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Recent tests</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border text-sm">
              {testList.data.items.slice(0, 5).map((t) => (
                <li key={t.id} className="flex items-center justify-between py-2">
                  <div>
                    <div className="font-medium">
                      Test #{t.id} · {t.test_mode ?? 'practice'}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t.completed_at ?? t.started_at ?? '—'}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="tabular-nums">
                      {t.score !== null && t.score !== undefined
                        ? `${Math.round(t.score)}%`
                        : '—'}
                    </div>
                    {t.status === 'in_progress' ? (
                      <Button asChild size="sm" variant="secondary">
                        <Link to={`/test/${t.id}`}>Resume</Link>
                      </Button>
                    ) : (
                      <Button asChild size="sm" variant="ghost">
                        <Link to={`/test/${t.id}/results`}>View</Link>
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

// -------------------- helpers --------------------

function MasteryTileCard({ tile }: { tile: MasteryTile }) {
  const border =
    tile.tier === 'weak'
      ? 'border-destructive/60'
      : tile.tier === 'on_track'
        ? 'border-warning/60'
        : tile.tier === 'mastered'
          ? 'border-success/60'
          : 'border-border';

  return (
    <Link
      to={`/test/new?topic_id=${tile.topic_id}`}
      className={cn(
        'group flex flex-col justify-between rounded-md border-2 bg-bg-secondary p-3 text-left transition-colors hover:bg-muted',
        border,
      )}
      aria-label={`${tile.name}, ${tile.tier}, ${Math.round(tile.current_score)}%`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="line-clamp-2 text-sm font-medium">{tile.name}</div>
        {tile.weightage ? (
          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            {tile.weightage}%
          </span>
        ) : null}
      </div>
      <div className="mt-2 flex items-baseline gap-1">
        <div className="text-lg font-semibold tabular-nums">
          {Math.round(tile.current_score)}
        </div>
        <div className="text-xs text-muted-foreground">/ 100</div>
      </div>
    </Link>
  );
}

function EmptyState({
  title,
  body,
  ctaLabel,
  ctaHref,
}: {
  title: string;
  body: string;
  ctaLabel?: string;
  ctaHref?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-border p-6 text-center">
      <div className="text-sm font-medium">{title}</div>
      <p className="mt-1 max-w-xs text-xs text-muted-foreground">{body}</p>
      {ctaLabel && ctaHref ? (
        <Button asChild size="sm" className="mt-3">
          <Link to={ctaHref}>{ctaLabel}</Link>
        </Button>
      ) : null}
    </div>
  );
}
