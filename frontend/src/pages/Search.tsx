import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2, SearchIcon } from 'lucide-react';

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
import { useSearch } from '@/lib/api/search';
import { useTopics } from '@/lib/api/topics';

/**
 * Search — R4 §3.3 `GET /search`. Full-page FTS5 search with debounced
 * query + filters. Snippets from the API are HTML-escaped so we render
 * them via `dangerouslySetInnerHTML` after the backend has already
 * highlighted matches with `<mark>` tags (per Flask precedent).
 */
export default function Search() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get('q') ?? '');
  const [topicId, setTopicId] = useState<string>('');
  const [difficulty, setDifficulty] = useState<string>('');
  const [confidence, setConfidence] = useState<string>('');
  const topics = useTopics();

  const searchParams = useMemo(
    () => ({
      q,
      topic_id: topicId ? Number(topicId) : undefined,
      difficulty: difficulty || undefined,
      confidence: confidence || undefined,
    }),
    [q, topicId, difficulty, confidence],
  );
  const search = useSearch(searchParams);

  const items = search.data?.items ?? [];

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setParams((p) => {
      const np = new URLSearchParams(p);
      if (q) np.set('q', q);
      else np.delete('q');
      return np;
    });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 pb-16">
      <div>
        <h1 className="text-2xl font-semibold">Search</h1>
        <p className="text-sm text-muted-foreground">
          Full-text search across every question in your bank.
        </p>
      </div>

      <form onSubmit={onSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Type at least 2 characters…"
            className="pl-9"
            autoFocus
          />
        </div>
        <Button type="submit">Search</Button>
      </form>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Filters</CardTitle>
          <CardDescription>
            Narrow results by topic, difficulty, and confidence.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <Label htmlFor="topic">Topic</Label>
              <select
                id="topic"
                value={topicId}
                onChange={(e) => setTopicId(e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">Any topic</option>
                {(topics.data?.items ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="difficulty">Difficulty</Label>
              <select
                id="difficulty"
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">Any</option>
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </div>
            <div>
              <Label htmlFor="confidence">Confidence</Label>
              <select
                id="confidence"
                value={confidence}
                onChange={(e) => setConfidence(e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">Any</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      <div>
        {q.trim().length < 2 ? (
          <p className="text-sm text-muted-foreground">
            Enter at least 2 characters to search.
          </p>
        ) : search.isLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Searching…
          </div>
        ) : search.isError ? (
          <p className="text-sm text-destructive">Search failed.</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No matches. Try loosening filters.
          </p>
        ) : (
          <ul className="space-y-3">
            {items.map((hit) => (
              <li
                key={hit.id}
                className="rounded-md border border-border bg-bg-secondary p-3"
              >
                <div className="text-xs text-muted-foreground">
                  Q#{hit.id} · {hit.difficulty ?? '—'}
                </div>
                <div
                  className="mt-1 text-sm"
                  // Backend produces `<mark>`-highlighted snippet HTML.
                  dangerouslySetInnerHTML={{
                    __html: hit.snippet || hit.question_text || '',
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
