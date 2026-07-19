# Plan C — Dashboard & Analytics

Scope: four features that make the dashboard actively guide day-to-day study
rather than just report history.

1. **Topic-mastery progress bars** — surface `topic_mastery` on dashboard + analytics.
2. **Study streak + daily goal tracker** — light, forgiving, non-punitive.
3. **"Next weak topic" suggestion** — auto-recommend what to study, weighted by exam impact.
4. **Time-per-question benchmarks** — user vs their own average vs target pace.

Author: research fork, 2026-07-15. Planning only, no code changes.

---

## 0. Quick summary (read this first)

| Feature | Effort | Blocking? | Impact |
| --- | --- | --- | --- |
| Topic-mastery bars | 3 h | No | High — makes dashboard useful |
| Consistency score (not streak) | 4 h | Adds one column | Medium — motivation without punishment |
| Next-weak-topic suggestion | 4 h | Uses existing tables | Very high — turns dashboard into a coach |
| Time-per-question benchmarks | 5 h | Needs derived stats | Medium — meaningful on exam-day pace |

**Total: ~16 h of work, spread over 2–3 evenings.**
Recommended order: `bars → next-weak → consistency → time benchmarks`.
Bars unblock everything visually. Next-weak is the biggest UX win. Time benchmarks
depend on having ≥5 completed tests to be meaningful, so they can wait.

**One prerequisite:** whatever new columns we add MUST be applied to Turso Cloud
via explicit `ALTER TABLE` statements. `db.py`'s `SCHEMA` string is never actually
executed against Turso — see [plan 00 tech-debt](00-tech-debt.md).

---

## 1. Feature: Topic-mastery progress bars

### What it is
A grid of all 18 Paper II topics (and 24 Paper I topics eventually) showing
mastery % and coverage on a single scannable view. Replaces "did I take a test
recently?" with "am I close to my target on each topic?"

### Current state (grounded in code)

- `topic_mastery` already has `current_score`, `test_count`, `last_studied`, `status`
  (columns: `diagnostic_score, current_score, study_hours, status, last_studied, test_count`).
- `bp_tests.py:145-164` updates it after every test with a 60/40 EMA blend of old and new score.
- `templates/index.html:60-122` shows two lists (weak/strong) with inline `score-bar` divs.
  Design tokens exist (`--primary`, `--success`, `--danger`, `--warning`, `.score-bar`, `.score-bar-fill`).
- `templates/analytics.html:44-55` has a Chart.js bar chart of mastery scores, but it
  labels topics vertically and doesn't group by paper or weightage.

### Competitor scan

| Product | Mastery UI | What to steal | What to skip |
| --- | --- | --- | --- |
| Anki | Retention % per deck, small line chart | Show recency (days since last review) alongside score | Retention formula overkill for MCQ |
| Khan Academy | 4-step ladder (Not started → Familiar → Proficient → Mastered) | Named tiers > raw %, easier to feel | Their ladder needs multiple practice types we don't have |
| Duolingo | Crown levels (0-5), gold when maxed | Small badge/dot for "at target" | Level-up animations are noise for exam prep |
| Testbook | Ring per topic + attempted-questions count | Ring + count as one component | They over-index on volume; ignore |
| Adda247 | Bar chart, no color coding | Bar chart is what we already have | Same-color bars are useless |
| Kaggle Learn | Progress ring per course | Ring form factor for hero cards | Their achievements gamification |

### Design decision

Two levels of visualization, both driven by the same data:

1. **Dashboard hero grid**: 3-column responsive grid of all attempted topics, sorted by (needs-attention DESC, weightage DESC). Each cell has: topic name, weightage badge, mastery bar, mini-stat "N tests · X days ago".
2. **Analytics page grid**: full 18-topic grid grouped by paper, with a legend
   for the 4-tier color coding (not started / weak <60 / on-track 60–74 / mastered ≥75).

Keep the existing weak/strong list on dashboard **below** the grid — it's the
"triage view" but not the primary artifact.

The tier thresholds should read from the existing `settings.weakness_threshold`
(default 60) and `settings.target_score` (default 75), not be hardcoded.

