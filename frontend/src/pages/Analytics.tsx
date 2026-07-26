import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  useHeatmap,
  useMastery,
  usePacing,
} from '@/lib/api/analytics';
import { useSettings, useUpdateSettings } from '@/lib/api/settings';
import { cn } from '@/lib/utils/cn';
import type {
  HeatmapResponse,
  MasteryTile,
  PacingResponse,
} from '@/lib/api/types';

/**
 * Analytics — a suite of read-only visualisations backed by
 * `/api/v1/analytics/*`.
 *
 * Charts are hand-rolled SVG (per Phase 9 spec: no chart lib) — this keeps
 * bundle size flat and gives us direct control over CSS-variable-driven
 * theming.
 */
export default function Analytics() {
  const mastery = useMastery();
  const pacing = usePacing();
  const [heatmapDim, setHeatmapDim] = useState<'difficulty' | 'recency'>(
    'difficulty',
  );
  const heatmap = useHeatmap(heatmapDim);
  const settings = useSettings();
  const updateSettings = useUpdateSettings();
  const [targetSec, setTargetSec] = useState<number>(60);

  // Reflect fetched settings.
  useEffect(() => {
    if (settings.data?.target_seconds_per_q) {
      setTargetSec(settings.data.target_seconds_per_q);
    }
  }, [settings.data]);

  const tiles: MasteryTile[] = mastery.data?.tiles ?? [];
  const grouped = tiles.reduce<Record<string, MasteryTile[]>>((acc, t) => {
    const key = t.paper ?? 'other';
    (acc[key] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div className="mx-auto max-w-6xl space-y-6 pb-16">
      <div>
        <h1 className="text-2xl font-semibold">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Everything the platform knows about your prep.
        </p>
      </div>

      {/* Mastery */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Mastery by paper</CardTitle>
        </CardHeader>
        <CardContent>
          {mastery.isLoading ? (
            <div className="h-24 animate-pulse rounded bg-muted" />
          ) : tiles.length === 0 ? (
            <p className="text-sm text-muted-foreground">No mastery data.</p>
          ) : (
            <div className="space-y-4">
              {Object.entries(grouped).map(([paper, list]) => (
                <div key={paper}>
                  <div className="mb-2 text-xs font-medium text-muted-foreground">
                    Paper {paper}
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-6">
                    {list.map((t) => (
                      <div
                        key={t.topic_id}
                        className={cn(
                          'rounded-md border-2 bg-bg-secondary p-2',
                          t.tier === 'weak' && 'border-destructive/60',
                          t.tier === 'on_track' && 'border-warning/60',
                          t.tier === 'mastered' && 'border-success/60',
                          t.tier === 'untested' && 'border-border',
                        )}
                      >
                        <div className="line-clamp-1 text-xs font-medium">
                          {t.name}
                        </div>
                        <div className="mt-1 flex items-baseline gap-1">
                          <span className="text-lg font-semibold tabular-nums">
                            {Math.round(t.current_score)}
                          </span>
                          {t.weightage ? (
                            <span className="text-[10px] text-muted-foreground">
                              · {t.weightage}%
                            </span>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Weakness heatmap */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-lg">Weakness heatmap</CardTitle>
            <CardDescription>
              Accuracy by topic × {heatmapDim}.
            </CardDescription>
          </div>
          <div className="flex gap-1">
            <Button
              size="sm"
              variant={heatmapDim === 'difficulty' ? 'default' : 'secondary'}
              onClick={() => setHeatmapDim('difficulty')}
            >
              Difficulty
            </Button>
            <Button
              size="sm"
              variant={heatmapDim === 'recency' ? 'default' : 'secondary'}
              onClick={() => setHeatmapDim('recency')}
            >
              Recency
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {heatmap.isLoading ? (
            <div className="h-24 animate-pulse rounded bg-muted" />
          ) : !heatmap.data?.topics?.length ? (
            <p className="text-sm text-muted-foreground">
              No heatmap data yet.
            </p>
          ) : (
            <Heatmap
              topics={heatmap.data.topics}
              buckets={extractBuckets(heatmap.data.topics)}
            />
          )}
        </CardContent>
      </Card>

      {/* Pacing */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Pacing</CardTitle>
          <CardDescription>
            Average seconds per question over your last N tests.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {pacing.isLoading ? (
            <div className="h-24 animate-pulse rounded bg-muted" />
          ) : !pacing.data ? (
            <p className="text-sm text-muted-foreground">No pacing data.</p>
          ) : (
            <PacingChart data={pacing.data} target={targetSec} />
          )}
        </CardContent>
      </Card>

      {/* Slow-and-wrong */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Slow & wrong (top 10)</CardTitle>
        </CardHeader>
        <CardContent>
          {pacing.data?.slow_wrong?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-2 py-2">Question</th>
                    <th className="px-2 py-2">Topic</th>
                    <th className="px-2 py-2">Difficulty</th>
                    <th className="px-2 py-2 text-right">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {pacing.data.slow_wrong.slice(0, 10).map((row) => (
                    <tr
                      key={row.question_id}
                      className="border-b border-border last:border-0"
                    >
                      <td className="max-w-md truncate px-2 py-2">
                        {row.question_text}
                      </td>
                      <td className="px-2 py-2">{row.topic ?? '—'}</td>
                      <td className="px-2 py-2">{row.difficulty ?? '—'}</td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {Math.round(row.time_spent_sec)}s
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Nothing slow-and-wrong yet.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Settings */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Preferences</CardTitle>
          <CardDescription>
            These drive per-question pacing targets and defaults across the
            app.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              await updateSettings.mutateAsync({
                target_seconds_per_q: targetSec,
              });
            }}
            className="flex items-end gap-3"
          >
            <div className="flex-1 max-w-xs">
              <Label htmlFor="target-sec">Target seconds per question</Label>
              <Input
                id="target-sec"
                type="number"
                min={10}
                max={600}
                value={targetSec}
                onChange={(e) => setTargetSec(Number(e.target.value))}
              />
            </div>
            <Button type="submit" disabled={updateSettings.isPending}>
              {updateSettings.isPending ? 'Saving…' : 'Save'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------- Heatmap (SVG-free, div-based) --------------------

function extractBuckets(topics: HeatmapResponse['topics']): string[] {
  const set = new Set<string>();
  for (const t of topics) {
    for (const k of Object.keys(t.cells)) set.add(k);
  }
  return Array.from(set).sort();
}

function Heatmap({
  topics,
  buckets,
}: {
  topics: HeatmapResponse['topics'];
  buckets: string[];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[500px] text-sm" role="table">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left text-xs text-muted-foreground">
              Topic
            </th>
            {buckets.map((b) => (
              <th key={b} className="px-2 py-1 text-xs text-muted-foreground">
                {b}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {topics.map((t) => (
            <tr key={t.topic_id}>
              <td className="px-2 py-1 text-sm">{t.name}</td>
              {buckets.map((b) => {
                const cell = t.cells[b];
                if (!cell) {
                  return (
                    <td key={b} className="px-1 py-1">
                      <div className="h-6 w-full rounded bg-muted" />
                    </td>
                  );
                }
                const acc = cell.accuracy;
                const color = accuracyColor(acc);
                return (
                  <td key={b} className="px-1 py-1">
                    <div
                      className="flex h-6 w-full items-center justify-center rounded text-[10px] font-medium text-white"
                      style={{ background: color }}
                      title={`${cell.correct}/${cell.attempted} = ${Math.round(acc)}%`}
                    >
                      {Math.round(acc)}%
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function accuracyColor(pct: number): string {
  // 0% red → 50% amber → 100% green.
  if (pct >= 80) return '#27ae60';
  if (pct >= 60) return '#f1c40f';
  if (pct >= 40) return '#e67e22';
  return '#e74c3c';
}

// ---------- Pacing chart (SVG line, hand-rolled) ------------

function PacingChart({
  data,
  target,
}: {
  data: PacingResponse;
  target: number;
}) {
  const trend = data.time_trend ?? [];
  if (trend.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No completed tests yet.</p>
    );
  }

  const w = 720;
  const h = 240;
  const pad = 32;
  const maxT = Math.max(target * 2, ...trend.map((p) => p.avg_time));
  const minT = 0;
  const stepX = (w - pad * 2) / Math.max(trend.length - 1, 1);
  const y = (v: number) =>
    h - pad - ((v - minT) / Math.max(maxT - minT, 1)) * (h - pad * 2);
  const x = (i: number) => pad + i * stepX;

  const linePath = trend
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.avg_time)}`)
    .join(' ');

  const targetY = y(target);

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full min-w-[500px]">
        {/* Y axis grid */}
        {[0, 0.25, 0.5, 0.75, 1].map((frac) => {
          const gy = pad + frac * (h - pad * 2);
          const val = maxT - frac * (maxT - minT);
          return (
            <g key={frac}>
              <line
                x1={pad}
                x2={w - pad}
                y1={gy}
                y2={gy}
                stroke="currentColor"
                strokeOpacity="0.1"
              />
              <text
                x={4}
                y={gy + 3}
                fontSize="10"
                fill="currentColor"
                opacity="0.5"
              >
                {Math.round(val)}s
              </text>
            </g>
          );
        })}

        {/* Target line */}
        <line
          x1={pad}
          x2={w - pad}
          y1={targetY}
          y2={targetY}
          stroke="hsl(var(--warning))"
          strokeDasharray="4 4"
          strokeWidth={1.5}
        />
        <text
          x={w - pad}
          y={targetY - 4}
          textAnchor="end"
          fontSize="10"
          fill="hsl(var(--warning))"
        >
          target {target}s
        </text>

        {/* Data line */}
        <path
          d={linePath}
          fill="none"
          stroke="hsl(var(--accent))"
          strokeWidth={2}
        />
        {trend.map((p, i) => (
          <circle
            key={i}
            cx={x(i)}
            cy={y(p.avg_time)}
            r={3}
            fill="hsl(var(--accent))"
          >
            <title>{`${p.date} · ${Math.round(p.avg_time)}s · ${
              p.score ?? '—'
            }%`}</title>
          </circle>
        ))}
      </svg>
    </div>
  );
}
