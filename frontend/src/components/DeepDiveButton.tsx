/**
 * `<DeepDiveButton questionId={n} />` — collapsed until clicked. On
 * click, POSTs to `/api/v1/questions/{id}/deep-dive`; on success renders
 * a structured card (explanation + key facts + exam tips + follow-ups).
 * Errors surface with the backend's ref-id (see `docs/plans/ANSWER_LEAK_
 * AUDIT.md` for the envelope shape).
 */
import { useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useDeepDive, type DeepDiveResponse } from '@/lib/api/deepDive';
import { ApiError } from '@/lib/api/types';

export function DeepDiveButton({ questionId }: { questionId: number }) {
  const mutation = useDeepDive();
  const [data, setData] = useState<DeepDiveResponse | null>(null);
  const [errRef, setErrRef] = useState<string | null>(null);

  const handleClick = () => {
    setErrRef(null);
    mutation.mutate(questionId, {
      onSuccess: (res) => setData(res),
      onError: (err) => {
        const ref =
          err instanceof ApiError && err.requestId
            ? err.requestId
            : (err as Error).message.slice(0, 8);
        setErrRef(ref);
      },
    });
  };

  if (!data && !errRef) {
    return (
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="mt-2 gap-1.5"
        onClick={handleClick}
        disabled={mutation.isPending}
      >
        {mutation.isPending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Sparkles className="h-3.5 w-3.5" />
        )}
        {mutation.isPending ? 'Thinking…' : 'Explain with AI'}
      </Button>
    );
  }

  if (errRef) {
    return (
      <div className="mt-2 rounded border border-destructive/40 bg-destructive/10 p-2 text-xs">
        AI tutor temporarily unavailable. Ref:{' '}
        <code className="font-mono">{errRef}</code>{' '}
        <button
          type="button"
          className="ml-2 underline hover:no-underline"
          onClick={handleClick}
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-2 rounded border border-accent/30 bg-accent/5 p-3 text-xs">
      <div className="flex items-center gap-1.5 font-semibold text-accent">
        <Sparkles className="h-3.5 w-3.5" />
        AI explanation
        {data!.cached ? (
          <span className="text-muted-foreground">(cached)</span>
        ) : null}
      </div>
      <p className="whitespace-pre-wrap leading-relaxed">{data!.explanation}</p>
      {data!.key_facts.length > 0 && (
        <div>
          <div className="font-semibold">Key facts</div>
          <ul className="ml-4 list-disc">
            {data!.key_facts.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}
      {data!.exam_tips.length > 0 && (
        <div>
          <div className="font-semibold">Exam tips</div>
          <ul className="ml-4 list-disc">
            {data!.exam_tips.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}
      {data!.follow_up_suggestions.length > 0 && (
        <div className="text-muted-foreground">
          <div className="font-semibold">You might also want to know</div>
          <ul className="ml-4 list-disc">
            {data!.follow_up_suggestions.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