### Schema changes

**None.** All data already exists. Nice.

### Implementation plan

**Backend (`bp_main.py`):**

Add a computed field per topic in the topics query used by `/`:

```python
# in bp_main.py, replace the topics query
topics = db.execute("""
    SELECT tm.*, t.name, t.subject, t.paper, t.weightage,
           CAST((julianday('now') - julianday(tm.last_studied)) AS INTEGER) AS days_since,
           CASE
             WHEN tm.current_score IS NULL OR tm.test_count = 0 THEN 'untested'
             WHEN tm.current_score < :weak THEN 'weak'
             WHEN tm.current_score < :target THEN 'on_track'
             ELSE 'mastered'
           END AS tier
    FROM topic_mastery tm JOIN topics t ON tm.topic_id = t.id
    ORDER BY t.paper, tm.current_score ASC NULLS FIRST
""", {"weak": weak, "target": target}).fetchall()
```

Also seed a `topic_mastery` row per topic on first-run so `LEFT JOIN` isn't
needed — or use `LEFT JOIN` to include topics that have never had a test.
Currently untested topics show up in `bp_main.py:32` via `test_count == 0`, so
we already do this the right way. Keep it.

**Frontend (`templates/index.html`):**

Replace the two side-by-side weak/strong cards (lines 60-122) with a single
"Mastery Grid" card containing a responsive grid of `topic-tile` divs. Keep the
weak/strong lists as a lower "Priority Review" section (only weak-tier topics,
capped at 5). Move strong topics to analytics — a dashboard should show what
you must fix, not what you've already conquered.

**Frontend (`templates/analytics.html`):**

Replace the bar chart at lines 44-55 (which uses Chart.js) with the same
CSS-only grid, grouped by paper. Chart.js is already loaded for other charts on
this page — keep it for the progress-over-time and paper-comparison — but a
grid renders faster and is easier to read for 18 discrete items.

**CSS additions (`static/style.css`):**

```css
.mastery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.topic-tile {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
}
.topic-tile.tier-untested { background: #f9fafb; opacity: 0.7; }
.topic-tile.tier-weak      { border-left: 3px solid var(--danger); }
.topic-tile.tier-on_track  { border-left: 3px solid var(--warning); }
.topic-tile.tier-mastered  { border-left: 3px solid var(--success); }
.topic-tile .weight-badge {
  font-size: 10px; padding: 2px 6px; border-radius: 3px;
  background: var(--primary-light); color: var(--primary);
}
.topic-tile .tile-meta {
  font-size: 11px; color: var(--text-muted); margin-top: 6px;
}
```

No new JS needed. All state is server-rendered.

### UI mockup — dashboard mastery grid

```
┌─── Topic Mastery ──────────────────────────────────────────────┐
│                                                                │
│ ┌── DBMS & SQL ──[10]──┐ ┌── Data Struct ─[8]──┐ ┌── OS ─[8]─┐│
│ │ ████████████░░░ 71%  │ │ ██████████░░░░░ 62% │ │ ░░░░░░░ - ││
│ │ 4 tests · 2d ago     │ │ 2 tests · 5d ago    │ │ untested  ││
│ └──────────────────────┘ └─────────────────────┘ └───────────┘│
│                                                                │
│ ┌── Networks ────[8]───┐ ┌── Comp Fund ──[10]─┐ ┌── SAD ─[4]─┐│
│ │ █████████████░ 82%   │ │ ███████░░░░░░░ 44% │ │ ██████░ 55%││
│ │ 6 tests · 1d ago     │ │ 3 tests · 7d ago   │ │ 1 test·9d ││
│ └──────────────────────┘ └────────────────────┘ └───────────┘│
│                                                                │
│  Legend: ▮weak <60   ▮on-track   ▮mastered ≥75   ░untested   │
└────────────────────────────────────────────────────────────────┘
```

Left border color = tier. `[N]` badge = weightage. Sort order: weak first, then
on-track (by weightage DESC), then untested (by weightage DESC), then mastered.
This surfaces "high-value work you haven't done" at the top.

