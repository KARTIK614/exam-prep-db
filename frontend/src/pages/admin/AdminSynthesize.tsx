import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { adminApi } from '@/lib/api/admin';
import { useTopics } from '@/lib/api/topics';
import type { Question } from '@/lib/api/types';

/**
 * AdminSynthesize — LLM question generation. Skeletal:
 *   1. Select topic + count → POST /admin/synthesize
 *   2. Preview generated questions
 *   3. Commit selected ids
 */
export default function AdminSynthesize() {
  const topics = useTopics();
  const [topicId, setTopicId] = useState<string>('');
  const [count, setCount] = useState(10);
  const [batchId, setBatchId] = useState<number | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);

  const generate = async () => {
    if (!topicId) return;
    setLoading(true);
    try {
      const res = await adminApi.synthesize({
        topic_id: Number(topicId),
        count,
      });
      setBatchId(res.batch_id);
      const preview = await adminApi.synthesizePreview(res.batch_id);
      setQuestions(preview.questions ?? []);
    } finally {
      setLoading(false);
    }
  };

  const commit = async () => {
    if (batchId === null) return;
    await adminApi.synthesizeCommit(batchId, Array.from(selected));
    setBatchId(null);
    setQuestions([]);
    setSelected(new Set());
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4 pb-16">
      <h1 className="text-2xl font-semibold">Synthesize</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Generate</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label>Topic</Label>
              <select
                value={topicId}
                onChange={(e) => setTopicId(e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">Choose…</option>
                {(topics.data?.items ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>Count</Label>
              <Input
                type="number"
                min={1}
                max={40}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              />
            </div>
          </div>
          <Button onClick={generate} disabled={loading || !topicId}>
            {loading ? 'Generating…' : 'Generate'}
          </Button>
        </CardContent>
      </Card>

      {questions.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Preview · batch {batchId}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {questions.map((q) => (
              <label
                key={q.id}
                className="flex items-start gap-2 rounded border border-border p-2 text-sm"
              >
                <input
                  type="checkbox"
                  checked={selected.has(q.id)}
                  onChange={(e) => {
                    const next = new Set(selected);
                    if (e.target.checked) next.add(q.id);
                    else next.delete(q.id);
                    setSelected(next);
                  }}
                  className="mt-1"
                />
                <div>
                  <div>{q.question_text}</div>
                  <div className="text-xs text-muted-foreground">
                    {q.difficulty ?? '—'} · correct {q.correct_option ?? '?'}
                  </div>
                </div>
              </label>
            ))}
            <Button onClick={commit} disabled={selected.size === 0}>
              Commit {selected.size}
            </Button>
          </CardContent>
        </Card>
      ) : loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : null}
    </div>
  );
}
