import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ChevronDown, ChevronRight, Clock, FileText, X, Zap } from 'lucide-react';

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
  getLastPresetSlug,
  setLastPresetSlug,
  useExamPresets,
  type ExamPreset,
} from '@/lib/api/presets';
import { useCreateTest, usePapers } from '@/lib/api/tests';
import type { PaperSummary } from '@/lib/api/types';
import { useTopics } from '@/lib/api/topics';
import { ApiError } from '@/lib/api/types';
import type { CreateTestRequest } from '@/lib/api/types';
import { cn } from '@/lib/utils/cn';

/**
 * TestSetup — configure and start a test. Wire form for R4 §3.4
 * `POST /tests`.
 *
 * Prefill: `?topic_id=X` (from next-weak-topic click on Dashboard) pre-
 * selects that topic. Multiple `?topic_id=X&topic_id=Y` are also honoured.
 */

const COUNT_PRESETS = [10, 25, 50, 100] as const;
type NegPreset = 'none' | 'third' | 'quarter' | 'fifth' | 'custom';

export default function TestSetup() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const topics = useTopics();
  const createTest = useCreateTest();
  const papers = usePapers();

  // Prefill topics from ?topic_id=…
  const prefilled = useMemo(() => {
    const ids = params.getAll('topic_id').map(Number).filter((n) => Number.isFinite(n));
    return new Set(ids);
  }, [params]);

  const [selectedTopics, setSelectedTopics] = useState<Set<number>>(prefilled);
  const [countPreset, setCountPreset] = useState<number | 'custom'>(25);
  const [customCount, setCustomCount] = useState(30);
  const [mode, setMode] = useState<'practice' | 'exam'>('practice');
  const [negPreset, setNegPreset] = useState<NegPreset>('third');
  const [customNeg, setCustomNeg] = useState(0.33);
  const [pyqOnly, setPyqOnly] = useState(false);
  const [pyqYearMin, setPyqYearMin] = useState(2015);
  const [pyqYearMax, setPyqYearMax] = useState(2024);
  const [difficulty, setDifficulty] = useState<'easy' | 'medium' | 'hard' | ''>('');
  const [formError, setFormError] = useState<string | null>(null);
  const [customExpanded, setCustomExpanded] = useState(prefilled.size > 0);

  // Exam-preset picker (Sujit feedback — one-click bundles).
  const presets = useExamPresets();
  const [selectedPresetSlug, setSelectedPresetSlug] = useState<string | null>(
    () => getLastPresetSlug(),
  );

  const questionCount = countPreset === 'custom' ? customCount : countPreset;

  // Apply a preset to the form state (used by both "fill form" and
  // "start immediately" buttons).
  const applyPreset = (p: ExamPreset) => {
    setSelectedTopics(new Set(p.topic_ids));
    if ([10, 25, 50, 100].includes(p.question_count)) {
      setCountPreset(p.question_count as 10 | 25 | 50 | 100);
    } else {
      setCountPreset('custom');
      setCustomCount(p.question_count);
    }
    setMode(p.test_mode);
    setNegPreset(p.neg_marking_preset as NegPreset);
    setPyqOnly(p.pyq_only);
    setDifficulty(''); // preset uses difficulty_mix, not a single filter
    setSelectedPresetSlug(p.slug);
    setLastPresetSlug(p.slug);
    setFormError(null);
  };

  // Auto-scroll to Submit when a preset is applied via "Fill form".
  useEffect(() => {
    // no-op — the visible submit button is at the bottom of the form
  }, [selectedPresetSlug]);

  const toggleTopic = (id: number) => {
    setSelectedTopics((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!questionCount || questionCount < 1 || questionCount > 200) {
      setFormError('Question count must be between 1 and 200.');
      return;
    }

    const body: CreateTestRequest = {
      topic_ids: Array.from(selectedTopics),
      question_count: questionCount,
      test_mode: mode,
      pyq_only: pyqOnly,
      pyq_year_min: pyqOnly ? pyqYearMin : undefined,
      pyq_year_max: pyqOnly ? pyqYearMax : undefined,
      difficulty: difficulty === '' ? null : difficulty,
      neg_marking_preset: mode === 'exam' ? negPreset : 'none',
      neg_marking_ratio: negPreset === 'custom' ? customNeg : undefined,
    };

    try {
      const res = await createTest.mutateAsync(body);
      navigate(`/test/${res.test_id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(
          err.code === 'no_questions_matched_filter'
            ? 'No questions match those filters. Loosen the criteria.'
            : err.message,
        );
      } else {
        setFormError('Failed to start test. Please try again.');
      }
    }
  };

  const startPreset = async (p: ExamPreset) => {
    applyPreset(p);
    setFormError(null);
    const body: CreateTestRequest = {
      topic_ids: p.topic_ids,
      question_count: p.question_count,
      test_mode: p.test_mode,
      pyq_only: p.pyq_only,
      difficulty: null,
      neg_marking_preset: p.test_mode === 'exam' ? p.neg_marking_preset : 'none',
    };
    try {
      const res = await createTest.mutateAsync(body);
      navigate(`/test/${res.test_id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(
          err.code === 'no_questions_matched_filter'
            ? 'No questions match this preset. Try another.'
            : err.message,
        );
      } else {
        setFormError('Failed to start test. Please try again.');
      }
    }
  };

  const startPaper = async (paper: PaperSummary) => {
    setFormError(null);
    try {
      const res = await createTest.mutateAsync({
        topic_ids: [],
        question_count: paper.question_count,
        test_mode: 'exam',
        paper_code: paper.paper_code,
      });
      navigate(`/test/${res.test_id}`);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Failed to start the paper. Please try again.');
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4 pb-16">
      <div>
        <h1 className="text-2xl font-semibold">Start a test</h1>
        <p className="text-sm text-muted-foreground">
          Sit a full paper, pick a preset bundle, or customise your own.
        </p>
      </div>

      {papers.data && papers.data.papers.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FileText className="h-4 w-4" /> Full papers
            </CardTitle>
            <CardDescription>
              Official papers in their original order, with exam marking: −1/3 of the marks for a
              wrong single-answer question, nothing off for multiple-correct or numerical. Pause any
              time; the clock runs in 50-minute blocks with a 10-minute break.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {papers.data.papers.map((p) => (
              <div
                key={p.paper_code}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3"
              >
                <div>
                  <div className="font-medium">{paperLabel(p.paper_code)}</div>
                  <div className="text-xs text-muted-foreground">
                    {p.question_count} questions · {p.max_marks} marks
                    {p.sections.length ? ` · ${p.sections.join(' + ')}` : ''}
                  </div>
                </div>
                <Button
                  size="sm"
                  onClick={() => startPaper(p)}
                  disabled={createTest.isPending}
                >
                  Start paper
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {/* Preset picker — Sujit feedback: one-click exam bundles */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Zap className="h-4 w-4" /> Quick start — exam bundles
          </CardTitle>
          <CardDescription>
            One-click presets for common exams. Click "Start" to jump straight in,
            or "Fill form" to tweak before launching.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {presets.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="h-28 animate-pulse rounded-md bg-muted"
                />
              ))}
            </div>
          ) : presets.isError || !presets.data ? (
            <p className="text-sm text-muted-foreground">
              Presets unavailable right now. Use the custom form below.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {presets.data.items.map((p) => {
                const active = p.slug === selectedPresetSlug;
                return (
                  <div
                    key={p.slug}
                    className={cn(
                      'flex flex-col gap-2 rounded-md border p-3 transition-colors',
                      active
                        ? 'border-primary bg-primary/5'
                        : 'border-border bg-bg-secondary',
                    )}
                  >
                    <div>
                      <div className="text-sm font-medium">{p.name}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {p.description}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5 text-xs">
                      <Badge>{p.question_count} Qs</Badge>
                      <Badge>{p.test_mode === 'exam' ? 'Exam' : 'Practice'}</Badge>
                      {p.neg_marking_preset !== 'none' ? (
                        <Badge>
                          {p.neg_marking_preset === 'third'
                            ? '−1/3'
                            : p.neg_marking_preset === 'quarter'
                              ? '−1/4'
                              : p.neg_marking_preset === 'fifth'
                                ? '−1/5'
                                : '−custom'}
                        </Badge>
                      ) : null}
                      {p.pyq_only ? <Badge>PYQ only</Badge> : null}
                      <span className="ml-auto inline-flex items-center gap-1 text-muted-foreground">
                        <Clock className="h-3 w-3" />
                        {p.suggested_minutes} min
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => startPreset(p)}
                        disabled={createTest.isPending}
                      >
                        Start
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          applyPreset(p);
                          setCustomExpanded(true);
                        }}
                      >
                        Fill form
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Custom test — collapsed by default */}
      <button
        type="button"
        onClick={() => setCustomExpanded((v) => !v)}
        className="flex w-full items-center gap-1 text-sm font-medium text-primary hover:underline"
      >
        {customExpanded ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        Customise instead
      </button>

      <form
        onSubmit={onSubmit}
        className={cn('space-y-4', customExpanded ? '' : 'hidden')}
      >
        {/* Topics multi-select */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Topics</CardTitle>
            <CardDescription>
              Empty = all topics. Click to add/remove.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {topics.isLoading ? (
              <div className="flex gap-2">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-8 w-24 animate-pulse rounded-full bg-muted"
                  />
                ))}
              </div>
            ) : topics.isError ? (
              <p className="text-sm text-destructive">Failed to load topics.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {(topics.data?.items ?? []).map((t) => {
                  const on = selectedTopics.has(t.id);
                  return (
                    <button
                      type="button"
                      key={t.id}
                      onClick={() => toggleTopic(t.id)}
                      className={cn(
                        'inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm transition-colors',
                        on
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-border bg-bg-secondary text-text-primary hover:bg-muted',
                      )}
                    >
                      <span>{t.name ?? `Topic ${t.id}`}</span>
                      {on ? <X className="h-3 w-3" /> : null}
                    </button>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Question count */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Question count</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-2">
              {COUNT_PRESETS.map((n) => (
                <RadioButton
                  key={n}
                  label={String(n)}
                  active={countPreset === n}
                  onClick={() => setCountPreset(n)}
                />
              ))}
              <RadioButton
                label="Custom"
                active={countPreset === 'custom'}
                onClick={() => setCountPreset('custom')}
              />
              {countPreset === 'custom' ? (
                <Input
                  type="number"
                  min={1}
                  max={200}
                  value={customCount}
                  onChange={(e) => setCustomCount(Number(e.target.value))}
                  className="w-24"
                />
              ) : null}
            </div>
          </CardContent>
        </Card>

        {/* Mode */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Mode</CardTitle>
            <CardDescription>
              Practice: no negative marking, explanations after each answer.
              Exam: negative marking applies.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2">
              <RadioButton
                label="Practice"
                active={mode === 'practice'}
                onClick={() => setMode('practice')}
              />
              <RadioButton
                label="Exam"
                active={mode === 'exam'}
                onClick={() => setMode('exam')}
              />
            </div>
          </CardContent>
        </Card>

        {/* Negative marking (only in exam mode) */}
        {mode === 'exam' ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Negative marking</CardTitle>
              <CardDescription>Ratio deducted per wrong answer.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                <RadioButton
                  label="None"
                  active={negPreset === 'none'}
                  onClick={() => setNegPreset('none')}
                />
                <RadioButton
                  label="1/3"
                  active={negPreset === 'third'}
                  onClick={() => setNegPreset('third')}
                />
                <RadioButton
                  label="1/4"
                  active={negPreset === 'quarter'}
                  onClick={() => setNegPreset('quarter')}
                />
                <RadioButton
                  label="1/5"
                  active={negPreset === 'fifth'}
                  onClick={() => setNegPreset('fifth')}
                />
                <RadioButton
                  label="Custom"
                  active={negPreset === 'custom'}
                  onClick={() => setNegPreset('custom')}
                />
                {negPreset === 'custom' ? (
                  <Input
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={customNeg}
                    onChange={(e) => setCustomNeg(Number(e.target.value))}
                    className="w-24"
                  />
                ) : null}
              </div>
            </CardContent>
          </Card>
        ) : null}

        {/* PYQ + difficulty */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Filters</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="pyq"
                checked={pyqOnly}
                onChange={(e) => setPyqOnly(e.target.checked)}
                className="h-4 w-4"
              />
              <Label htmlFor="pyq" className="cursor-pointer">
                Previous-year questions only
              </Label>
            </div>

            {pyqOnly ? (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="yearMin">Year min</Label>
                  <Input
                    id="yearMin"
                    type="number"
                    min={2000}
                    max={2030}
                    value={pyqYearMin}
                    onChange={(e) => setPyqYearMin(Number(e.target.value))}
                  />
                </div>
                <div>
                  <Label htmlFor="yearMax">Year max</Label>
                  <Input
                    id="yearMax"
                    type="number"
                    min={2000}
                    max={2030}
                    value={pyqYearMax}
                    onChange={(e) => setPyqYearMax(Number(e.target.value))}
                  />
                </div>
              </div>
            ) : null}

            <div>
              <Label className="mb-2 block">Difficulty</Label>
              <div className="flex gap-2">
                <RadioButton
                  label="Any"
                  active={difficulty === ''}
                  onClick={() => setDifficulty('')}
                />
                <RadioButton
                  label="Easy"
                  active={difficulty === 'easy'}
                  onClick={() => setDifficulty('easy')}
                />
                <RadioButton
                  label="Medium"
                  active={difficulty === 'medium'}
                  onClick={() => setDifficulty('medium')}
                />
                <RadioButton
                  label="Hard"
                  active={difficulty === 'hard'}
                  onClick={() => setDifficulty('hard')}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {formError ? (
          <div
            role="alert"
            className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
          >
            {formError}
          </div>
        ) : null}

        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => navigate(-1)}
            disabled={createTest.isPending}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={createTest.isPending}>
            {createTest.isPending ? 'Starting…' : 'Start test'}
          </Button>
        </div>
      </form>
    </div>
  );
}

/** "GATE2024_CS_S1" → "GATE 2024 · CS · Set 1". */
function paperLabel(code: string): string {
  const m = /^([A-Z]+)(\d{4})_([A-Z]+)(?:_S(\d))?$/.exec(code);
  if (!m) return code.replace(/_/g, ' ');
  return `${m[1]} ${m[2]} · ${m[3]}${m[4] ? ` · Set ${m[4]}` : ''}`;
}

function RadioButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-md border px-3 py-1.5 text-sm transition-colors',
        active
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border bg-bg-secondary hover:bg-muted',
      )}
    >
      {label}
    </button>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border bg-bg-primary px-2 py-0.5 text-xs">
      {children}
    </span>
  );
}