### Effort
- Backend query changes: 1 h
- CSS + templates: 1.5 h
- Testing across empty/partial/full data states: 0.5 h
- **Total: 3 h**

---

## 2. Feature: Consistency score (NOT a streak)

### Why not a streak

Duolingo-style streaks are engineered around loss aversion — the fear of losing
your 47-day streak is what drags you back to the app. That works for open-ended
learning where "just do 5 minutes" is meaningful.

For **Kartik's context** this is wrong:

- Fixed exam date. The goal is score on exam day, not perpetual engagement.
- Solo user. No social pressure to keep face. Nobody sees a broken streak.
- Mon–Fri study pattern likely. A weekend gap breaks the streak weekly. Two
  broken streaks and the user learns to distrust the metric.
- High-stakes context. Losing a streak on top of exam anxiety = actively harmful.
- No "streak freeze economics" — Duolingo can offer freezes because they make
  money from it. We have nothing to sell.

The academic literature on this is clear: streaks are effective for habit
**formation** in low-stakes daily contexts (Woolley & Fishbach 2017; Habitica
data). For high-stakes preparation where the user is already extrinsically
motivated, streaks add anxiety without adding action. The Duolingo streak-freeze
mechanic exists specifically because their designers know pure streaks are
brittle.

### What to build instead: consistency score

A 4-week rolling metric that answers "how consistent has your practice been?"
without punishing any single day.

**Definition:**
```
consistency = min(100, 100 * (days_with_any_activity_in_last_28) / 20)
```

- `days_with_any_activity` counts a day if the user completed ≥1 test OR
  logged a study_session with `duration_min >= 10`.
- Denominator 20 (not 28) means "you can miss 8 days out of 28 and still hit
  100%". That's roughly 5 study days a week, matching Kartik's likely rhythm.
- Score decays gracefully — 15 active days = 75%, 10 active days = 50%. Missing
  one day never causes a cliff.

**Display:**
- Show as a percentage badge on the dashboard hero card.
- Show a 28-cell activity strip below the badge (see mockup).
- No fireworks, no "you're on fire!" copy. Just the number.

### Competitor scan

| Product | Metric | Fits our case? |
| --- | --- | --- |
| Duolingo | Streak (contiguous days) | No — punitive |
| Anki | "Reviews due today" + retention % | Better — outcome-based |
| Khan Academy | "Energy points" + activity heatmap | Similar to what we propose |
| Codecademy | Weekly goal + progress bar | Yes — matches our consistency-score idea |
| Habitica | Habits list with per-habit streaks | Too heavy for one exam |
| GitHub contribution graph | Green-square activity grid | Excellent visual, steal directly |

The GitHub contribution graph is the reference. It communicates activity
without ever saying "you failed today". We already have a 30-day heatmap
in `bp_analytics.py:61-69` — we can promote a compact 28-day version to the
dashboard.

### Schema changes

Add one derived column? No — we already have enough. Just query:

```python
active_days = db.execute("""
    SELECT COUNT(DISTINCT d) FROM (
      SELECT date(completed_at) AS d FROM mock_tests
        WHERE completed_at >= date('now', '-28 days') AND status = 'completed'
      UNION
      SELECT date FROM study_sessions
        WHERE date >= date('now', '-28 days') AND duration_min >= 10
    )
""").fetchone()[0]
consistency = min(100, active_days * 5)   # active_days / 20 * 100
```

That's it. No new table, no new column.

Optionally add a `daily_goal_min` to `settings` (default 30) so the user can
tune what counts as "enough" — but keep the default as "≥10 min or ≥1 test".

### Implementation plan

**Backend (`bp_main.py`):**

Add two new fields to the `/` route context: `consistency_score` (int 0–100)
and `activity_28d` (list of 28 dicts `{date, has_activity, minutes}`).

**Frontend (`templates/index.html`):**

New hero card above the existing stat grid. See mockup below.

**CSS additions (`static/style.css`):**

