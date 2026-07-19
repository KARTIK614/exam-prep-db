# Plan A — Study Effectiveness Features

**Status:** Proposal — planning only, no implementation.
**Scope:** Four features that make studying *more effective per minute spent*, as opposed to Plan C which makes the dashboard *more useful per glance*.

1. **Spaced repetition on wrong answers** — extend `error_log` with SR scheduling so review timing is optimised, not manual.
2. **Weakness heatmap** — topic × difficulty × recency matrix on Analytics.
3. **PYQ filter** — parse messy `questions.source` strings; expose year / exam-body as filters on Test Setup and Analytics.
4. **Bookmarks / starred questions** — new schema, new UX for "come back to this later".

**Author:** research fork, 2026-07-17.
**Assumes:** Plan 00 (tech-debt: `questions.disabled` + `updated_at` ALTERs, Turso silent-failure fix) has landed. Plan C (dashboard + mastery grid + consistency score) is written but may or may not have shipped by execution time — this plan is designed to compose either way.

---

## 0. Quick-win first sprint (read this first)

Biggest immediate lift for least code — ship these three in one PR:

| # | Change | Effort | Why it wins |
|---|--------|--------|-------------|
| 1 | **Bookmarks: star button on `test.html` + `bookmarks` table + `/bookmarks` list route** | 3.5 h | Zero-risk new table, no interaction with scoring code. The "come back to this" escape hatch you notice missing every test. Immediate emotional payoff. |
| 2 | **PYQ filter: backfill `question_sources` normalisation + `pyq_only` checkbox on `/test/setup`** | 4.5 h | The most-asked-for question filter. Backfill is pure Python regex on `source`, no risk to `questions` itself. |
| 3 | **Leitner review queue: `sr_box` + `sr_due_at` columns on `error_log` + `/review` route** | 5.5 h | Spaced-repetition value without SM-2/FSRS complexity. "Cards due today" number Kartik can chase. DB shape supports swapping the algorithm later. |

**First-sprint total ~13.5 h. Skip the weakness heatmap until sprint 2** — highest-effort feature (~7 h) and depends on ≥20 tests to be meaningful. The three above give three visible new capabilities in a weekend.

---

**Contents:** F1 SR · F2 heatmap · F3 PYQ · F4 bookmarks · cross-cutting · rollout · open questions · appendices.

---

## Feature 1 — Spaced repetition on wrong answers

### 1.1 Current state (grounded in code)

- `error_log` (`db.py:45-52`) tracks every wrong answer: `test_id, question_id, topic_id, selected_option, correct_option, error_type, root_cause, resolved, created_at, redo_1_score, redo_2_score`.
- `bp_tests.py:128-134` inserts one row per wrong response in `finish()` — single write path.
- `bp_errorlog.py` renders `/errorlog` with filters + per-row R1/R2 redo buttons wired to `POST /api/redo_error` (`bp_api.py:107-114`).
- **Nothing schedules reviews.** Redo is manual and unbounded — same-day or three-weeks-later, no signal about which is right.

### 1.2 Competitor scan

| Product | Algorithm | UX pattern | Steal this | Skip |
|---------|-----------|------------|------------|------|
| **Anki** | SM-2 (default); optionally FSRS since 23.10 | "N cards due today"; grade recall 1-4 (Again / Hard / Good / Easy) after each card | The daily-queue framing ("N due"), the 4-button grading vocabulary (map to our `redo_score`) | The full SM-2 ease-factor storage (5+ columns per card); Anki's back-of-card timer stats |
| **SuperMemo** | SM-17 (proprietary), evolves the item-difficulty estimate over time | Adaptive interval + retention target | Nothing directly — algorithm is closed and tuned for lifelong-learning contexts | Everything else. Genuine overkill. |
| **Quizlet** | Leitner-style 5 boxes ("Learn" mode) | Progress bar per set; auto-shuffle within box | The 5-box mental model — easy for one user to reason about | Their spaced repetition is buried behind a paywall (Quizlet Plus) and lacks a fixed exam-date mode |
| **RemNote** | FSRS + optional SM-2 | Cards inline in notes; queue emerges from tag hierarchy | Nothing structural here — we're not a note app | Their tight coupling with note graph — we have topics, not notes |
| **Testbook / Adda247** | No true SR; "revise wrong questions" is a one-shot bucket, not scheduled | "Mistake bank" tab, revisit anytime | The naming — "Mistake Bank" reads better than "Error Log" for a review context | Their non-algorithm approach — that's exactly the gap we're closing |
| **Oliveboard** | No SR; per-test "Review incorrect" only | Bookmarking within a mock test | Nothing new — we already have `error_log` per-test | Same as Testbook — no scheduling |

**Takeaways:** Indian exam-prep sites don't do real SR — a differentiator. Anki is the reference but its full data model is too heavy for us; we just need one interval + due-date column. Steal the "N cards due today" phrasing — it's the vocab that works.

### 1.3 Design decision — Leitner vs SM-2 vs FSRS

For a solo user with a fixed exam date (say 90–180 days out), the design constraints are different from Anki's typical "lifelong learner". Compare:

