# B — Test-Taking UX Plan

**Status:** Proposal — not implemented
**Scope:** Bring the test-taking screen closer to the real RPSC / Basic Computer Instructor online exam interface so exam day feels familiar. Five feature groups: keyboard shortcuts, question palette, timer + per-question tracking, negative marking, printable PDF export.
**Guiding principle:** Match real exam UI patterns rather than reinvent. Kartik should be able to sit down on exam day and have zero muscle-memory switching cost.

---

## 0. TL;DR — Recommended Build Order

| # | Feature | Effort | Why here in the order |
|---|---------|--------|-----------------------|
| 1 | **Exam Mode toggle** (schema + `mock_tests.mode` + `mock_tests.negative_ratio` + `mock_tests.duration_sec`) | 3h | Unblocks everything else. Current UI is "practice with instant feedback" — real exam hides answers until submit. |
| 2 | **Palette upgrade with 5-state colour code + mark-for-review** | 5h | Highest-leverage single change. Real RPSC UI is dominated by this widget; without it the test screen looks nothing like exam day. Standalone from other features. |
| 3 | **Overall countdown timer** + auto-submit at zero | 3h | Cheap once mode toggle exists; the current per-question count-up stays as an inset display in Practice Mode only. |
| 4 | **Keyboard shortcut expansion + persistent hint bar** | 2h | Small delta over what already exists (A/B/C/D + arrows). Add: `M` mark-for-review, `S` save+next, `C` clear, `Space` toggle palette, `?` cheatsheet modal. |
| 5 | **Negative marking** (config + score maths) | 2h | Just arithmetic + a form field once schema is in place. |
| 6 | **PDF export** | 4h | Nice-to-have. Wait until #1–5 are settled — printable layout will change again after palette redesign. |

**Total: ~19 hours of focused work.** Palette is deliberately not #1 because the mode toggle is a schema prerequisite. If mode toggle is deferred, palette can still ship but the "hide answer during test" behaviour needs a separate flag.

---

## 1. Argument for putting the palette FIRST (or not)

**For:**
- Every real online exam (RPSC, SSC, IBPS, UPPCL) has a palette in the top-right corner. Kartik's brain will look for it on exam day.
- Palette is a self-contained UI change — schema changes are additive (`marked_for_review` column on `test_responses`).
- Gives an immediate "this looks like a real exam" gut feeling that pays back motivation-wise.

**Against:**
- Palette semantics depend on whether the test is in Exam Mode (5 states, no correctness leaked) or Practice Mode (current 4 states including correct-dot / wrong-dot). Building it without the mode toggle means writing throwaway state logic.
- The current palette already exists at 90% of what's needed for Practice Mode. The upgrade is really about adding *Exam Mode* semantics.

**Verdict:** Mode toggle first (3h prerequisite), palette immediately after (5h). Together this is the first sprint. Treat them as a single work-item if easier.

---

## 2. Competitor Scan

Screenshots consulted from memory / public exam-day walkthroughs. Not linking URLs (things move) — pattern names below are stable.

| Platform | Palette | KB shortcuts | Timer position | Neg marking | Mark for review | Notes |
|----------|---------|--------------|----------------|-------------|-----------------|-------|
| **RPSC online exam (TCS iON)** | Right-side grid, 5 states, ~40px cells | Very limited (some builds allow A-D) | Top-right, red past 5min | Server-config, shown on instructions page | Yes, "Save & Mark for Review" is a distinct button | Sections are collapsible. Palette groups by section. This is what we should imitate closest. |
| **SSC / IBPS (Wheebox / TCS iON)** | Same right-side pattern, sometimes as popover on mobile | None reliable | Fixed top-right, countdown | Fixed ⅓ ratio per exam | Yes, orange | Very similar visual language to RPSC — colour codes are almost identical across TCS builds |
| **Testbook** | Right-side palette (~7 cols), section chips above | A-D + N (next), P (prev), R (review) | Top-right countdown | Configurable per test | Yes, purple in their build | Also has "language switch" button we can steal for bilingual later |
| **Adda247** | Bottom-drawer palette on mobile, right-side on desktop | Fewer shortcuts | Top-right | Fixed ratio | Yes | Adds "Question Type" filter to palette (MCQ / Assertion) — overkill for us |
| **Oliveboard** | Right side, chips + palette dual view | A-D | Top-right | Config | Yes | Notable: "Submit Section" button separate from "Submit Test" — needed only if we section-ize later |
| **GradeUp / BYJU Exam Prep** | Right side | Limited | Top-right | Config | Yes | Slower UI, don't imitate |
| **Anki** | N/A (single card flow) | Space to flip, 1-4 to grade | N/A | N/A | N/A | Not applicable to timed tests but their keyboard-first philosophy is the reference for KB shortcuts |
| **Google Forms / Quizizz** | Progress bar only, no palette | None | Depends | None native | Bookmark ≠ mark for review | Not appropriate for exam simulation |

**Colour convention (TCS iON standard — what candidates actually memorise):**

| State | Colour | RGB roughly |
|-------|--------|-------------|
| Not visited | Grey / light | `#e5e7eb` |
| Not answered (visited but no choice) | Red | `#dc2626` |
| Answered | Green | `#059669` |
| Marked for review (no answer) | Purple | `#7c3aed` |
| Answered + marked for review | Purple with green ring / dot | `#7c3aed` + green corner |
| Current question | Blue outline / border | `#2563eb` (border only, fill unchanged) |