```css
.hero-card {
  display: flex; align-items: center; gap: 20px;
  padding: 20px; margin-bottom: 24px;
  background: linear-gradient(135deg, var(--primary-light), #fff);
  border: 1px solid var(--border); border-radius: 12px;
}
.consistency-value { font-size: 42px; font-weight: 700; color: var(--primary); }
.activity-strip { display: flex; gap: 2px; }
.activity-cell {
  width: 12px; height: 12px; border-radius: 2px; background: #e5e7eb;
}
.activity-cell.level-1 { background: rgba(37,99,235,0.4); }
.activity-cell.level-2 { background: rgba(37,99,235,0.7); }
.activity-cell.level-3 { background: rgba(37,99,235,1.0); }
```

### UI mockup — dashboard hero

```
┌──────────────────────────────────────────────────────────────────┐
│  Consistency               Next weak topic                        │
│                                                                   │
│    68%      ▮ ▮ ░ ▮ ▮ ▮ ▮  → Computer Fundamentals (10 pts)      │
│             ░ ▮ ▮ ▮ ░ ▮ ▮    Last score 44% · 3 days since study  │
│    active   ▮ ▮ ▮ ▮ ░ ░ ▮                                         │
│    17/20    ▮ ▮ ▮ ░ ▮ ▮ ░    [ Start focused test ]  [ Study ]   │
│    days     ▮ ▮ ▮ ▮ ░                                            │
│                                                                   │
│    28-day activity          (algorithm: see plan §3)              │
└──────────────────────────────────────────────────────────────────┘
```

**Language matters.** "17/20 active days" reads as progress. "Broken 3-day streak"
reads as failure. Same underlying data, different emotion.

### Effort
- Backend query + template partial: 2 h
- CSS + activity strip: 1 h
- Copy tuning + testing empty/partial: 1 h
- **Total: 4 h**

---

## 3. Feature: "Next weak topic" suggestion

### Goal
A single recommendation on the dashboard: "spend your next 30 minutes on X".
Must beat naive "pick the lowest score" — because that would send Kartik to
IoT (3 pts, weightage 3) when DBMS (10 pts, currently at 44%) is a bigger
score lever.

### Current behavior
`bp_main.py:30` filters weak topics as `current_score < 60 AND test_count > 0`,
sorted by `current_score ASC`. This ignores weightage entirely. If Kartik has
IoT at 40% (2 questions asked) and DBMS at 55% (30 questions asked), IoT ranks
higher — but studying IoT gains him 3 potential exam points while DBMS gains 10.

### Algorithm options evaluated

**Option A — Naive lowest score**
- Rank: `ORDER BY current_score ASC`
- ✗ Ignores weightage → sends user to low-impact topics
- ✗ Ignores confidence (a 40% score from 2 questions is much less certain than 40% from 30)
- ✗ Ignores recency → keeps recommending topics the user just studied

**Option B — Weighted gap × weightage**
- Rank: `score = (target_score - current_score) × weightage`
- Expected points recoverable if you close the gap.
- ✓ Correctly prioritizes DBMS at 44% (0.31 × 10 = 3.1) over IoT at 40% (0.35 × 3 = 1.05).
- ✗ Still ignores confidence and recency.

