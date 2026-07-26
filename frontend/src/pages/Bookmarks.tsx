import { Link, useNavigate } from 'react-router-dom';
import { BookmarkX, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { useBookmarks } from '@/lib/api/bookmarks';
import { useToggleBookmark } from '@/lib/api/questions';
import { useCreateTest } from '@/lib/api/tests';

/**
 * Bookmarks — R4 §3.3 `GET /bookmarks`. Table view with a per-row Remove
 * button (calls `DELETE /questions/{id}/bookmark`) plus a "Start test
 * from these" CTA that spins up a new test scoped to the bookmarked
 * question ids.
 */
export default function Bookmarks() {
  const bookmarks = useBookmarks({ limit: 100 });
  const toggle = useToggleBookmark();
  const createTest = useCreateTest();
  const navigate = useNavigate();

  const items = bookmarks.data?.bookmarks ?? [];

  const startTest = async () => {
    if (items.length === 0) return;
    // The Rust backend doesn't yet expose "test from ids" — best-effort:
    // create a test with those topics and let the user filter down.
    const topicIds = Array.from(
      new Set(items.map((b) => b.question.topic_id).filter((n): n is number => n !== null)),
    );
    try {
      const res = await createTest.mutateAsync({
        topic_ids: topicIds,
        question_count: Math.min(items.length, 25),
        test_mode: 'practice',
      });
      navigate(`/test/${res.test_id}`);
    } catch {
      // Silently fail — user can try again.
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 pb-16">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Bookmarks</h1>
          <p className="text-sm text-muted-foreground">
            Questions you've saved for later.
          </p>
        </div>
        {items.length > 0 ? (
          <Button onClick={startTest} disabled={createTest.isPending}>
            Start test from these
          </Button>
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Saved questions</CardTitle>
          <CardDescription>{items.length} bookmarked</CardDescription>
        </CardHeader>
        <CardContent>
          {bookmarks.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          ) : bookmarks.isError ? (
            <p className="text-sm text-destructive">Failed to load bookmarks.</p>
          ) : items.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              You haven't bookmarked any questions yet. Tap the star on a
              question inside a test to save it here.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-2 py-2">Topic</th>
                    <th className="px-2 py-2">Preview</th>
                    <th className="px-2 py-2">Difficulty</th>
                    <th className="px-2 py-2">Saved</th>
                    <th className="px-2 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((b) => (
                    <tr
                      key={b.bookmark_id}
                      className="border-b border-border last:border-0 hover:bg-muted/40"
                    >
                      <td className="px-2 py-2">
                        {b.question.topic_id ?? '—'}
                      </td>
                      <td className="max-w-md truncate px-2 py-2">
                        <Link
                          to={`/search?q=${encodeURIComponent(
                            (b.question.question_text ?? '').slice(0, 40),
                          )}`}
                          className="hover:underline"
                        >
                          {b.question.question_text ?? '(no text)'}
                        </Link>
                      </td>
                      <td className="px-2 py-2">
                        {b.question.difficulty ?? '—'}
                      </td>
                      <td className="px-2 py-2 text-xs text-muted-foreground">
                        {b.created_at ?? '—'}
                      </td>
                      <td className="px-2 py-2 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            toggle.mutate({
                              id: b.question.id,
                              isBookmarked: true,
                            })
                          }
                        >
                          <BookmarkX className="mr-1 h-4 w-4" /> Remove
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
