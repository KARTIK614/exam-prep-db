import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  useAdminFlags,
  useDisableFlagQuestion,
  useDismissFlag,
  useResolveFlag,
} from '@/lib/api/admin';

/**
 * AdminFlags — flag triage queue. Each row supports resolve, dismiss, or
 * disable-question. Filter by status via chips.
 */
export default function AdminFlags() {
  const [status, setStatus] = useState('open');
  const flags = useAdminFlags({ status });
  const resolve = useResolveFlag();
  const dismiss = useDismissFlag();
  const disable = useDisableFlagQuestion();

  return (
    <div className="mx-auto max-w-5xl space-y-4 pb-16">
      <h1 className="text-2xl font-semibold">Flags</h1>
      <div className="flex gap-2">
        {(['open', 'resolved', 'dismissed', 'all'] as const).map((s) => (
          <Button
            key={s}
            size="sm"
            variant={status === s ? 'default' : 'secondary'}
            onClick={() => setStatus(s)}
          >
            {s}
          </Button>
        ))}
      </div>

      <Card>
        <CardContent className="p-0">
          {flags.isLoading ? (
            <div className="p-6"><Loader2 className="h-4 w-4 animate-spin" /></div>
          ) : flags.data?.items?.length ? (
            <ul className="divide-y divide-border">
              {flags.data.items.map((f) => (
                <li key={f.id} className="p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs text-muted-foreground">
                        Q#{f.question_id} · {f.category} · {f.status} · {f.created_at}
                      </div>
                      <div className="line-clamp-2 text-sm">
                        {f.question_text ?? '(no text)'}
                      </div>
                      {f.note ? (
                        <div className="mt-1 rounded bg-bg-secondary p-2 text-xs">
                          {f.note}
                        </div>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 flex-col gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => resolve.mutate(f.id)}
                      >
                        Resolve
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => dismiss.mutate(f.id)}
                      >
                        Dismiss
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => disable.mutate(f.id)}
                      >
                        Disable Q
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="p-6 text-sm text-muted-foreground">No flags.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
