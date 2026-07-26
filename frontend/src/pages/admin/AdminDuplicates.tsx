import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { adminApi, useAdminDuplicates } from '@/lib/api/admin';

/**
 * AdminDuplicates — pair list from `/api/v1/admin/duplicates`.
 * Renders side-by-side with a Disable button for the suggested-disable.
 */
export default function AdminDuplicates() {
  const dupes = useAdminDuplicates();

  return (
    <div className="mx-auto max-w-6xl space-y-4 pb-16">
      <h1 className="text-2xl font-semibold">Duplicates</h1>
      {dupes.isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : !dupes.data?.pairs?.length ? (
        <p className="text-sm text-muted-foreground">No duplicate pairs.</p>
      ) : (
        <div className="space-y-3">
          {dupes.data.pairs.map((p, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Jaccard {p.jaccard.toFixed(3)} · shared {p.isize}
                </CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {[p.q1, p.q2].map((q) => (
                  <div
                    key={q.id}
                    className="rounded border border-border bg-bg-secondary p-3 text-sm"
                  >
                    <div className="text-xs text-muted-foreground">
                      Q#{q.id}
                      {p.suggested_disable === q.id ? (
                        <span className="ml-2 rounded bg-destructive/20 px-1 text-destructive">
                          suggest disable
                        </span>
                      ) : null}
                    </div>
                    <div className="whitespace-pre-wrap">{q.question_text}</div>
                    <Button
                      size="sm"
                      variant={
                        p.suggested_disable === q.id ? 'destructive' : 'ghost'
                      }
                      className="mt-2"
                      onClick={() => adminApi.disableDuplicate(q.id)}
                    >
                      Disable this
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