We should adopt this exact colour code. Kartik has already stared at it during any RPSC practice exam he's taken.

**What we take:**
- 5-state colour code above, exactly.
- Right-side palette layout, 5–8 columns wide.
- Top-right countdown timer with 5-min red flash.
- "Save & Next" / "Save & Mark for Review" / "Clear" / "Mark for Review" 4-button action row under the question.
- `A`/`B`/`C`/`D` to pick, `M` mark-for-review, `N` / `→` next, `P` / `←` prev, `S` save+next, `C` clear.

**What we skip:**
- Section grouping in palette (we don't have sections in `mock_tests` yet).
- Language switch button (defer to bilingual work).
- Mobile bottom-drawer palette (see accessibility section — desktop-first for now).
- Question-type filter chips (Adda247's overkill).

**What we improve over the real thing:**
- A "keyboard shortcuts" cheatsheet modal (real exam doesn't have this; we do because it saves teaching Kartik shortcuts twice).
- Per-question time tracking in the *results* screen (real exam doesn't tell you this post-hoc; we already do this and it's genuinely useful).

---

## 3. Current State Analysis

### What already works (leave alone)
- `bp_tests.py:14-73` — test setup with paper/topics/difficulty/focus-weak filter is fine.
- `bp_api.py:44-58` — `/api/question/<idx>` returns question payload; contract is good.
- Palette grid in `templates/test.html:86-92` — DOM structure is fine, just needs new class states and JS logic.
- Question flag modal — no changes needed.
- Deep dive on results screen — no changes needed.

### What must change (Exam Mode requires)
- `bp_api.py:61-92` — `/api/submit_answer` immediately reveals `correct_option` + `explanation`. Must return only `{answered, total}` when test is in Exam Mode. `is_correct` computation stays server-side but is not exposed until `/test/finish`.
- `templates/test.html:270-319` — `showAnsweredState` renders correctness feedback. In Exam Mode this is bypassed; option stays selected (blue outline) but no green/red highlighting until finish.
- `templates/test.html:337-346` — keyboard handler is small; expand as described below.
- `bp_tests.py:57-61` — `mock_tests` insert lacks mode / duration / neg-marking columns. Schema change needed (see §8).

### What must be added
- Overall countdown timer (currently only per-question count-up).
- `marked_for_review` on `test_responses`.
- Auto-submit at timer zero (with a 30-second warning modal).
- `/api/toggle_review/<q_idx>` endpoint (small).
- `mock_tests.negative_ratio` and score recomputation in `/test/finish`.
- PDF export route.
- Print CSS.

### What can stay Practice-Mode-only
- Immediate feedback + explanation panel (`.feedback-panel`).
- Per-question count-up timer as inset (kept as reference).
- Green/red palette dots (`.correct-dot` / `.wrong-dot`).

---

## 4. Feature Details

### 4.1 Keyboard Shortcuts

**Currently implemented** (`templates/test.html:337-346`):
- `ArrowRight` / `ArrowLeft` — nav (only after answering, right-arrow)
- `A` / `B` / `C` / `D` — pick option (only if not answered)

**Add:**

| Key | Action | Mode | Notes |
|-----|--------|------|-------|
| `A` / `B` / `C` / `D` | Pick option | Both | Already works. In Exam Mode, allow re-picking (overwrite) until submit. |
| `Enter` | "Save & Next" — commit current answer, move to next | Both | In Practice Mode = same as clicking auto-advance |
| `Shift+Enter` | "Save & Mark for Review" | Exam only | Marks + advances |
| `M` | Toggle mark-for-review on current question | Exam only | No advance |
| `C` | Clear current answer | Exam only | Practice Mode: answer is locked once submitted |
| `→` / `N` | Next question | Both | Removed the "must have answered" gate |
| `←` / `P` | Previous question | Both | |
| `Space` | Toggle palette focus / expand palette on mobile | Both | |
| `F` | Open flag modal | Both | Currently only clickable |
| `?` | Open shortcut cheatsheet modal | Both | New modal (see UI mockup §6.4) |
| `Esc` | Close any open modal | Both | Already works globally |
| `1`–`9`, `0` | Jump to Q1–Q9, Q10 (single-digit only) | Both | Only when palette is focused (`Space` first). Discourage otherwise — clashes with option keys if we allow global. |
| `G G` | Vim-style "go to top of palette" | — | Skip. Overkill. |

**Hint bar** — persistent footer strip at the bottom of the test screen showing 4–5 most-used shortcuts. Text-only, small font, muted colour. `?` opens the full cheatsheet modal.

```
─────────────────────────────────────────────────────────────────────
 A B C D — pick    Enter — save & next    M — mark    ← → — nav    ? — help
─────────────────────────────────────────────────────────────────────
```

**Rationale:** Real exams don't show a shortcut hint bar. But Kartik will use ours daily, and having the bar means he doesn't need to open the cheatsheet every session. The bar is dismissible via `settings.value` toggle — see §8.

**Where the code goes:**
- `templates/test.html` — extend the existing `document.addEventListener('keydown', ...)` block.
- Add cheatsheet modal HTML (like existing `#flag-modal` structure).
- Do NOT put shortcuts in `static/script.js` — they're test-screen-specific. That file is only global concerns (401 handling, formatters, resolve/redo).

---

### 4.2 Question Palette / Navigator

**Existing palette** is a 10-column CSS grid at `static/style.css:447-468`. Cells are ~30px square. Keep the grid; change the state model.

#### 4.2.1 State model

Five states in Exam Mode, four in Practice Mode. Represented as data attributes on each `.q-nav-btn` so CSS can style them independently and JS logic stays simple.

```
data-state="not_visited"       — grey, no border
data-state="not_answered"      — red fill, white text
data-state="answered"          — green fill, white text
data-state="review"            — purple fill, white text
data-state="answered_review"   — purple fill, small green dot in top-right corner
```

Plus an orthogonal class:
```
.current                        — blue 2px border, does NOT change fill
```

State transitions in Exam Mode:

```
not_visited ──visit──> not_answered ──pick──> answered
                            │                    │
                            └─mark─┐             ├─mark─┐
                                   ▼             │      ▼
                                review           │  answered_review
                                   │             │      │
                                   └─pick────────┘      │
                                                        │
                                          clear ────────┴──> not_answered
```

State transitions in Practice Mode (unchanged from today, mapped to new attribute):

```
not_visited ──visit──> not_answered ──submit──> answered
                                                    │
                                          server tells us:
                                                    ├─ is_correct=1 ──> data-correct="yes"
                                                    └─ is_correct=0 ──> data-correct="no"
```

Practice Mode green/red dots live in a separate `data-correct` attribute (`yes` / `no` / unset) so the state and correctness axes don't collide.

#### 4.2.2 Layout

- Desktop: 8 columns × N rows in the right-side sticky panel. Cell aspect-ratio 1:1, min-width 36px, font 12px.
- 50-Q test = 7 rows. 100-Q test = 13 rows. Fits without scroll on 1080p; add `max-height: 60vh; overflow-y: auto` for 200-Q tests.
- Cell content: just the question number. No icons. Corner dot for `answered_review` is a `::after` pseudo-element.
- Cell hover: 1.05× scale, `title` tooltip showing status text ("Answered", "Marked for review", etc.).

Existing `.question-nav-grid` uses 10 columns. Change to 8 for larger touch/click targets and cleaner rows at 50-Q.

#### 4.2.3 Colour legend

Always visible above the palette in a compact single row, ~11px font:

```
🔴 Not answered    🟢 Answered    🟣 Review    🟢+🟣 Review+answered    ⬜ Not visited
```

Use CSS colour swatches (`<span class="dot dot-red"></span>`), not emoji — accessibility.

#### 4.2.4 Action buttons under the question

Real RPSC has a distinctive 4-button row below the options. Replicate exactly:

```
[ Clear Response ]  [ Mark for Review & Next ]  [ Save & Next ]  [ Submit Test ]
     grey                purple                     blue              red
```

- Practice Mode hides "Clear Response" and "Mark for Review & Next"; keeps "Save & Next" + "Submit Test".
- Enter key = Save & Next.
- Shift+Enter = Mark for Review & Next.
- Ctrl+Backspace or `C` key = Clear Response.

#### 4.2.5 Server persistence for mark-for-review

Needs a new endpoint:

```
POST /api/toggle_review
Body: { "question_index": 12 }
Returns: { "marked": true }
```

Store in `session["review_marks"] = {"12": true, ...}` (matches existing session pattern for `responses`). Persist to DB in `/test/finish` — see schema §8.

The palette is entirely client-side during test; server only knows about it on submit. That's fine — palette state is ephemeral until finish.

---

### 4.3 Timer + Per-Question Tracking

#### Two timers to distinguish

- **Overall countdown** — new. Top-right corner. Configured at test setup (default: 2 min/question or user-set).
- **Per-question count-up** — current behaviour. Small inset display, secondary size, only in Practice Mode. In Exam Mode it's silently tracked server-side for post-hoc analytics but not displayed.

#### Position

- Top-right of the page header, fixed (not sticky within card). ~28px monospace digits.
- Sub-label below in muted 11px: "Total remaining" or "Question timer".

Real exams put both timers stacked. TCS iON puts overall on top, section on bottom. We only have "overall" for now.

#### Warning thresholds (overall countdown, Exam Mode)

| Remaining | Colour | Behaviour |
|-----------|--------|-----------|
| > 10:00 | `--text` (dark) | Steady |
| ≤ 10:00 | `--warning` (`#d97706`) | Steady |
| ≤ 5:00 | `--danger` (`#dc2626`) | Steady, 1× flash at first crossing |
| ≤ 1:00 | `--danger`, blinking | 0.5s blink cycle |
| = 0 | `--danger` | Auto-submit, no confirmation |

Show a modal at 30s remaining: "30 seconds left — test will auto-submit at zero." Dismissable. Modal appearance is a one-time thing per test.

**Anti-pattern to avoid:** Do not tick the timer every 100ms (current per-question timer does this). Use `setInterval(..., 1000)` and `Date.now()` for the source of truth to survive tab-throttling. Store `test.started_at` server-side and compute remaining as `duration_sec - (now - started_at)` on each tick — this way pausing/refreshing the tab doesn't give free time.

#### Server-side clock authority

Client computes remaining from `test.started_at` (already in `mock_tests`) + `test.duration_sec` (new column). On any refresh, the timer picks up where it should be. If Kartik refreshes at 15 minutes remaining, he sees 15 minutes remaining. If he closes the tab for 5 minutes and reopens, the tab now shows 10 minutes remaining.

Add `GET /api/test_status` returning `{ started_at, duration_sec, remaining_sec, current_time }` — client uses `remaining_sec` on load, then ticks locally.

Auto-submit is enforced server-side too: any `POST /api/submit_answer` after `now > started_at + duration_sec` is rejected with a 409 and the client is redirected to `/test/finish`.

#### Per-question analytics

Currently stored in `test_responses.time_spent_sec` at the moment of `/api/submit_answer`. This assumes one-shot answering — problematic in Exam Mode where users can revisit and change answers. Two options:

- **A. Cumulative:** Sum time across visits. Track per-visit deltas client-side, POST final total in `/api/submit_answer` (or in `/test/finish` for un-submitted answers).
- **B. Last-visit only:** Only count time on the visit that produced the final answer. Loses info.

Recommend A. Store an array of visit durations in `session["responses"][q_idx]["visits"]` client-side, sum on submit. This means changing the payload shape but is the more useful metric.

Add `test_responses.visit_count INTEGER DEFAULT 1` for post-hoc analysis of "how often did I flip-flop on this question."

---

### 4.4 Negative Marking

#### Storage

**Per-test, not global.** Different exams use different ratios (BCI is ⅓, some RPSC papers are ¼, some are 0). Stored on `mock_tests.negative_ratio REAL DEFAULT 0`.

- `0.0` — no negative marking (default)
- `0.333333...` — BCI standard
- `0.25` — some RPSC papers
- User can enter any value 0.0–1.0 in test setup.

Global default lives in `settings` table:
```
INSERT OR IGNORE INTO settings (key, value) VALUES ('default_neg_ratio', '0.333333');
```

Test setup form pre-populates from this default but is per-test overridable.

#### Score computation

Currently `bp_tests.py:101-103`:
```python
correct = sum(1 for r in responses.values() if r["is_correct"])
total = len(questions)
score = round((correct / total * 100) if total > 0 else 0, 1)
```

New:
```python
correct = sum(1 for r in responses.values() if r["is_correct"])
wrong   = sum(1 for r in responses.values() if not r["is_correct"] and r["selected"])
unanswered = total - correct - wrong
raw_marks = correct - (wrong * neg_ratio)
max_marks = total  # 1 mark per question
score_pct = round((raw_marks / max_marks * 100), 1)
```

Store on `mock_tests`:
- `score` (percentage, existing)
- `raw_marks REAL` (new — for display "42.33/100")
- `wrong_count INTEGER` (new)
- `unanswered_count INTEGER` (new — computed from total - correct - wrong)

#### UI

- Test setup form: numeric input "Negative marking (fraction of correct mark)". Default from settings. Hint: "0.333 = ⅓, 0.25 = ¼, 0 = disabled."
- Results screen: show breakdown "42 correct − 6 × 0.333 = 40.00 / 50 (80%)".
- Instructions banner before test starts (Exam Mode only): "This test uses ⅓ negative marking."

#### Edge cases

- Unanswered → 0 marks (no penalty). Encourage skipping over guessing when penalty is high.
- Marked-for-review without answer → same as unanswered.
- Practice Mode → ignore `negative_ratio` in score display, but store the raw value on the test row. That way switching a past test to Exam Mode retroactively works.

---

### 4.5 PDF Export (offline mock printout)

#### Purpose

Kartik studies away from the laptop sometimes. Print a mock, take it on paper, then enter answers back into the app for scoring.

#### Two flavours

1. **Test paper PDF** — 100 questions, options A/B/C/D, no answers. Blank grid for answers at the top or bottom.
2. **Answer key PDF** — separate document with correct answers + explanations. Kartik can print without looking.

Optionally: a third **"scored test" PDF** — after submission, a report-style PDF showing his responses vs correct.

#### Implementation: client-side vs server-side

**Recommendation: client-side, using `window.print()` + `@media print` CSS.**

Rationale:
- Zero new Python deps. Bundling WeasyPrint (Pango, Cairo, fontconfig) on Render is annoying — the free tier build times balloon.
- Browser print-to-PDF is universal, controllable, and the resulting file is small.
- Custom "print view" route + CSS is enough.
- We already produce HTML; letting the browser render it is the least redundant path.

**Downside:** margins and page breaks require careful CSS. That's fine.

**Server-side (WeasyPrint / ReportLab) is worth revisiting if:**
- We need programmatic PDF generation (e.g., email a nightly PDF).
- Print styling gets too fiddly.

Not now.

#### Print view routes

```
GET  /test/setup?export=pdf           — form to configure the export
POST /test/export                     — generates a printable HTML page
GET  /test/print/<generation_id>      — printable page for question set
GET  /test/print/<generation_id>/key  — printable page for answer key
```

`generation_id` is a token stored in a new `pdf_generations` table (or on `mock_tests` with `mode='paper'`) so it's a real DB row not a URL-generated random sample.

Alternative: reuse `mock_tests` with `mode='paper'` and `status='paper'`. Cleaner.

#### Print layout (single sheet, one column, 2 questions per page approx)

```
┌──────────────────────────────────────────────┐
│   Mock Test #123 — Paper II                  │
│   50 questions · 60 minutes · ⅓ negative     │
│                                              │
│   Name: ________________  Date: __________   │
├──────────────────────────────────────────────┤
│                                              │
│  1. What is the base of the binary system?   │
│                                              │
│     A. 2      B. 8      C. 10     D. 16      │
│                                              │
│  2. Which of the following is NOT a...       │
│                                              │
│     A. TCP    B. UDP    C. HTTP   D. ICMP    │
│                                              │
│                    ... continues ...         │
│                                              │
├──────────────────────────────────────────────┤
│  Answer Sheet (fill A/B/C/D)                 │
│  1: ___  2: ___  3: ___  4: ___  5: ___      │
│  6: ___  7: ___  8: ___  9: ___  10: ___     │
│  ...                                         │
└──────────────────────────────────────────────┘
```

For the answer key, mirror the layout but replace blanks with the letter + a one-line explanation.

#### `@media print` CSS additions

```css
@media print {
  .sidebar, .side-panel, .card-header,
  #q-nav-grid, .btn, .action-buttons,
  .modal-overlay, footer { display: none !important; }

  body { background: white; color: black; font-size: 11pt; }
  .main { margin-left: 0; padding: 0; }
  .page-header { border: none; padding: 8pt 0; }

  .print-question { page-break-inside: avoid; margin-bottom: 12pt; }
  .print-question .options { display: flex; gap: 16pt; flex-wrap: wrap; }
  .print-answer-sheet { page-break-before: always; }
  .print-answer-sheet .grid { columns: 5; column-gap: 12pt; font-family: monospace; }

  @page { margin: 1.5cm; }
}
```

#### Effort split

- Print route + template: 1.5h
- `@media print` CSS iteration: 1h
- Answer key variant: 30min
- Manual QA (print preview in 3 browsers): 1h

**Total: ~4h.** Ship after the rest of the exam-mode work.

---

## 5. Backend Changes Summary

### 5.1 Schema (Turso)

```sql
-- mock_tests additions
ALTER TABLE mock_tests ADD COLUMN mode TEXT DEFAULT 'practice';
ALTER TABLE mock_tests ADD COLUMN duration_sec INTEGER;
ALTER TABLE mock_tests ADD COLUMN negative_ratio REAL DEFAULT 0;
ALTER TABLE mock_tests ADD COLUMN raw_marks REAL;
ALTER TABLE mock_tests ADD COLUMN wrong_count INTEGER;
ALTER TABLE mock_tests ADD COLUMN unanswered_count INTEGER;

-- test_responses additions
ALTER TABLE test_responses ADD COLUMN marked_for_review INTEGER DEFAULT 0;
ALTER TABLE test_responses ADD COLUMN visit_count INTEGER DEFAULT 1;

-- settings — default negative ratio
INSERT OR IGNORE INTO settings (key, value) VALUES ('default_neg_ratio', '0.333333');
INSERT OR IGNORE INTO settings (key, value) VALUES ('default_test_duration_min', '60');
INSERT OR IGNORE INTO settings (key, value) VALUES ('show_kb_hint_bar', 'true');
```

**Migration risk:** all additive `ALTER TABLE` on Turso. No data rewrite. See tech-debt plan for the schema-drift verification story. Note that `db.py` `SCHEMA` string must also be updated so any future re-init has the new columns.

### 5.2 New endpoints (`bp_api.py`)

```
POST /api/toggle_review            — { question_index } → { marked }
GET  /api/test_status              — { started_at, duration_sec, remaining_sec, current_time }
POST /api/save_and_next            — same as submit_answer but explicit no-reveal
```

`/api/submit_answer` gains conditional behaviour: if `session["test_mode"] == "exam"`, don't return `correct_option` / `explanation`. Store the answer, return only `{ answered, total }`. Add reveal on `/test/finish`.

### 5.3 New route (`bp_tests.py`)

```
GET  /test/print/<test_id>         — printable question view (respects mode='paper')
GET  /test/print/<test_id>/key     — printable answer key
```

### 5.4 Score recomputation (`bp_tests.py:101-103`)

Add negative-marking arithmetic; store `raw_marks`, `wrong_count`, `unanswered_count` on `mock_tests`. Existing `score` remains the percentage for compatibility with `topic_mastery` blending logic at `bp_tests.py:145-164`.

### 5.5 Session state

Add:
- `session["test_mode"]` — `"practice"` or `"exam"`.
- `session["review_marks"]` — dict `{q_idx_str: true}`.
- `session["negative_ratio"]` — float, mirrors `mock_tests` row for fast client access.

---

## 6. UI Mockups

### 6.1 Full Exam Mode test screen

```
┌────────────┬────────────────────────────────────────────────────┬──────────────────────┐
│            │ Mock Test #12 — Paper II                           │ ⏱ 42:17              │
│ SIDEBAR    │ Question 7 of 50 · Data Structures · Medium        │ (Total remaining)    │
│            ├────────────────────────────────────────────────────┤ 5-min flash at 05:00 │
│ ▪ Dashbrd  │                                                    ├──────────────────────┤
│ ▶ Test     │  Q7. In a binary search tree, the in-order         │ Question Palette     │
│ ★ Analytc  │      traversal produces which sequence?            │                      │
│ ⚠ Errlog   │                                                    │  1  2  3  4  5  6  7 │
│            │  ○ A. Reverse-sorted order                         │  ●  ●  ●  ●  ●  ●  ⬜│
│            │  ● B. Sorted (ascending) order                     │  ●  ●        current │
│            │  ○ C. Random order                                 │  8  9 10 11 12 13 14 │
│            │  ○ D. Level-order (BFS)                            │  ⬜ ⬜ ⬜ ⬜ ⬜ ⬜ ⬜│
│            │                                                    │  15 16 17 18 19 20 21│
│            │                                                    │  ⬜ ⬜ ⬜ ⬜ ⬜ ⬜ ⬜│
│            │                                                    │                      │
│            │ ⚑ Report issue                                     │  ... continues       │
│            ├────────────────────────────────────────────────────┤                      │
│            │ [Clear] [Mark & Next] [Save & Next] [Submit Test] │  Legend:             │
│            │  grey    purple         blue         red          │  🟢 Answered         │
│            └────────────────────────────────────────────────────┤  🔴 Not answered     │
│            │ A B C D — pick   Enter — save & next   M — mark   │  🟣 Review           │
│            │ ← → — nav   ? — help                              │  ⬜ Not visited      │
└────────────┴────────────────────────────────────────────────────┴──────────────────────┘
```

### 6.2 Practice Mode (preserves current behaviour with new palette state names)

```
┌────────────┬────────────────────────────────────────────────────┬──────────────────────┐
│            │ Mock Test #12 — Paper II                           │ Q timer 00:42        │
│ SIDEBAR    │ Question 7 of 50 · Data Structures · Medium        │ (per-question)       │
│            ├────────────────────────────────────────────────────┤                      │
│ ▪ Dashbrd  │                                                    │  1  2  3  4  5  6  7 │
│ ▶ Test     │  Q7. In a binary search tree, the in-order         │  ✓  ✓  ✗  ✓  ✓  ✓  ⬜│
│            │      traversal produces which sequence?            │  current             │
│            │                                                    │                      │
│            │  ○ A. Reverse-sorted                               │  Legend:             │
│            │  ✓ B. Sorted (ascending)  ← immediate feedback     │  ✓ Correct           │
│            │  ○ C. Random                                       │  ✗ Wrong             │
│            │  ○ D. Level-order                                  │  ⬜ Unattempted      │
│            │                                                    │                      │
│            │  ┌ ✓ Correct! ─────────────────────────┐          │                      │
│            │  │ Explanation: In-order traversal...  │          │                      │
│            │  └──────────────────────────────────────┘          │                      │
│            │                                                    │                      │
│            │ [ Next Question ▶ ]                                │                      │
└────────────┴────────────────────────────────────────────────────┴──────────────────────┘
```

### 6.3 Palette colour legend (both modes)

```
  Exam Mode:
  ┌───┬───┬───┬───┬───┐
  │🟢 │🔴 │🟣 │🟢🟣│⬜ │
  └───┴───┴───┴───┴───┘
   Ans NoA Rev Ans+  Not
                Rev  visited

  Practice Mode:
  ┌───┬───┬───┐
  │ ✓ │ ✗ │⬜ │
  └───┴───┴───┘
   OK  Bad Skip
```

### 6.4 Keyboard cheatsheet modal (opens with `?`)

```
┌─ Keyboard Shortcuts ────────────────────────────────┐
│                                                     │
│  Answering                                          │
│    A B C D          Pick option A/B/C/D             │
│    C                Clear response (Exam only)      │
│                                                     │
│  Navigation                                         │
│    Enter / N / →    Save & next                     │
│    Shift+Enter      Save & mark for review          │
│    P / ←            Previous question               │
│    Space            Focus palette                   │
│                                                     │
│  Palette (when focused)                             │
│    1-9, 0           Jump to Q1-Q10                  │
│    Arrows           Navigate palette                │
│    Enter            Go to selected                  │
│                                                     │
│  Other                                              │
│    M                Toggle mark for review          │
│    F                Flag question issue             │
│    ?                This help                       │
│    Esc              Close modal                     │
│                                                     │
│  [Don't show hint bar]  [ Close ]                   │
└─────────────────────────────────────────────────────┘
```

### 6.5 End-of-test results — time per question

Add to `templates/results.html` (currently missing). A horizontal bar chart:

```
Time per question (seconds)
Q1  ▓▓ 12s   ✓
Q2  ▓▓▓▓ 24s ✗
Q3  ▓ 6s     ✓
Q4  ▓▓▓▓▓▓▓▓▓▓▓ 68s ✓  ← slowest
Q5  ▓▓▓ 18s  ✓
...
Q50 ▓▓ 14s   ✓
     └── target line at 60s ─┘
```

Use Chart.js horizontal bar (already loaded on results page at line 8). Colour bars green if correct, red if wrong. Highlight bars over target (60s default, from `settings.target_time_per_question`).

### 6.6 Test setup form additions

Add three fields to `templates/test_setup.html`:

```
┌ Test Mode ────────────────────────────────────┐
│ ○ Practice — instant feedback + explanations  │
│ ● Exam     — no feedback until submit         │
└────────────────────────────────────────────────┘

┌ Duration ─────────────────────────────────────┐
│  ┌──┐                                          │
│  │60│ minutes  (default: 60)                   │
│  └──┘                                          │
└────────────────────────────────────────────────┘

┌ Negative marking ─────────────────────────────┐
│  ┌──────┐                                      │
│  │0.333 │  fraction (0.333 = ⅓, 0 = disabled) │
│  └──────┘                                      │
└────────────────────────────────────────────────┘
```

---

## 7. Accessibility Notes

### 7.1 Keyboard-only navigation

The test screen MUST be usable with keyboard alone. Current state is almost there but has gaps:

- `.q-nav-btn` buttons receive focus via `Tab` but there's no ARIA state announced. Add:
  ```html
  <button
    class="q-nav-btn"
    aria-label="Question 7, answered, marked for review, current"
    aria-current="location"
    data-state="answered_review">
    7
  </button>
  ```

- Focus ring: current CSS uses `:focus { outline: none; ... box-shadow: ... }` on form fields. Palette buttons need a visible focus ring — 2px `--primary` outline works.

- Option buttons (`btn-option`) need `role="radio"` and `aria-checked`. The whole options list becomes a `role="radiogroup"` with `aria-labelledby="q-text"`.

### 7.2 Screen reader announcements

- Timer: don't spam the screen reader with per-second updates. Add `aria-live="polite"` on the timer, but update the accessible text only at the 10min / 5min / 1min thresholds (not every tick). Use a hidden `<span class="sr-only">` for these announcements.
- On answering: announce "Answered." briefly. On mark-for-review: "Marked for review."
- On palette state change: don't announce — the state is discoverable on tab-through.

### 7.3 Colour contrast

TCS iON colours are chosen for contrast, but double-check:
- White text on `#dc2626` (red) — WCAG AA passes (4.6:1).
- White text on `#059669` (green) — AA passes (3.4:1 — passes for large text ≥18pt; borderline for 12px palette cells). Consider `#047857` for cells if a WCAG audit fails.
- White text on `#7c3aed` (purple) — AA passes (5.7:1).

### 7.4 Reduced motion

Wrap the 1-minute blink and the 30s modal slide-in in:
```css
@media (prefers-reduced-motion: reduce) {
  .timer-blink { animation: none; }
  .modal { animation: none; }
}
```

### 7.5 Mobile

Current `@media (max-width: 900px)` collapses `.test-layout` to single column. This shoves the palette below the question. Fine for phones. Two follow-ups (defer to polish plan E):
- Convert palette to bottom-sheet drawer that swipes up on mobile.
- Increase palette cell size to 44px (touch target minimum).

Do not block this plan on those.

---

## 8. Migration & Backwards Compatibility

### 8.1 Existing in-progress tests

At schema-migration time, add `mode='practice'` and `duration_sec=NULL` to all existing rows. The existing tests continue to render as before (Practice Mode, no timer).

### 8.2 `test_responses` back-fill

`marked_for_review=0` and `visit_count=1` for all existing rows — no ambiguity.

### 8.3 Feature flag safety

Wrap all new UI in mode-checks so a broken deploy doesn't nuke Practice Mode:

```jinja
{% if test.mode == 'exam' %}
  ... exam-mode-only markup ...
{% else %}
  ... existing practice markup ...
{% endif %}
```

### 8.4 Settings back-fill

The three new `settings` rows use `INSERT OR IGNORE` — safe to re-run.

### 8.5 Old JS still works

`static/script.js` doesn't need to change for palette/timer work — all new JS lives in `templates/test.html` inline. Keep `script.js` for globals.

---

## 9. Testing Plan

### 9.1 Manual test matrix

| Scenario | Mode | Expected |
|----------|------|----------|
| Answer all Qs in order | Practice | Instant feedback, palette fills green/red |
| Answer all Qs in order | Exam | No feedback, palette fills green only |
| Skip Q3, go to Q5 | Both | Q3 palette state = not_answered (red) in Exam; not_visited-ish in Practice |
| Mark Q7 for review, answer Q7, revisit | Exam | Palette shows purple+green corner dot |
| Timer hits 0 | Exam | Auto-submit fires; results appear |
| Refresh at 15:00 remaining | Exam | Reloads with 15:00 (server-authoritative) |
| Close tab for 5min, reopen | Exam | Timer picks up 5min less |
| Type answers with keyboard only | Both | End-to-end test possible without mouse |
| Fill flag modal via keyboard | Both | Tab-navigable, Esc closes |
| Change answer to Q4 after answering | Exam | Allowed; new value overwrites; visit_count+=1 |
| Change answer to Q4 after answering | Practice | Locked; no change |
| Negative marking = 0.333, 40 correct, 5 wrong | Exam | raw_marks = 40 - 5*0.333 = 38.33 |
| Negative marking = 0, 40 correct, 5 wrong | Exam | raw_marks = 40 |
| Print preview in Chrome | Any | Sidebar hidden, palette hidden, questions paginated cleanly |

### 9.2 Automated (optional but recommended)

- Playwright script: start a test → answer 5 Qs via KB → mark 1 for review → submit → assert results. ~30 min to write.
- Server-side unit test on score computation with negative marking (pytest). ~15 min.

### 9.3 Regression risk

- **`topic_mastery` blending** at `bp_tests.py:145-164` relies on `score` being the raw percentage. If I change `score` to include negative marking, mastery scores could drop retroactively. Keep `score` as (correct/total)*100 for topic mastery purposes; use `raw_marks` for the score-with-penalty display. Document this on the test row.

---

## 10. Effort Estimate Summary

| Feature | Estimate | Blocked by |
|---------|----------|------------|
| Schema migration + mode flag | 3h | Nothing |
| Palette state upgrade (5 states + colours) | 3h | Schema |
| Mark-for-review persistence + endpoint | 1.5h | Schema |
| Action buttons (Clear / Mark & Next / Save & Next / Submit) | 1h | — |
| Countdown timer (server-authoritative) | 3h | Schema |
| Auto-submit + 30s warning modal | 1h | Timer |
| Keyboard shortcut expansion + hint bar | 1.5h | — |
| Keyboard cheatsheet modal | 30min | — |
| Negative marking config + score maths | 2h | Schema |
| Results screen additions (bar chart, negative-marking breakdown) | 2h | Score maths |
| PDF export routes + templates | 2.5h | — (independent) |
| Print CSS iteration | 1.5h | PDF routes |
| Accessibility pass (ARIA, focus rings, reduced-motion) | 2h | UI done |
| Testing (manual + optional Playwright) | 2h | — |

**Total: ~26h.** Round up to 30h with buffer. Fits in one dedicated week or 2–3 weekends.

---

## 11. Open Questions / Follow-ups

1. **Sections?** RPSC exams have sectioned papers (Paper I sections A–D). Current `mock_tests` has no section concept. Palette-with-sections is real-RPSC accurate but doubles the palette work. **Defer** — flag as follow-up.
2. **Language switch?** Some questions in `data/extracted_questions/*.json` are English-only, some might be bilingual later. Not needed for BCI prep now — defer.
3. **Bilingual explanations?** `questions.language` column exists (`db.py:31`, default `'bilingual'`) but isn't used. Independent of test-taking UX. Defer.
4. **Autosave between clicks?** In Exam Mode, we currently only save on "Save & Next". A tab crash mid-question loses the current picked option. Consider a debounced auto-persist to `session["responses"]` on click. Cheap: 30 min.
5. **Live status widget** on the "Test in progress" state — dashboard could show "Test in progress · 42 min remaining". Would need a resume-test link. Follow-up.
6. **Instructions screen before test starts** (like real RPSC): 1-page pre-test screen with duration, question count, negative marking, "click Begin to start timer". This is a good UX polish item; ~1h. Recommend adding it in the second pass.

---

## 12. Execution Checklist

**Sprint 1 (Exam Mode fundamentals — ~10h)**
- [ ] Add columns to `mock_tests` and `test_responses` (Turso ALTER TABLE)
- [ ] Update `db.py` `SCHEMA` string to match
- [ ] Verify schema-drift smoke test (see tech-debt plan) catches ALTER omissions
- [ ] Add `test_mode` field to test setup form
- [ ] Modify `bp_tests.py:setup()` to persist mode/duration/neg_ratio
- [ ] Modify `bp_api.py:submit_answer()` to conditionally reveal answer
- [ ] Add `/api/toggle_review` endpoint
- [ ] Add 5-state palette CSS + data-state attributes
- [ ] Manual test: complete both modes end-to-end

**Sprint 2 (Timer + KB — ~5h)**
- [ ] Add server-authoritative countdown (`/api/test_status`)
- [ ] Client-side tick loop using server-provided `remaining_sec`
- [ ] Warning thresholds (10min amber, 5min flash, 1min blink, 30s modal)
- [ ] Auto-submit on zero (client + server both)
- [ ] Expand keyboard handler with new keys
- [ ] Cheatsheet modal
- [ ] Hint bar with toggle in cheatsheet

**Sprint 3 (Negative marking + results — ~4h)**
- [ ] Score maths in `/test/finish`
- [ ] Store raw_marks / wrong_count / unanswered_count
- [ ] Results screen: negative-marking breakdown row
- [ ] Results screen: time-per-question bar chart

**Sprint 4 (PDF export — ~4h)**
- [ ] `/test/print/<id>` route
- [ ] `/test/print/<id>/key` route
- [ ] Print CSS `@media print` block
- [ ] Answer-sheet grid at bottom
- [ ] Manual print-preview QA in Chrome + Firefox

**Sprint 5 (Accessibility + polish — ~3h)**
- [ ] ARIA labels on palette + option buttons
- [ ] Focus rings visible on all interactive elements
- [ ] `prefers-reduced-motion` respected
- [ ] Screen-reader-only announcements for timer thresholds
- [ ] Colour contrast audit (WebAIM contrast checker)

**Sprint 6 (Testing + cleanup — ~2h)**
- [ ] Complete manual test matrix (§9.1)
- [ ] Optional Playwright script
- [ ] Update `README.md` with Exam Mode notes
- [ ] Update `docs/plans/00-tech-debt.md` checklist if this sprint introduced new debt

---

## Cross-plan dependencies

- **Depends on 00-tech-debt:** the silent-failure fix in `turso_patch._post` MUST land before the ALTER TABLE work here, otherwise a mis-typed column name would silently drop test rows and we'd only notice after Kartik finishes a test.
- **Interacts with A-study-effectiveness:** the "PYQ filter" in that plan will want to sit next to Test Mode toggle on the setup form. Coordinate form layout when both land.
- **Interacts with C-dashboard-analytics:** results-page bar chart is duplicated in analytics; share the Chart.js config.
- **Interacts with D-content-quality:** flag modal already exists; no changes here.
- **Interacts with E-polish:** dark mode and mobile drawer redesign land after this. Timer/palette CSS should already use `var(--*)` so dark mode is a drop-in later.
