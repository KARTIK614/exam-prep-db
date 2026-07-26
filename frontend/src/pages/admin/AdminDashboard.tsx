import { Loader2 } from 'lucide-react';

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { useAdminStats } from '@/lib/api/admin';

/**
 * AdminDashboard — high-level counters + recent flags. Phase 11 will beef
 * this up per the critic report; for now it's the wired-through shell.
 */
export default function AdminDashboard() {
  const stats = useAdminStats();

  if (stats.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading admin stats…
      </div>
    );
  }
  if (stats.isError) {
    return <p className="text-sm text-destructive">Failed to load stats.</p>;
  }

  const s = stats.data;
  const cells: Array<[string, number | undefined]> = [
    ['Flags open', s?.flags_open],
    ['Flags total', s?.flags_total],
    ['Questions', s?.questions],
    ['Disabled qs', s?.questions_disabled],
    ['Topics', s?.topics],
    ['Users', s?.users],
    ['Uploads', s?.uploads],
    ['Mid-conf review', s?.review_medium],
    ['Synthetic review', s?.review_synthetic],
    ['Deficit topics', s?.deficit_topics],
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-4 pb-16">
      <h1 className="text-2xl font-semibold">Admin</h1>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {cells.map(([label, value]) => (
          <Card key={label}>
            <CardContent className="p-4">
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className="text-2xl font-semibold tabular-nums">
                {value ?? '—'}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recent flags</CardTitle>
          <CardDescription>Latest question issues raised by users.</CardDescription>
        </CardHeader>
        <CardContent>
          {s?.recent_flags?.length ? (
            <ul className="space-y-2 text-sm">
              {s.recent_flags.map((f) => (
                <li key={f.id} className="rounded border border-border p-2">
                  <div className="line-clamp-1 font-medium">
                    {f.question_text ?? '(no text)'}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {f.category} · {f.created_at ?? '—'}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No recent flags.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
