import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { adminApi, useAdminQuestions } from '@/lib/api/admin';
import type { Question } from '@/lib/api/types';

/**
 * AdminQuestions — question table with inline edit for basic fields.
 * Phase 11 lifts this into a proper editor with LaTeX preview.
 */
export default function AdminQuestions() {
  const [difficulty, setDifficulty] = useState('');
  const list = useAdminQuestions({ difficulty: difficulty || undefined });
  const [editing, setEditing] = useState<Question | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await adminApi.updateQuestion(editing.id, editing);
      setEditing(null);
      list.refetch();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 pb-16">
      <h1 className="text-2xl font-semibold">Questions</h1>
      <div className="flex gap-2">
        <select
          value={difficulty}
          onChange={(e) => setDifficulty(e.target.value)}
          className="h-10 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="">Any difficulty</option>
          <option value="easy">Easy</option>
          <option value="medium">Medium</option>
          <option value="hard">Hard</option>
        </select>
        <Button variant="ghost" onClick={() => list.refetch()}>
          Refresh
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {list.isLoading ? (
            <div className="p-6"><Loader2 className="h-4 w-4 animate-spin" /></div>
          ) : list.data?.items?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-left text-xs text-muted-foreground">
                    <th className="px-2 py-2">ID</th>
                    <th className="px-2 py-2">Text</th>
                    <th className="px-2 py-2">Diff</th>
                    <th className="px-2 py-2">Disabled</th>
                    <th className="px-2 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((q) => (
                    <tr key={q.id} className="border-b border-border last:border-0">
                      <td className="px-2 py-2 font-mono text-xs">{q.id}</td>
                      <td className="max-w-md truncate px-2 py-2">
                        {q.question_text}
                      </td>
                      <td className="px-2 py-2">{q.difficulty ?? '—'}</td>
                      <td className="px-2 py-2">{q.disabled ? 'yes' : 'no'}</td>
                      <td className="px-2 py-2 text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditing(q)}
                        >
                          Edit
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="p-6 text-sm text-muted-foreground">No questions.</p>
          )}
        </CardContent>
      </Card>

      {editing ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Editing Q#{editing.id}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <textarea
              value={editing.question_text ?? ''}
              onChange={(e) =>
                setEditing({ ...editing, question_text: e.target.value })
              }
              rows={4}
              className="w-full rounded-md border border-input bg-background p-2 text-sm"
            />
            <div className="grid gap-2 sm:grid-cols-2">
              {(['a', 'b', 'c', 'd'] as const).map((k) => (
                <Input
                  key={k}
                  value={(editing[`option_${k}` as keyof Question] as string) ?? ''}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      [`option_${k}`]: e.target.value,
                    })
                  }
                  placeholder={`Option ${k.toUpperCase()}`}
                />
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                className="w-24"
                value={editing.correct_option ?? ''}
                onChange={(e) =>
                  setEditing({ ...editing, correct_option: e.target.value })
                }
                placeholder="Correct"
              />
              <select
                value={editing.difficulty ?? ''}
                onChange={(e) =>
                  setEditing({ ...editing, difficulty: e.target.value || null })
                }
                className="h-10 rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="">difficulty</option>
                <option value="easy">easy</option>
                <option value="medium">medium</option>
                <option value="hard">hard</option>
              </select>
            </div>
            <textarea
              value={editing.explanation ?? ''}
              onChange={(e) =>
                setEditing({ ...editing, explanation: e.target.value })
              }
              rows={3}
              placeholder="Explanation"
              className="w-full rounded-md border border-input bg-background p-2 text-sm"
            />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