**Option C — Weighted gap × weightage × recency decay × confidence**
- Rank: `score = (target - current) × weightage × recency_factor × confidence_factor`
- `recency_factor` = 1.0 if last studied >7 days ago, 0.5 if 3–7 days, 0.2 if <3 days (don't cram same topic daily)
- `confidence_factor` = min(1.0, test_count / 5) — a topic tested only twice gets weighted less
- ✓ Most accurate.
- ✗ Complex. Requires tuning. Explaining "why this recommendation?" gets hard.

**Option D — Multi-armed bandit (Thompson sampling)**
- Model each topic as a Beta distribution of success probability, sample, and
  recommend the topic with highest expected score improvement.
- ✓ Handles exploration-vs-exploitation formally.
- ✗ Massive overkill for 18 topics and one user. Debugging is a nightmare.
- ✗ Doesn't easily incorporate the weightage constraint.

### Recommendation: Option C, but simpler

Use Option C with only 3 factors, and expose the reasoning in the UI so the
user trusts it:

```python
def next_weak_topic_score(row, target=75):
    gap = max(0, target - (row['current_score'] or 0))
    weightage = row['weightage']
    days_since = row['days_since'] or 999
    if days_since < 3:  recency = 0.3   # don't cram same topic
    elif days_since < 7: recency = 0.7
    else: recency = 1.0
    confidence = min(1.0, (row['test_count'] or 0) / 5)
    # For untested topics, use diagnostic weight only (don't require confidence).
    if row['test_count'] == 0:
        return weightage * 2.0  # boost untested high-weight topics
    return gap * weightage * recency * confidence
```

This meaningfully beats "lowest score" while remaining explainable to the user:

> **DBMS & SQL** — current 44%, weight 10, last studied 7d ago
> _Would gain up to +3.1 exam points_

That "would gain up to +N exam points" hint is the killer feature — it turns
an abstract recommendation into concrete motivation.

### Handling ties / edge cases

- Skip topics with `days_since < 1` — user just studied it today, breathe.
- If no topic has `gap > 0`, recommend "You're above target on all attempted
  topics. Move to untested topics: [list]".
- If all topics untested, recommend "Take a diagnostic test to identify gaps."
- Always show the top-3 candidates in a collapsible list, so if the user
  disagrees with #1 they see the alternatives.

### Competitor scan

| Product | Recommendation algorithm | Fit |
| --- | --- | --- |
| Anki | Cards due today (FSRS-driven) | Different mechanic (per-card SR, not per-topic) |
| Khan Academy | "Continue where you left off" | Too passive |
| Duolingo | "Weakest skill" via internal model | Similar goal, opaque algorithm |
| Testbook | "Recommended for you" — usually paid content | Not actually adaptive |
| Adda247 | Same as Testbook | Not applicable |
| Kaggle Learn | Linear course progression | Wrong domain |

Nothing in the exam-prep space does this well. This is a differentiator.

### Schema changes

**None.** We already have `weightage` (topics), `current_score`, `test_count`,
`last_studied` (topic_mastery). All queries are single-table joins.

### Implementation plan

**Backend (`bp_main.py`):**

Add helper `_rank_next_topic(db)` that returns the top-3 candidates with
per-topic reasoning strings. Pass into template.

**Frontend (`templates/index.html`):**

New card in the hero grid (right side, next to consistency badge). See §2 mockup.
Also add a "See top 3" expand toggle showing alternatives.

**Test plan:**
- Empty DB → shows "take a diagnostic test" state.
- All topics mastered → shows "move to untested" state.
- Weak DBMS (weight 10) + weak IoT (weight 3), both at 45% → DBMS wins. Assert.
- Recently-studied DBMS + weak Networks → Networks wins (recency factor cuts DBMS score).

### Effort
- Algorithm helper + tests: 2 h
- Backend integration: 0.5 h
- Frontend card + "See top 3" reveal: 1 h
- Copy tuning ("would gain up to +N points" phrasing): 0.5 h
- **Total: 4 h**

---

## 4. Feature: Time-per-question benchmarks

### Goal
Show the user how their pacing compares to (a) their own moving average and
(b) a target derived from real exam constraints.

BCI paper is 100 Qs in 120 minutes → **72 seconds/question target**. If Kartik
consistently averages 100 s/question, he'll physically run out of time. This
metric is exam-critical and currently invisible.

### Current state

- `bp_analytics.py:43-49` already computes `avg_time` per test.
- `test_responses` has `time_spent_sec` per question.
- No target line, no per-difficulty breakdown, no "you're slowing down"
  warning.

### Design

Three sub-widgets:

**a. Pace-per-test line chart** (already exists on analytics; enhance)
- Add a horizontal target line at the exam pace (72 s for BCI, configurable).
- Color line red if user is >20% over target, amber 0–20% over, green under.
- Add a 5-test moving-average line so single-test outliers don't spook.

**b. Time-by-difficulty stacked bar** (new)
- Group `test_responses` by question difficulty, show mean time.
- Easy: expected ≤50s. Medium ≤72s. Hard ≤100s. Color-coded vs target.

**c. Slow-question spotlight** (new, on error log)
- Top-10 questions where `time_spent_sec > 2 × target AND is_correct = 0`.
- These are "time sinks that also cost accuracy" — the most valuable to review.

### Schema changes

Add to `settings`:
```sql
INSERT OR IGNORE INTO settings (key, value) VALUES ('target_seconds_per_q', '72');
```

No other schema changes. `test_responses.time_spent_sec` and `questions.difficulty`
already give us everything.

### Competitor scan

| Product | Pacing UI | Notable |
| --- | --- | --- |
| Testbook | Per-question timer only, no analytics | We can do better |
| Adda247 | Overall test time, no per-Q | Same |
| Oliveboard | "Time analysis" section — per-Q breakdown, decent | Steal the layout |
| Anki | Time-per-card in stats page | Different context |
| RPSC actual exam | Ticks up in exam UI | Just for reference; test.html should mirror this |

Oliveboard has the closest match. Their "Time Analysis" tab is a good reference
for what to build on the analytics page.

### Implementation plan

**Backend (`bp_analytics.py`):**

Add three new context variables:

```python
target_sec = int(settings.get('target_seconds_per_q', 72))

# Moving-average pace
recent_pace = db.execute("""
    SELECT mt.id, AVG(tr.time_spent_sec) as avg_time,
           date(mt.completed_at) as d
    FROM mock_tests mt JOIN test_responses tr ON mt.id = tr.test_id
    WHERE mt.status='completed'
    GROUP BY mt.id ORDER BY mt.completed_at DESC LIMIT 20
""").fetchall()

pace_by_difficulty = db.execute("""
    SELECT q.difficulty, AVG(tr.time_spent_sec) as avg_time,
           COUNT(*) as n
    FROM test_responses tr JOIN questions q ON tr.question_id = q.id
    JOIN mock_tests mt ON tr.test_id = mt.id
    WHERE mt.status='completed'
    GROUP BY q.difficulty
""").fetchall()

slow_and_wrong = db.execute("""
    SELECT q.id, q.question_text, tr.time_spent_sec, q.difficulty, t.name as topic
    FROM test_responses tr JOIN questions q ON tr.question_id = q.id
    JOIN topics t ON q.topic_id = t.id
    WHERE tr.is_correct = 0 AND tr.time_spent_sec > 2 * ?
    ORDER BY tr.time_spent_sec DESC LIMIT 10
""", (target_sec,)).fetchall()
```

**Frontend (`templates/analytics.html`):**

Modify the existing `timeTrendChart` to add:
- `annotation` plugin (already registered in some Chart.js builds — check import)
  or just draw a dataset with `borderDash: [5,5]` for the target line.
- Add a second dataset for the 5-point moving average.

Add two new cards below the existing pace chart:
- "Pacing by Difficulty" (horizontal bar chart, colored vs target)
- "Slow & Wrong Questions" (table with link to question edit / review)

### UI mockup — analytics pacing panel

```
┌─── Pace-per-Test ────────────────────────────────────────────┐
│                                                              │
│  120s │                                                      │
│       │              ●                                       │
│   90s │           ●     ●  ●                                 │
│       │       ●                ●                             │
│   72s │─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ (target)   │
│   60s │  ●                          ●    ●●                 │
│       │                                                      │
│   30s │  ────────────────────────────── (5-test MA)          │
│       └──────────────────────────────────                    │
│         T1  T2  T3  T4  T5  T6  T7  T8  T9  T10              │
│                                                              │
│  You are 18% over target pace. Focus on Medium questions —   │
│  see below.                                                  │
└──────────────────────────────────────────────────────────────┘

┌─── Pacing by Difficulty ────────────────────────────────────┐
│                                                             │
│  Easy    ██████ 48s  (target 50s)     ✓                    │
│  Medium  █████████████████ 95s  (target 72s)    over by 32% │
│  Hard    ██████████ 88s   (target 100s)    ✓               │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─── Slow & Wrong (top 10) ───────────────────────────────────┐
│  Q#   Topic       Time      Difficulty                       │
│  1421 DBMS       210s   ▓▓▓▓  hard                           │
│  1103 Networks   198s   ▓▓▓▓  medium  ← medium@198s is a red flag │
│  ...                                                         │
└──────────────────────────────────────────────────────────────┘
```

### Effort
- Backend queries: 1.5 h
- Chart enhancements (target line + MA): 1.5 h
- New difficulty-pacing card: 1 h
- "Slow & Wrong" table: 1 h
- **Total: 5 h**

---

## Cross-cutting: JS budget & library choice

Current: `static/script.js` is 145 lines. `analytics.html` already loads
Chart.js 4.4.0 (~200 KB) from CDN.

**Recommendation: keep Chart.js on analytics only, do not add other libraries.**
Everything on the dashboard should be pure server-rendered HTML + CSS. The
consistency strip, mastery tiles, and next-topic card don't need JS. This keeps
the dashboard fast on mobile and avoids a chart flash-of-empty on load.

Do not add:
- Alpine.js / htmx (nothing here needs client-side interactivity beyond a
  single settings-save fetch, which already works)
- D3 (Chart.js covers our needs)
- A CSS framework (we have design tokens already)

If we ever need SVG rings/gauges, hand-roll them in ~30 lines of SVG rather
than pulling in another library.

---

## Cross-cutting: routes

**Prefer extending, not creating.** Everything above can live on the existing
`/` and `/analytics` routes. Reasons:

- Solo user, no navigation load. Extra pages fragment the mental model.
- Server-render cost is negligible at this scale.
- If a section gets too heavy, split it later with an HTMX-style include, not
  a new URL.

The only new endpoint that might make sense:

- `POST /api/dismiss_recommendation` — user says "not this topic today, show me the next one". Stores `dismissed_at` in session (not DB, since it's a UX preference for the current visit).

Skip this unless usage shows users don't trust the top-1 recommendation.

---

## Cross-cutting: Turso schema application

Per [plan 00 tech-debt](00-tech-debt.md), `db.py`'s `SCHEMA` string is never
actually executed against Turso for paths containing "exam_prep" — `turso_patch`
routes them to the HTTP endpoint but the CREATE TABLE from `SCHEMA` is
`CREATE TABLE IF NOT EXISTS`, and the Turso tables were seeded from a different
script and are missing columns from `SCHEMA`.

**Practical implication for this plan:** we don't need schema changes for
features 1, 3, or 4. For feature 2 (consistency score) we only add a settings
row, which uses INSERT OR IGNORE and works fine.

If we later want a `topic_mastery.last_7d_activity` or similar, we must:
1. Add the column to `db.py`'s SCHEMA (for local dev / future deployments).
2. Run `ALTER TABLE` explicitly against Turso.
3. Verify with `PRAGMA table_info(topic_mastery)`.

This is spelled out fully in plan 00; not repeated here.

---

## Rollout order & dependencies

```
  ┌─────────────────────┐
  │ 1. Mastery grid     │  no deps, ~3 h
  └──────────┬──────────┘
             │
  ┌──────────▼──────────┐
  │ 3. Next-weak topic  │  reuses tile styles, ~4 h
  └──────────┬──────────┘
             │
  ┌──────────▼──────────┐
  │ 2. Consistency score │  independent, ~4 h
  └──────────┬──────────┘
             │
  ┌──────────▼──────────┐
  │ 4. Pacing benchmarks │  needs ≥5 completed tests to be useful, ~5 h
  └─────────────────────┘

Total: ~16 h. Recommended cadence: one feature per evening.
```

Feature 1 unblocks 3 (both use the tile visual). Do them in the same PR.
Feature 2 is independent and could ship earlier if you want an emotional win.
Feature 4 depends on enough test history to draw a moving average; hold it
until Kartik has done ≥5 tests post-launch of the new dashboard.

---

## Checklist (tick when done)

### Feature 1 — Topic-mastery grid
- [ ] Backend query includes tier/days_since computed columns
- [ ] Dashboard template shows grid of tiles (weak-first sort)
- [ ] Analytics template shows same grid, grouped by paper
- [ ] Legend for 4 tiers rendered
- [ ] CSS `mastery-grid`, `topic-tile`, `weight-badge` classes added
- [ ] Empty state (all topics untested) works
- [ ] Mobile responsive at <480 px (auto-fill grid should handle)

### Feature 2 — Consistency score
- [ ] `active_days` and `consistency_score` query added to `bp_main.py`
- [ ] `activity_28d` list generated (last 28 days incl. today)
- [ ] Hero card rendered on dashboard
- [ ] 28-cell activity strip renders correctly
- [ ] Copy is neutral (no "streak broken" language)
- [ ] `settings.daily_goal_min` respected (default 30 min = counts if ≥10 min)
- [ ] Empty state (no activity) renders `0% · 0/20 days`

### Feature 3 — Next weak topic
- [ ] `_rank_next_topic(db)` helper implemented
- [ ] Returns top-3 with reasoning strings
- [ ] Handles empty DB, all-mastered, all-untested states
- [ ] Reasoning string shows "up to +N exam points" phrasing
- [ ] Dashboard card + "See top 3" collapsible
- [ ] Manual test: weak-DBMS beats weak-IoT
- [ ] Manual test: recently-studied topic gets deprioritized

### Feature 4 — Pacing benchmarks
- [ ] `target_seconds_per_q` seeded in settings (default 72)
- [ ] `recent_pace`, `pace_by_difficulty`, `slow_and_wrong` queries added
- [ ] Target line rendered on `timeTrendChart`
- [ ] 5-point moving-average dataset added
- [ ] "Pacing by Difficulty" bar chart card added
- [ ] "Slow & Wrong (top 10)" table card added
- [ ] Empty state (no test responses) renders gracefully
- [ ] Target-line color logic (red/amber/green) implemented

### Cross-cutting
- [ ] No new JS libraries added (Chart.js only, on analytics only)
- [ ] Any new settings rows use `INSERT OR IGNORE`
- [ ] No new `disabled` / `updated_at` columns assumed to exist on `questions`
- [ ] All template changes tested with `flask run` locally
- [ ] Screenshot the dashboard before + after — should look calmer, not busier

---

## Out of scope for this plan (deliberately)

- **Achievements / badges** — gamification is easy to over-do and hard to remove. Skip.
- **Social features / leaderboards** — solo user, N/A.
- **Deep per-question analytics** (heatmap of correct/wrong per question) — covered by error log; don't duplicate.
- **Predictive exam-day score** — needs a validated model; do not fake it. If we ship a "predicted score" it must be defensible.
- **Study-plan generation** (weekly schedule) — separate feature, worth its own plan.

---

## Notes for cross-plan integration

- **PYQ filter (plan A)** should also surface on the "Next weak topic" card as a
  toggle: "Practice this topic — PYQ only" vs "Practice this topic — all questions".
- **Spaced repetition (plan A)** will replace the naive `error_log` recent-errors
  section on the dashboard once shipped. Both plans should agree on the schema.
- **Test-taking UX (plan B)** — the question palette will show per-question time
  during the test; those values are the same `time_spent_sec` we aggregate here.
- **Tech debt (plan 00)** — the `turso_patch` silent-failure fix must ship before
  any of these features, since adding a settings row now would fail silently if
  the settings table drifts. Verified today that settings works, but keep this in
  mind for feature 4's `target_seconds_per_q`.

---

## Open questions

1. Should the mastery grid also show Paper I topics on the dashboard, or only Paper II? Kartik's exam has both, but Paper II is the CS focus. **Recommendation:** dashboard shows only the paper with the nearest test date (or defaulting to Paper II); analytics shows both grouped.
2. What's the definitive "target seconds per question" for BCI? The paper is 100 Q in 120 min = 72 s. But some Qs (matching, prefix expressions) genuinely need 90 s+. **Recommendation:** keep 72 s as default; expose in settings.
3. Should we auto-refresh the "next weak topic" recommendation daily? **Recommendation:** no — it changes every time a test is submitted, which is enough. Auto-refresh would make it feel like a slot machine.