| Property | Leitner (5-box) | SM-2 | FSRS (v4) |
|----------|-----------------|------|-----------|
| **Storage per item** | 1 int (box #) + 1 date (last review) | 3 floats (ease, interval, reps) + date | ~5 floats (stability, difficulty, R, retrievability) + date + full review log |
| **Algorithm complexity** | Trivial: correct → box+1, wrong → box=1 | Moderate: `EF' = EF + (0.1 - (5-q)*(0.08 + (5-q)*0.02))` etc. — 4 branches | High: 17 tuned parameters, requires review-history log to compute stability at each step |
| **Explainability to the user** | Very high: "you got box 3 → next review in 5 days" | Medium: interval math is opaque | Low: interval is a function of hidden stability |
| **Handles fixed exam date** | Yes trivially: cap boxes at 5, freeze after box 5, add a "cram all boxes" mode in exam week | Poorly: SM-2 intervals grow unbounded (Anki caps at 100 y). You'd have to hard-cap. | Poorly natively, but FSRS 4.5+ has a `desired_retention_at_deadline` — needs configuration |
| **Handles first-day cold start** | Yes — every wrong answer starts at box 1 | Yes | Poorly — FSRS needs ~1000 reviews to tune parameters. Cold start defaults to SM-2 equivalent. |
| **Cost of getting it wrong** | Low — worst case the user reviews slightly too often. Waste minutes, not months. | Medium — a mis-tuned ease factor cascades. Anki forums are full of "my ease factor collapsed" horror stories. | Medium — bad parameters silently drift review intervals |
| **Migration path if we pick wrong** | Trivial — box # can be re-derived from `redo_score` history | Painful — the ease factor is a hidden state that never gets rebuilt correctly | Painful for same reason |
| **Fit for our data volume** | Perfect — we have hundreds to low thousands of wrong-answers, not millions | Slight overkill | Massive overkill |

**Recommendation: Leitner-5, with a graceful upgrade path to SM-2 if we ever need it.**

Reasoning for Kartik's context:

1. **Fixed exam date changes the objective.** Anki is optimised for indefinite retention; Kartik needs peak retention on one specific day. Leitner supports a trivial "collapse all boxes daily during exam week" mode.
2. **Cold start.** ~50 errors after first diagnostic. FSRS needs ~1000 reviews to beat SM-2; SM-2 needs ~50 to beat Leitner. At his volume Leitner is at the sweet spot.
3. **Explainability = trust.** "Next review in 5 days because box 3" is trusted; "because stability=2.3 × R=0.8" gets the feature disabled.
4. **Maintainability.** Leitner ~40 lines; SM-2 ~120 lines with subtle branches; FSRS a whole submodule. Solo dev.
5. **Reversible.** Leitner columns are a strict subset of what SM-2/FSRS would need. We can add `sr_ease` and `sr_interval` later without breaking existing writes.

### 1.4 Leitner schedule constants

Standard 5-box intervals, tuned for a 6-month exam runway:

| Box | Interval (days) if answered correctly | On wrong answer |
|-----|----------------------------------------|-----------------|
| 1   | 1 day                                  | stays at box 1  |
| 2   | 3 days                                 | drop to box 1   |
| 3   | 7 days                                 | drop to box 1   |
| 4   | 14 days                                | drop to box 2   |
| 5   | 30 days (retired — "mastered")         | drop to box 3   |

The "drop-to-3" instead of "drop-to-1" for box 5 is a pragmatic softening — a box-5 miss usually means momentary lapse, not full concept collapse. Anki does the equivalent with its "hard" grade.

**Exam-week override (optional, ship later):** if `days_until_exam <= 14`, review every card daily regardless of box. Add a `settings.exam_date` field to drive this.

### 1.5 Schema changes

`error_log` already exists. Add three columns:

```sql
-- New columns on error_log
ALTER TABLE error_log ADD COLUMN sr_box INTEGER DEFAULT 1;
ALTER TABLE error_log ADD COLUMN sr_due_at TEXT;       -- ISO date, next review
ALTER TABLE error_log ADD COLUMN sr_last_reviewed TEXT; -- ISO datetime
```

**Add to `db.py:_run_alter_migrations` list:**

```python
migrations = [
    "ALTER TABLE questions ADD COLUMN disabled INTEGER DEFAULT 0",
    "ALTER TABLE questions ADD COLUMN updated_at TEXT",
    "ALTER TABLE error_log ADD COLUMN sr_box INTEGER DEFAULT 1",
    "ALTER TABLE error_log ADD COLUMN sr_due_at TEXT",
    "ALTER TABLE error_log ADD COLUMN sr_last_reviewed TEXT",
]
```

**Backfill for existing rows:**

```sql
UPDATE error_log SET sr_box = 1,
    sr_due_at = date(COALESCE(created_at, 'now'), '+1 day')
WHERE sr_due_at IS NULL;
-- Then advance rows with existing redo data to smoother starting positions:
UPDATE error_log SET sr_box=2, sr_due_at=date('now','+3 days') WHERE redo_1_score = 1;
UPDATE error_log SET sr_box=3, sr_due_at=date('now','+7 days') WHERE redo_2_score = 1;
```

No changes to `test_responses`, `questions`, `topic_mastery`, or `mock_tests`. Zero conflict with Plan C's mastery grid — that uses `topic_mastery`, this uses `error_log`.

### 1.6 Backend

**New route** (bp_errorlog.py or a new bp_review.py — recommend the latter for URL clarity):

```
GET  /review              — the daily-queue page: shows all errors where sr_due_at <= today
POST /api/review_answer   — user submits correct/wrong for one review card; server advances box + due date
```

**Helper functions** (put in `db.py` or a new `sr.py` module — I'd add `sr.py` because it's testable in isolation):

```python
# sr.py — Leitner-5 scheduling primitives
BOX_INTERVALS_DAYS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
DROP_ON_MISS = {1: 1, 2: 1, 3: 1, 4: 2, 5: 3}

def next_box(current_box: int, was_correct: bool) -> int:
    return min(5, current_box + 1) if was_correct else DROP_ON_MISS.get(current_box, 1)

def next_due(box: int, from_date=None) -> str:
    from_date = from_date or datetime.now().date()
    return (from_date + timedelta(days=BOX_INTERVALS_DAYS[box])).isoformat()

def get_due_reviews(db, limit: int = 50):
    """Errors due today or earlier, oldest-due first. Join questions + topics for display."""
    return db.execute("""
        SELECT el.*, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
               q.correct_option, q.explanation, t.name AS topic_name
        FROM error_log el
        JOIN questions q ON el.question_id = q.id
        JOIN topics t ON el.topic_id = t.id
        WHERE (q.disabled IS NULL OR q.disabled = 0)
          AND date(el.sr_due_at) <= date('now')
        ORDER BY el.sr_due_at ASC, el.sr_box ASC
        LIMIT ?
    """, (limit,)).fetchall()

def record_review(db, error_id: int, was_correct: bool):
    row = db.execute("SELECT sr_box FROM error_log WHERE id=?", (error_id,)).fetchone()
    if row is None: return None
    new_box = next_box(row["sr_box"] or 1, was_correct)
    new_due = next_due(new_box)
    db.execute("UPDATE error_log SET sr_box=?, sr_due_at=?, sr_last_reviewed=? WHERE id=?",
               (new_box, new_due, datetime.now().isoformat(), error_id))
    db.commit()
    return {"new_box": new_box, "next_due": new_due}
```

**Test hook** — `tests/test_sr.py` asserts each box transition (correct + miss), that `next_due(2)` is 3 days ahead, and a temp-sqlite round-trip.

**Cross-write from `bp_tests.py:finish()`** — extend the existing INSERT to set `sr_box=1, sr_due_at=date('now','+1 day')` explicitly (2 columns, 1 line change). Keeps the read query simple (no COALESCE needed).

### 1.7 Frontend

**New template `templates/review.html`** — served by `/review`. Simpler than `test.html` (no timer, no navigator): header ("Review Queue — N due today"), one-card-at-a-time question rendering, options as buttons, and after answer a reveal panel with two big buttons (`Got it — box N+1, review in X days` / `Missed — box 1, review tomorrow`). Progress: `Card 3 of 27`.

**Modify `templates/errorlog.html`** — Review Queue summary card at top:

```
┌── Review Queue ─────────────────────────────┐
│  27 cards due today   [ Start review ]      │
│  Box 1: 12  Box 2: 8  Box 3: 5  Box 4: 2  Box 5: 0│
└─────────────────────────────────────────────┘
```

The box-distribution row is the diagnostic. Most cards in box 1-2 → not retaining. Cards clustered in box 4-5 → mastering.

**Modify `templates/index.html`** — add `<a href="/review" class="pill">📚 N due today</a>` pill (backend adds `sr_due_today = SELECT COUNT(*) FROM error_log WHERE date(sr_due_at) <= date('now')`).

**JS** — new page needs one fetch to `/api/review_answer` (cleaner than reusing `submit_answer`). ~20 lines total.

### 1.8 Interaction with existing tables

| Table          | Read? | Write? | Notes |
|----------------|-------|--------|-------|
| `error_log`    | Y     | Y      | Adds sr_box, sr_due_at, sr_last_reviewed. Existing `redo_1_score` / `redo_2_score` become vestigial — keep them, don't remove. |
| `questions`    | Y     | N      | Standard join for question_text / options / explanation. Filter `disabled=0`. |
| `topics`       | Y     | N      | Standard join for topic_name display. |
| `test_responses` | N   | N      | SR reviews are outside a test — do not create test_responses rows. |
| `topic_mastery` | N    | N      | SR does not touch mastery. Deliberate: mastery is a global proficiency signal driven by full tests; SR is a per-item recall signal. Mixing them would double-count. |

### 1.9 UI mockup — `/review` page

```
┌────────────────────────────────────────────────┐
│  Review Queue · Card 3 of 27                   │
│  Box 2 · Last seen 3 days ago                  │
│                                                │
│  Topic: DBMS & SQL      Difficulty: hard       │
│                                                │
│  Q: A relation in which every non-key attr...  │
│    [ A. 5NF ] [ B. 3NF ] [ C. 4NF ] [ D. BCNF ]│
│  ─────────────────────────────                 │
│  ✓ Correct: B. 3NF                             │
│  3NF: in 2NF + no transitive dependency.       │
│                                                │
│  [ Missed — box 1, review tomorrow ]           │
│  [ Got it — box 3, review in 7 days ]          │
└────────────────────────────────────────────────┘
```

The two big buttons after reveal are the whole UX. Interval text on each button is the trust-builder — user sees *before* clicking what the choice means for their schedule.

### 1.10 Effort estimate

| Task | Hours |
|------|-------|
| `sr.py` module + unit tests | 1.5 |
| `db.py` migration additions + backfill script | 0.5 |
| New `bp_review.py` blueprint + `/review` + `/api/review_answer` | 1.5 |
| `templates/review.html` | 1.5 |
| `errorlog.html` header card + `index.html` badge | 0.5 |
| Manual verification (seed 10 fake errors, run through a review cycle) | 0.5 |
| **Total** | **6 h** |

Note: quick-win-first-sprint version cuts the errorlog header, the dashboard badge, and the tests to hit **5.5 h**. Ship that first, add the polish in a follow-up.

---

## Feature 2 — Weakness heatmap (topic × difficulty × recency)

### 2.1 Current state

- `bp_analytics.py:61-69` already builds a 30-day *activity* heatmap (tests taken per day). Rendered in `analytics.html:92-107`.
- `bp_analytics.py:51-59` builds a global `difficulty_stats` (correct/total by easy/medium/hard).
- Nothing shows the **intersection**: "am I weak at *hard* questions on *DBMS* that I *haven't seen in 3 weeks*?" That intersection is where the exam-day risk lives.

### 2.2 Competitor scan

| Product | Heatmap UI | Steal | Skip |
|---------|-----------|-------|------|
| **Anki** | Retention-per-tag matrix (in "Card Info" and third-party addons like "Anki Stats") | Two-axis coloring, hover for details | The tag-based topic hierarchy — we have flat topics |
| **RemNote** | Retention heatmap by tag | Same as Anki | Same as Anki |
| **Khan Academy** | Skill × grade level matrix on parent dashboard | Multi-dimensional visualization at all | Their "grade level" concept doesn't map |
| **Testbook** | Topic × accuracy % table (single-axis, boring) | The topic-list layout | The single-axis flatness |
| **Adda247** | Same as Testbook, plus rank comparisons | Nothing | Peer comparisons — solo user |
| **Oliveboard** | Topic × section × mock-test grid | The grid density | Too many columns; overwhelms |

**GitHub contribution graph** is the reference: dense 2D grid with color as the third dimension. Maps cleanly to topic × difficulty × accuracy or topic × recency × accuracy — pick one for default, toggle the other.

### 2.3 Design decision

Two heatmaps, one page, one toggle:

**Heatmap A — Topic × Difficulty (primary)**
- Rows: attempted topics, weightage DESC.
- Cols: easy / medium / hard.
- Cell: accuracy %. Colors: red <50, amber 50-74, green ≥75, gray untested. Hover: `N correct / M attempted · last seen X days ago`.
- Signal: *"82% on medium DBMS but 34% on hard DBMS → study DBMS by difficulty, not by topic."*

**Heatmap B — Topic × Recency (toggle)**
- Rows: same topics.
- Cols: `0-7d`, `8-14d`, `15-30d`, `>30d`.
- Cell: accuracy % in that time bucket. Same color scale.
- Signal: *"Networks 85% recent vs 55% >30d → you're forgetting Networks."* Aggregate view of what SR handles per-question.

Do NOT build a 3D heatmap. Two 2D views with a toggle are strictly better than one unreadable grid.

### 2.4 Cross-plan alignment with Plan C

Plan C introduces:
- `mastery-grid` on dashboard + analytics (`topic_mastery.current_score` per topic tile, tiered by weak / on-track / mastered).
- Consistency score with 28-day activity strip.

**The heatmap is different from the mastery grid**, deliberately:
- Mastery grid answers "how much do I know each topic?" — one number per topic, current, EMA-smoothed.
- Heatmap answers "where inside each topic are the holes?" — two-dimensional breakdown.

**Placement recommendation:** the heatmap goes **below** the mastery grid on analytics, not on the dashboard. Dashboard stays fast + minimal (per plan C). If a user wants to drill down after seeing a weak topic on the grid, the heatmap gives them the row-level detail on the same page.

### 2.5 Schema changes

**None.** Everything is a query over `test_responses` + `questions` + `topics`.

The only mild concern is query performance if we ever have 100 K responses. At current scale (thousands) it's a non-issue. Add an index later if needed:

```sql
-- Optional, for future scale
CREATE INDEX IF NOT EXISTS idx_tr_qid ON test_responses(question_id);
CREATE INDEX IF NOT EXISTS idx_q_topic_diff ON questions(topic_id, difficulty);
```

### 2.6 Backend

Two new queries in `bp_analytics.py:dashboard()`, both `GROUP BY topic × <axis>`:

```python
# Heatmap A — topic × difficulty
heatmap_diff = db.execute("""
    SELECT t.id AS topic_id, t.name AS topic_name, t.weightage, q.difficulty,
           COUNT(*) AS attempted, SUM(tr.is_correct) AS correct
    FROM test_responses tr
    JOIN questions q ON tr.question_id = q.id
    JOIN topics t ON q.topic_id = t.id
    WHERE (q.disabled IS NULL OR q.disabled = 0)
    GROUP BY t.id, q.difficulty
""").fetchall()

# Heatmap B — topic × recency (buckets 0-7 / 8-14 / 15-30 / 30+ days)
heatmap_recency = db.execute("""
    SELECT t.id AS topic_id, t.name AS topic_name, t.weightage,
           CASE
             WHEN julianday('now') - julianday(mt.completed_at) <= 7  THEN '0-7'
             WHEN julianday('now') - julianday(mt.completed_at) <= 14 THEN '8-14'
             WHEN julianday('now') - julianday(mt.completed_at) <= 30 THEN '15-30'
             ELSE '30+' END AS bucket,
           COUNT(*) AS attempted, SUM(tr.is_correct) AS correct
    FROM test_responses tr
    JOIN mock_tests mt ON tr.test_id = mt.id
    JOIN questions q ON tr.question_id = q.id
    JOIN topics t ON q.topic_id = t.id
    WHERE mt.status='completed' AND (q.disabled IS NULL OR q.disabled = 0)
    GROUP BY t.id, bucket
""").fetchall()
```

Reshape in Python into `{topic_id: {name, weightage, cells: {axis_value: {attempted, correct, accuracy}}}}` then sort by (weightage DESC, name ASC). Pass to template.

### 2.7 Frontend

New card in `analytics.html` below the mastery grid: header with `Weakness Heatmap` + segmented `[By Difficulty][By Recency]` toggle, body containing two Jinja-rendered `.heatmap-2d` divs (one shown, one `display:none`), plus a legend row.

CSS adds `.heatmap-2d` (grid: `200px repeat(3, 1fr)`, gap 4px), `.cell.acc-red/amber/green/empty` (matching existing `--danger/warning/success/border` tokens), and `.segmented-toggle` (inline-flex, active state uses `--primary`).

JS is 10 lines: click handler on the toggle buttons that swaps `display: grid` / `display: none` on the two grid divs. No Chart.js.

### 2.8 UI mockup

```
┌─── Weakness Heatmap ─────── [ By Difficulty ] [ By Recency ] ─┐
│                                                                │
│  Topic (weight)          Easy     Medium    Hard               │
│  ───────────────────    ──────   ──────   ──────               │
│  DBMS & SQL     (10)    ▮ 89%    ▮ 71%    ▮ 34%                │
│  Comp Fund      (10)    ▮ 76%    ▮ 55%    ░  —                 │
│  Data Struct    ( 8)    ▮ 82%    ▮ 63%    ▮ 45%                │
│  Networks       ( 8)    ▮ 91%    ▮ 78%    ▮ 62%                │
│  Operating Sys  ( 8)    ░  —     ▮ 44%    ▮ 28%                │
│  SAD            ( 4)    ▮ 88%    ▮ 60%    ░  —                 │
│                                                                │
│  Legend: ▮<50   ▮50–74   ▮≥75   ░untested                     │
│                                                                │
│  Insight: "Hard-difficulty DBMS + hard-difficulty OS are your  │
│  two biggest exam-day risks. That's 18 points at stake."       │
└────────────────────────────────────────────────────────────────┘
```

The "Insight" strip at the bottom is optional but powerful — it's a computed sentence that names the two lowest-accuracy × highest-weightage cells. Formula:

```python
risk_score = (100 - accuracy) * weightage
# top two by risk_score → insight sentence
```

Ship the grid first, add the insight strip only if there's obvious appetite.

### 2.9 Effort estimate

| Task | Hours |
|------|-------|
| Two queries + Python reshape | 1.5 |
| Template markup for both grids | 1.5 |
| CSS for cells + toggle | 1.0 |
| JS toggle (10 lines) | 0.25 |
| Insight strip (computed sentence + template) | 1.0 |
| Empty-state / no-data handling | 0.5 |
| Testing across 0 / 5 / 50 responses | 0.75 |
| **Total** | **6.5 h** (round to 7 h) |

---

## Feature 3 — PYQ filter (year / exam-body / source-normalisation)

### 3.1 Current state — the mess

Sample of unique `source` values from `data/extracted_questions/*.json` — ~210 distinct non-null strings across ~2500 questions (~40% are null):

```
BCI 18 June 2022 Q13
PYQ RPSC Programmer 27.10.2024 Paper-I
Raj. Basic Computer Instructor 18.06.2022
Basic Computer Instructor 18-06-2022
PYQ Raj IA 2013 / Raj. IA Exam 2013 / Informatics Assistant - 2013
CET 10+2, 22.10.24 (1st Shift)
GATE CS 2014 / ISRO CS
UGC NET Dec 2005 / ISRO CS 2011
DSSSB-PGT-2018 (Male)
null                          ← ~40% of questions
```

Problems:
1. **Same exam, 5 spellings.** BCI = Basic Computer Instructor = Raj. Basic Computer Instructor = ... all 2022-06-18.
2. **Multi-source strings.** `"GATE CS 2014 / ISRO CS"` — one question shared by two exams; need both indexed.
3. **Dates in 4+ formats:** `18 June 2022`, `18.06.2022`, `18-06-2022`, `2022-06-18`. Year usually recoverable; day+month sometimes not.
4. **Free-form suffixes:** `Q13`, `(1st Shift)`, `(IInd Shift)`, `Paper-I`, `(Male)`, `(Batch-01)`.
5. **~40% null** — textbook questions with no provenance. Must remain filterable (a "PYQ only" toggle should hide them).

Filtering by `LIKE '%2022%'` on `source` is fragile. Need normalisation into a side table.

### 3.2 Competitor scan

| Product | Filter UX | Steal | Skip |
|---------|-----------|-------|------|
| **Testbook** | Year dropdown + exam dropdown, both single-select | Two-column filter layout | Their filters ignore multi-source (a question tagged "GATE + ISRO" appears under either, not both) |
| **Adda247** | "Previous Year Questions" is a whole separate section, not a filter | The dedicated "PYQ" landing chip | Fragmentation — we want inline filtering |
| **Oliveboard** | Year + exam multiselect | Multiselect | Their year list is populated manually per exam — brittle |
| **PrepInsta** | Free-text search over questions, no structured filter | Nothing | Search is not filter |
| **GateOverflow** | Tag-based filtering (per-year tags manually curated) | Tag concept is right, but manual curation is out | The mailing-list-era tagging tools |
| **Anki** | Deck / tag filter | Tag concept | Their tag hierarchy tooling |

**Takeaway:** none of these handle multi-source strings correctly. Expanding `"GATE CS 2014 / ISRO CS"` into two searchable rows is a differentiator.

### 3.3 Design decision

Two-table schema:

- **`question_sources`** — a normalised many-to-many: one row per (question × exam × year). One question can have N rows.
- **`exams`** — a lookup of canonical exam bodies (BCI, GATE-CS, ISRO-CS, UGC-NET, DSSSB, CET-Rajasthan, etc.).

The raw `questions.source` text stays. It's the ground truth; normalisation is a projection.

Filtering becomes:
```sql
SELECT DISTINCT q.* FROM questions q
JOIN question_sources qs ON qs.question_id = q.id
WHERE qs.exam_code = 'BCI' AND qs.exam_year = 2022;
```

Fast, indexable, and handles multi-source correctly.

### 3.4 Schema changes

```sql
CREATE TABLE IF NOT EXISTS exams (
    code TEXT PRIMARY KEY,            -- 'BCI', 'GATE-CS', 'RPSC-PROG', 'UGC-NET', ...
    name TEXT NOT NULL,               -- 'Basic Computer Instructor'
    body TEXT,                        -- 'RSMSSB', 'IIT/IISc', 'UPSC', 'NTA'
    scope TEXT DEFAULT 'national'     -- 'national' | 'rajasthan' | 'central-govt'
);

CREATE TABLE IF NOT EXISTS question_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    exam_code TEXT NOT NULL REFERENCES exams(code),
    exam_year INTEGER,                -- nullable when unknown
    exam_date TEXT,                   -- ISO 'YYYY-MM-DD' when known, else null
    shift TEXT,                       -- '1st', 'IInd', null
    paper TEXT,                       -- 'I', 'II', null
    raw_snippet TEXT,                 -- original substring, e.g. "BCI 18 June 2022 Q13"
    UNIQUE(question_id, exam_code, exam_year, shift, paper)
);

CREATE INDEX IF NOT EXISTS idx_qs_exam_year ON question_sources(exam_code, exam_year);
CREATE INDEX IF NOT EXISTS idx_qs_qid ON question_sources(question_id);
```

Seed the `exams` table with ~30 canonical codes covering everything seen in the extracted JSONs. Grouped by scope:

- **Rajasthan (RSMSSB / RPSC):** `BCI`, `RPSC-PROG`, `RAJ-IA`, `CET-RAJ`, `CET-RAJ-12`, `LDC-RAJ`, `PATWAR-RAJ`, `VDO-RAJ`, `JR-ACC-RAJ`, `LIB-RAJ`, `SR-CI-RAJ`, `JR-INST-RAJ`
- **National CS exams:** `GATE-CS` (IIT/IISc), `ISRO-CS`, `UGC-NET` (NTA), `NIELIT`, `NIMCET`, `CUET-PG`
- **Central-govt teachers:** `KVS-PGT`, `NVS-PGT`, `DSSSB-PGT`, `DSSSB-TGT`, `HTET-PGT`
- **Banking / SSC / Rail:** `IBPS-SO`, `SBI-SO`, `SSC-JE-CS`, `SSC-CGL`, `RRB-JE-IT`
- **Other state / PSU:** `UPP-COMP`, `UPPCL`, `BSNL-JE`
- **Catch-all:** `MISC` — for anything the normaliser can't classify. Never drop data.

Each row: `(code, name, body, scope)`, e.g. `('BCI', 'Basic Computer Instructor', 'RSMSSB', 'rajasthan')`. Full seed SQL lives in `scripts/seed_exams.sql`, run once against local + Turso.

Add both tables to `db.py`'s `SCHEMA` string and the `_run_alter_migrations` list won't need entries (these are fresh CREATE TABLEs).

### 3.5 Normalisation strategy

**A backfill script** — `scripts/backfill_question_sources.py` (DB-only, no Turso specifics).

Structure: an ordered regex table matched specifically-first, plus small helpers.

```python
# Sketch — see /appendix A for expected parser outputs
PATTERNS = [
  # BCI variants — most common. Matches "BCI 18 June 2022", "Raj. Basic Computer Instructor 18.06.2022", etc.
  (r'\b(?:PYQ\s+)?(?:Raj\.?\s+)?(?:Basic\s+Computer\s+Instructor|BCI|Raj\s+Basic\s+Instructor)\b', 'BCI'),
  (r'\bRPSC\s+Programmer\b', 'RPSC-PROG'),
  (r'\b(?:PYQ\s+)?(?:Raj\.?\s+|Rajasthan\s+)?(?:Informatics\s+Assistant|\bIA\b)', 'RAJ-IA'),
  (r'\bCET\s+10\+2\b', 'CET-RAJ-12'),
  (r'\bCET\s+(?:Gr\.?\s+Level|Raj\.?|Grad\.?|Exam)', 'CET-RAJ'),
  (r'\bGATE\s+CS\b', 'GATE-CS'),
  (r'\bISRO\s+(?:CS|Scientist|Engineer|Sci)\b', 'ISRO-CS'),
  (r'\bUGC[\s\-]?NET\b', 'UGC-NET'),
  (r'\bKVS\s+PGT\b', 'KVS-PGT'),
  (r'\bDSS?SB[\s\-]PGT\b', 'DSSSB-PGT'),
  (r'\bDSS?SB[\s\-]TGT\b', 'DSSSB-TGT'),
  (r'\bNIELIT\b', 'NIELIT'),
  (r'\bIBPS\s+SO\b', 'IBPS-SO'),
  (r'\bSBI\s+(?:SO|PO)\b', 'SBI-SO'),
  (r'\bSSC\s+(?:JE|CGL|Scientific|IMD)\b', 'SSC-JE-CS'),
  (r'\bRRB\s+(?:JE|NTPC)\b', 'RRB-JE-IT'),
  (r'\bLDC\b', 'LDC-RAJ'),
  (r'\bPatwar\b', 'PATWAR-RAJ'),
  (r'\bVDO\b', 'VDO-RAJ'),
  # ... continue with less-common patterns
]

def parse_source(raw: str) -> list[dict]:
    """Return zero or more dicts of {exam_code, exam_year, exam_date, shift, paper, raw_snippet}."""
    if not raw: return []
    # Split on ' / ' — indicates multi-source. Then match each part against the pattern table.
    # For each match: extract year (any 4-digit 1980-2030 in the part), date (dd.mm.yyyy → ISO),
    # shift ('1st Shift'/'IInd Shift'), paper ('Paper-I' etc.).
    # Unmatched parts → exam_code='MISC', still recorded (never drop data).
    ...

def _extract_year(part):
    m = re.search(r'\b(19[89]\d|20[0-3]\d)\b', part)
    return int(m.group(1)) if m else None

def _extract_date(part):
    m = re.search(r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})', part)
    if not m: return None
    dd, mm, yy = m.groups(); yy = int(yy)
    if yy < 100: yy += 2000
    try: return f"{yy:04d}-{int(mm):02d}-{int(dd):02d}"
    except: return None

def backfill(db_path):
    db = sqlite3.connect(db_path); db.row_factory = sqlite3.Row
    for q in db.execute("SELECT id, source FROM questions WHERE source IS NOT NULL"):
        for p in parse_source(q['source']):
            db.execute("INSERT OR IGNORE INTO question_sources (question_id, exam_code, "
                       "exam_year, exam_date, shift, paper, raw_snippet) VALUES (?,?,?,?,?,?,?)",
                       (q['id'], p['exam_code'], p['exam_year'], p['exam_date'],
                        p['shift'], p['paper'], p['raw_snippet']))
    db.commit()
```

**Two-phase deployment:**
1. Ship the schema + backfill script. Run against local DB. Inspect the `[unmatched]` log — expect ~10-30 stragglers.
2. Hand-add regex patterns for the biggest unmatched clusters. Re-run. Aim for <5% MISC.
3. Ship to Turso (see Cross-cutting §5.2 below) — schema first, then backfill runs remotely.

**Ongoing normalisation** — every new question inserted by `bp_admin.py` (PDF upload flow) should also run `parse_source()` and populate `question_sources`. Hook it in the admin's insert path so the two tables stay in sync.

### 3.6 Backend — filter integration

**Modify `bp_tests.py:setup()`** POST handler — read three new form fields:

```python
pyq_only    = request.form.get("pyq_only") == "on"
exam_codes  = request.form.getlist("exam_codes")            # multi-select
exam_years  = [int(y) for y in request.form.getlist("exam_years") if y.isdigit()]

if pyq_only or exam_codes or exam_years:
    query = query.replace("FROM questions q ",
                          "FROM questions q JOIN question_sources qs ON qs.question_id = q.id ")
    query = query.replace("SELECT q.*, t.name as topic_name",
                          "SELECT DISTINCT q.*, t.name as topic_name")
if exam_codes:
    query += f" AND qs.exam_code IN ({','.join('?' * len(exam_codes))})"
    params.extend(exam_codes)
if exam_years:
    query += f" AND qs.exam_year IN ({','.join('?' * len(exam_years))})"
    params.extend(exam_years)
```

`pyq_only` with no specific code/year = any question that has *any* row in `question_sources`. Also expose to the template: `exams_available` (code, name, question-count via `LEFT JOIN … GROUP BY … HAVING count > 0 ORDER BY count DESC`) and `years_available` (`SELECT DISTINCT exam_year … ORDER BY DESC`).

### 3.7 Frontend — filter widget

Add a `<fieldset>` to `templates/test_setup.html`:
- `<input type="checkbox" name="pyq_only">` — the primary lever.
- `<details><summary>Filter by exam</summary>` collapses a grid of `<label>` chips, one per exam in `exams_available`, showing `name (n_questions)`.
- `<details><summary>Filter by year</summary>` collapses a `<select multiple>` of years from `years_available`.

Same filter belongs on `/errorlog` too (review "wrong answers on GATE 2018") — follow-up, not first sprint.

### 3.8 Interaction with existing tables

| Table              | Read?     | Write?          |
|--------------------|-----------|-----------------|
| `questions`        | Y         | N (existing INSERTs unchanged) |
| `question_sources` | Y         | Y (backfill + new admin uploads) |
| `exams`            | Y         | Y (seeded once) |
| `error_log`        | future — enable PYQ filter on `/errorlog` too | N |
| `test_responses`   | future — analytics "accuracy by exam" | N |

**Cross-plan with Plan C's mastery grid:** the grid doesn't need this — it operates on topic-level aggregates. But the "next weak topic" recommender (plan C §3) could grow a "…on PYQ questions" refinement once this ships. Note it as a follow-up in that plan (as it already does — line 747).

### 3.9 UI mockup — test setup with PYQ filter

```
┌─── Configure Mock Test ────────────────────────┐
│  [existing paper/count/difficulty/focus-weak]  │
│                                                │
│  ── Previous Year Questions ──────             │
│  [x] PYQ only                                  │
│  ▾ Filter by exam                              │
│    [x] BCI (92)     [ ] GATE CS (48)           │
│    [ ] RPSC Prog(18)[ ] ISRO CS  (26)          │
│    [ ] UGC NET (34) [ ] KVS PGT  (22)          │
│    [ ] ... 24 exams total                      │
│  ▾ Filter by year                              │
│    [2024][2023][2022][2021][2020] ...          │
│                                                │
│  [existing Topics multi-select]                │
│  [ Start Test ]                                │
└────────────────────────────────────────────────┘
```

`(N)` counts are queried live from `question_sources` — sets user expectation before submit. If Kartik asks for 100 questions in a slice that only has 92, we auto-cap (existing behaviour, `bp_tests.py:53-54`).

### 3.10 Effort estimate

| Task | Hours |
|------|-------|
| Schema: `exams` + `question_sources` + indexes | 0.25 |
| Seed `exams` table (~30 rows) | 0.25 |
| `backfill_question_sources.py` — patterns + parser | 3.5 |
| Manual regex tuning after first backfill run (iterate 2-3×) | 1.0 |
| Hook parse_source into `bp_admin.py` insert path | 0.5 |
| `bp_tests.setup()` filter integration | 1.0 |
| `test_setup.html` filter widget | 1.0 |
| Verification: run a filtered test end-to-end | 0.5 |
| **Total** | **8 h** |

Quick-win-first-sprint version: skip the multi-select exam picker and the `/errorlog` filter (save ~2 h). Just ship "PYQ only" checkbox + the backfill. That's **~4.5 h** as claimed in §0.

---

## Feature 4 — Bookmarks / starred questions

### 4.1 Current state

None. No "come back to this later" affordance anywhere. Existing saved-question mechanisms are `error_log` (auto-populated on wrong answers) and `question_flags` (bug reports). No `questions.flagged` column exists, and shouldn't — bookmarks are per-user metadata, semantically distinct from question data.

### 4.2 Competitor scan

| Product | Bookmark UX | Steal | Skip |
|---------|-------------|-------|------|
| **Anki** | "Star" flag on card (one of 4 flag colors) | The star icon; per-card single-click | Anki's four-flag system — one color is enough for us |
| **Testbook** | Bookmark within a mock test, view list from side menu | The floating side-menu access | Their bookmark-locked-behind-Pass paywall |
| **Adda247** | Same as Testbook | Same | Same |
| **Oliveboard** | Bookmark + folders | Star icon | Folders — solo user doesn't need |
| **Quizlet** | Star cards ("hard" pile) | Star as the affordance | Their "Starred" study mode is baked in, we'd bolt on |
| **Notion / Obsidian** | Star / favorite at document level | Nothing directly — different domain | Everything else |

**Takeaway:** star icon is the universal affordance. One-tap toggle. Show a count somewhere the user can navigate to.

### 4.3 Design decision

Single table `bookmarks`, single icon on the test/review UI, one list route.

**Skip:** folders (YAGNI, solo user), tags (topics already play that role), per-bookmark notes (fragments the commentary mental model — errors go to `error_log.root_cause`, right answers to `study_sessions.notes`).

**Ship:** bookmark from test + from review queue, dashboard count, topic filter on list view, and — crucial killer feature — **"start test from my bookmarks"**. This lets Kartik build a personal must-know quiz.

### 4.4 Schema changes

```sql
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    user_id INTEGER REFERENCES users(id),   -- nullable for single-user mode
    note TEXT,                              -- reserved; not surfaced in UI v1
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(question_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_bookmarks_qid ON bookmarks(question_id);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id);
```

`user_id` is nullable + defaulted to whatever `g.user` resolves to in `check_auth`. In current single-user deployment, this is fine — we can treat NULL as "the one user" or backfill it once. Since `users` table exists (`db.py:78`), better hygiene to always populate.

Add to `SCHEMA` in `db.py`. No ALTERs — this is a fresh table.

### 4.5 Backend

**New API endpoints (`bp_api.py`):**

- `POST /api/bookmark` — idempotent toggle. Reads `{question_id}`. Looks up existing row by `(question_id, user_id)` → DELETE if present else INSERT. Returns `{status: "added"|"removed", bookmarked: bool}`.
- `GET /api/bookmarks/count` — returns `{count: N}` for the current user (used by the dashboard pill).

**New blueprint `bp_bookmarks.py`:**

- `GET /bookmarks` — renders `bookmarks.html`. Joins `bookmarks → questions → topics`, filters `disabled=0`, honours `?topic=<id>`.
- `POST /bookmarks/start_test` — creates a `mock_tests` row and populates the session with all bookmarked question rows; then `redirect(url_for("tests.take"))`. Reuses the existing test-taking pipeline.

Register in `app.py` alongside other blueprints.

### 4.6 Frontend — the star button

**`templates/test.html`** — inline star link next to the existing "Report issue" link. On click, POST `/api/bookmark`, flip icon `☆ Bookmark` ↔ `★ Bookmarked`.

Fold `bookmarked: bool` into the `/api/question/<idx>` JSON response so we don't need a second fetch per navigation — one-line addition in `bp_api.py:get_question()`.

**`templates/bookmarks.html`** (new) — mirrors `errorlog.html` structure: page header with count + "Start test from bookmarks" button, topic filter card, table of `Topic | Question preview | Difficulty | Bookmarked date | [★ Remove]` rows. Empty state points at the star affordance on the test page.

**Sidebar** — add `<a href="/bookmarks">☆ Bookmarks</a>` to all 6 templates. A sidebar-include refactor is worth doing but out of scope here (see §5.1).

**Dashboard hint** — small `☆ 12 bookmarks` pill next to the `📚 27 due today` SR pill. If Plan C's hero card hasn't shipped, add as a stat-grid card instead.

### 4.7 Interaction with existing tables

| Table              | Read? | Write? |
|--------------------|-------|--------|
| `bookmarks`        | Y     | Y      |
| `questions`        | Y     | N      |
| `topics`           | Y     | N      |
| `users`            | Y (for user_id) | N |
| `error_log`        | N     | N      |
| `test_responses`   | N     | N      |
| `mock_tests`       | Y (only when starting a test-from-bookmarks — creates a new mock_tests row via existing setup logic) | Y (only the new-test creation, unchanged code path) |

### 4.8 UI mockup — bookmarks page

```
┌─── Bookmarks ────────── [ Start test from bookmarks ] ─┐
│  12 saved · Filter: [ All topics ▾ ]                   │
│                                                        │
│  Topic         Question preview          Diff   Saved  │
│  ─────────     ──────────────────────    ────  ──────  │
│  DBMS & SQL    Which is NOT a valid...   hard  Jul 16  │
│  Networks      In a TCP handshake, ...   med   Jul 15  │
│  Data Struct.  Post-order traversal...   hard  Jul 14  │
│  ...                                     [★ Remove ...]│
└────────────────────────────────────────────────────────┘
```

Star on `test.html` — small inline link `☆ Bookmark` next to `⚑ Report issue`. On click, flips to `★ Bookmarked`. Text link (not a button) so it doesn't compete visually with A/B/C/D.

### 4.9 Effort estimate

| Task | Hours |
|------|-------|
| Schema: `bookmarks` table + indexes | 0.25 |
| `bp_bookmarks.py` blueprint + `/bookmarks` route | 0.75 |
| `/api/bookmark` toggle endpoint | 0.5 |
| Extend `/api/question/<idx>` to return `bookmarked` flag | 0.25 |
| `test.html` star button + JS toggle | 0.75 |
| `templates/bookmarks.html` | 1.0 |
| "Start test from bookmarks" route (variant of `bp_tests.setup()`) | 1.0 |
| Sidebar link + dashboard count | 0.25 |
| Manual verification | 0.5 |
| **Total** | **5 h** |

Quick-win-first-sprint version drops the "start test from bookmarks" (save 1 h) and dashboard count (save 0.25 h) — ship just the toggle + list. That's **~3.5 h** as claimed in §0. The "start test" feature is the killer follow-up.

---

## Cross-cutting concerns

### 5.1 Sidebar navigation drift

Every template currently has a hand-copied `<nav class="sidebar-nav">`. Adding `/review` and `/bookmarks` links means editing:

- `templates/index.html`
- `templates/analytics.html`
- `templates/errorlog.html`
- `templates/test.html`
- `templates/test_setup.html`
- `templates/results.html`

Recommend a follow-up: extract to `templates/_sidebar.html` include with an `active` variable. **Out of scope for this plan** but noted so the templates PR is bounded — don't refactor sidebar in the same PR that adds bookmarks.

### 5.2 Turso schema application

Per Plan 00: `db.py`'s `SCHEMA` runs against local sqlite but not Turso. Schema changes here must be applied explicitly:

- **F1 SR:** 3 ALTER TABLEs on `error_log` (via `_run_alter_migrations` + Turso ALTER script).
- **F3 PYQ:** 2 new CREATE TABLEs + `exams` seed data → Turso.
- **F4 Bookmarks:** 1 new CREATE TABLE → Turso.
- **F2 Heatmap:** no schema.

Recommend `scripts/apply_migrations.py` (uses `turso_patch.TC`, idempotent, per-statement logging) — ship alongside Feature 1 and reuse for 3 + 4. Post-Plan-00, silent Hrana failures are fixed so bad columns now raise cleanly.

### 5.3 New blueprints to register in `app.py`

The plan adds two blueprints:
- `bp_review` — Feature 1
- `bp_bookmarks` — Feature 4

Register in `app.py` alongside existing ones. No URL prefix — routes are top-level `/review`, `/bookmarks`.

### 5.4 Rollback

All four features are additive and independently revertable. New tables and columns are nullable / defaulted; unregistering a blueprint or reverting a template change removes the feature without data loss. No plan feature drops or renames columns.

### 5.5 JS budget

Plan C committed to no new JS libraries; this plan honours that. Approximate new JS: SR ~20 lines, heatmap toggle ~10, PYQ filter 0 (form submit), bookmarks ~25. Total ~55 lines — `static/script.js` grows from 145 to ~200. Still small, still framework-free.

### 5.6 Testing

Add to `tests/`:
- `test_sr.py` — Leitner primitives (see §1.6).
- `test_source_parser.py` — 30+ real strings from extracted JSONs as fixtures. Assert ambiguous cases like `"PYQ Raj IA"` (no year) return `exam_year=None`, not a hallucinated year.
- `test_bookmarks.py` — happy path + duplicate insert (idempotent).
- Heatmap: skip unit tests; smoke-test on seeded DB.

### 5.7 Accessibility (brief)

Heatmap cells include the accuracy number inside the cell (not colour-only) and `aria-label="Topic, difficulty, N% accuracy"`. Star icon uses `aria-pressed` + `title`. Review-page buttons are `type="button"`.

### 5.8 Deliberately NOT building

Recommendation ML (that's Plan C §3), NLP topic auto-tagging (topic_id set at ingest), bookmark folders/labels (YAGNI), sharing (solo user), SR for right-answered questions (would need a separate `review_deck` table — out of scope), analytics on SR itself (retention curves etc — v2 of this plan if the base feature sees usage).

---

## Rollout order + dependency graph

```
  Plan 00 (tech debt) — MUST land first
    - questions.disabled + updated_at ALTERs
    - Turso silent-failure fix
             │
   ┌─────────┼──────────┐
   ▼         ▼          ▼
  F4        F3         F1
Bookmarks  PYQ        SR (Leitner)
3.5–5 h    4.5–8 h    5.5–6 h
   │        │          │
   └────────┼──────────┘
   First sprint (~13.5 h) — three independent features, ship together
            │
            ▼
           F2 Weakness heatmap (6.5–7 h)
           No schema; needs ≥20 tests to be useful
```

**Why F2 last:** highest-effort, becomes richer as the other three drive more test-taking, no dependencies. Total plan: ~20 h across 2-3 weekends. Combined with Plan C's 16 h that's ~36 h — fits a 4-6 week window without burning study time.

### Cross-plan sequencing

If both Plan A and Plan C are on the table, order by value-per-hour:

1. Plan C F1 mastery grid (3 h) — visual unblock, zero risk
2. Plan A F4 bookmarks (3.5 h) — emotional win
3. Plan A F3 PYQ quick-win (4.5 h) — functional win
4. Plan A F1 SR/Leitner (5.5 h) — study-effectiveness win
5. Plan C F2 consistency (4 h) — motivation
6. Plan C F3 next-weak-topic (4 h) — recommender
7. Plan A F2 heatmap (6.5 h) — diagnostic
8. Plan C F4 pacing benchmarks (5 h) — timing check

Total ~36 h.

---

## Open questions

1. **Shared "cards to review" pane for bookmarks + SR?** No — different semantics ("I want" vs "the system says you should"). Two separate dashboard pills.
2. **SR card whose question is `disabled=1`?** Silently skip via `WHERE q.disabled=0`. If the question is re-enabled the errors reappear.
3. **PYQ filter: hard vs bias?** Hard for v1 — it's a checkbox, user intent is clear. Slider later if there's demand.
4. **Leitner intervals: 1/3/7/14/30 or 1/3/10/30/60?** Ship `1/3/7/14/30`. For a 90-180 day runway the tighter schedule keeps box-5 cards visible before exam; 60-day intervals risk a card being untouched too long. Expose in `settings` for tweaking.
5. **SR card whose topic_mastery is now high?** Ignore mastery — SR is per-question, mastery is per-topic. They're allowed to disagree.
6. **Normaliser rewriting `questions.source`?** No — never touch the raw column, keep it as audit trail. `question_sources.raw_snippet` preserves the substring.
7. **Bookmarks during test affect `answered_count`?** No, orthogonal. `submit_answer` doesn't touch bookmarks; `/api/bookmark` doesn't touch `test_responses`.
8. **Heatmap cells click through to SR queue?** Real synergy but feature creep. Ship read-only in v1; add click-through as v2 polish.

---

## Checklist (tick when done)

**Feature 1 — SR:** `error_log` ALTERs run local + Turso · `sr.py` primitives + `tests/test_sr.py` · `bp_tests.finish()` sets `sr_box=1, sr_due_at=+1d` · `bp_review.py` blueprint · `templates/review.html` · errorlog header card · backfill existing errors from redo scores · dashboard "N due today" pill.

**Feature 2 — Heatmap:** `heatmap_diff` + `heatmap_recency` queries in `bp_analytics.py` · Python reshape · `analytics.html` two grids + toggle · CSS classes · insight strip (optional) · empty-state · mobile scroll behaviour.

**Feature 3 — PYQ filter:** `exams` + `question_sources` schema + indexes · seed 30 exam codes · `backfill_question_sources.py` — iterate to <5% MISC · hook into `bp_admin.py` insert path · `bp_tests.setup()` accepts `pyq_only`/`exam_codes`/`exam_years` · `test_setup.html` fieldset · live counts · errorlog PYQ filter (follow-up).

**Feature 4 — Bookmarks:** `bookmarks` table + indexes · `bp_bookmarks.py` · `/api/bookmark` toggle · `/api/question/<idx>` returns `bookmarked` · star toggle on `test.html` · `templates/bookmarks.html` · `/bookmarks/start_test` · sidebar link (6 templates) · dashboard count pill.

**Cross-cutting:** no new JS libs · ALTERs on Turso · blueprints registered in `app.py` · `tests/test_source_parser.py` covers ≥30 real strings · sidebar-include refactor noted as separate follow-up.

---

## Notes for cross-plan integration

- **Plan C mastery grid** vs this plan's **heatmap**: complementary, not overlapping. Grid = per-topic (dashboard). Heatmap = per-topic × difficulty (analytics). Zero conflict.
- **Plan C consistency score**: shares `mock_tests.completed_at` reads. Adding SR reviews as an "activity type" is deferred — first ship consistency as Plan C specs, then decide if reviews count.
- **Plan C next-weak-topic**: after this plan lands, `_rank_next_topic` can bias toward topics with pending bookmarks. Cheap follow-up.
- **Plan B palette / exam mode**: bookmarks work in either mode; SR is outside tests entirely.
- **Plan 00 tech debt**: bundle the Turso `questions` disabled/updated_at verification into this plan's migration script.

---

## Appendix A — sample `parse_source()` outputs

Given the extracted-JSON diversity documented in §3.1:

| Input (raw source) | Parsed rows |
|---|---|
| `"BCI 18 June 2022 Q13"` | `[{code: BCI, year: 2022, date: 2022-06-18, snippet: "BCI 18 June 2022 Q13"}]` |
| `"PYQ RPSC Programmer 27.10.2024 Paper-I"` | `[{code: RPSC-PROG, year: 2024, date: 2024-10-27, paper: I, snippet: "PYQ RPSC Programmer 27.10.2024 Paper-I"}]` |
| `"GATE CS 2014 / ISRO CS"` | `[{code: GATE-CS, year: 2014, ...}, {code: ISRO-CS, year: null, ...}]` |
| `"UGC NET Dec 2005 / ISRO CS 2011"` | `[{code: UGC-NET, year: 2005, ...}, {code: ISRO-CS, year: 2011, ...}]` |
| `"CET 10+2 Level, 22.10.24 (1st Shift)"` | `[{code: CET-RAJ-12, year: 2024, date: 2024-10-22, shift: 1st, ...}]` |
| `"Raj. IA 2018"` | `[{code: RAJ-IA, year: 2018, ...}]` |
| `"DSSSB-PGT-2018 (Male)"` | `[{code: DSSSB-PGT, year: 2018, snippet: "DSSSB-PGT-2018 (Male)"}]` |
| `"Informatics Assistant - 2013"` | `[{code: RAJ-IA, year: 2013, ...}]` |
| `null` | `[]` (question stays in DB, but has no `question_sources` row → not PYQ) |
| `"Basic Computer Instructor - 18.06.2022"` | `[{code: BCI, year: 2022, date: 2022-06-18, ...}]` |
| `"Operating System Concept"` | `[{code: MISC, ...}]` — no exam metadata, tagged for review |
| `"UGC NET / NIELIT A Level"` | `[{code: UGC-NET, year: null, ...}, {code: NIELIT, year: null, ...}]` |

**Expected coverage after 2-3 regex iterations:** ≥95% of non-null source strings match to a real `exam_code`. The remaining ≤5% land in MISC and can be manually reviewed via a `SELECT DISTINCT raw_snippet FROM question_sources WHERE exam_code = 'MISC'` query.

---

## Appendix B — Leitner box math worked example

Day 0: 8 wrong on diagnostic → all enter box 1, due day 1.
Day 1: 5 right (→box 2, due day 4), 3 wrong (stay box 1, due day 2).
Day 4: 5 due; 4 right (→box 3, due day 11), 1 wrong (→box 1, due day 5).
Day 11: 4 due; 3 right (→box 4, due day 25).
Day 25: 3 due; all right (→box 5, "retired", next visit day 55).
Day 90 = exam day: every card has been reviewed 4-5 times at spaced intervals tuned to the forgetting curve. If the exam were earlier (day 60), the schedule still hits every card at least twice.

That's the whole argument for Leitner. No hidden state, no tuning parameter, straightforward to explain to the user in one screen.
