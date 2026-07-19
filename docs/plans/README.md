# Implementation Roadmap

Index + cross-plan sequencing for the six research plans written on 2026-07-17.
Each plan below is standalone and fully self-contained; this file is the map.

---

## The six plans

| # | Plan | File | Lines | Effort | What it delivers |
|---|---|---|---|---|---|
| 00 | Tech debt | [`00-tech-debt.md`](00-tech-debt.md) | 444 | ~4h | Fix `turso_patch` silent failures + schema drift + token rotation |
| A | Study effectiveness | [`A-study-effectiveness.md`](A-study-effectiveness.md) | 949 | ~30h | Leitner spaced repetition, weakness heatmap, PYQ filter, bookmarks |
| B | Test-taking UX | [`B-test-taking-ux.md`](B-test-taking-ux.md) | 875 | ~30h | TCS-iON question palette, keyboard shortcuts, timer, neg-marking, print export |
| C | Dashboard/analytics | [`C-dashboard-analytics.md`](C-dashboard-analytics.md) | 764 | ~16h | Mastery grid, consistency score (not streaks), next-weak-topic picker, pacing |
| D | Content quality | [`D-content-quality.md`](D-content-quality.md) | 919 | ~19h | Structured metadata columns, mid-confidence review UI, dedupe, topic backfill |
| E | Polish | [`E-polish.md`](E-polish.md) | 609 | ~20h | Structured flagging, dark mode, mobile responsive, FTS5 search |

**Total mandatory effort: ~119 h** (~3 solid working weeks, or ~5 evenings/week × 6 weeks).

---

## Cross-plan dependencies

```
                             ┌──────────────┐
                             │  00 tech-debt │  ← blocks everything
                             └───────┬───────┘
                                     │  adds `disabled`, `updated_at`
                                     │  fixes turso_patch silent-fail
                                     │
        ┌────────────────┬───────────┼───────────────┬────────────┐
        ▼                ▼           ▼               ▼            ▼
     ┌──────┐        ┌──────┐    ┌──────┐        ┌──────┐    ┌──────┐
     │  B   │        │  C   │    │  D   │        │  E   │    │  A   │
     │ Test │        │Dash- │    │Content│       │Polish│    │Study │
     │  UX  │        │board │    │quality│       │      │    │effect│
     └──────┘        └──────┘    └──┬───┘        └──┬───┘    └──▲───┘
                                    │               │           │
                                    │  adds `pyq_exam`,         │
                                    │       `pyq_year`,         │
                                    │       `confidence`,       │
                                    │       `section`, ...      │
                                    │               │           │
                                    └───────────────┼───────────┤
                                                    │           │
                                          E's search filters,   │
                                             A's PYQ filter ────┘
```

**Hard blocks:**
- **00 blocks all** — schema migrations must land or subsequent ALTERs pile up on broken foundation
- **D → A**: A's PYQ filter needs D's `pyq_exam`/`pyq_year` columns (both plans co-designed those names)
- **D → E**: E's search should filter by D's structured metadata

**Soft blocks:**
- **E dark mode → E mobile**: dark-mode's CSS variable pass rewrites the same declarations mobile media queries touch. Doing mobile first means editing every color rule twice.
- **B schema/mode toggle → B palette**: 3h schema prep unblocks the palette (the highest-leverage UI change in B)

---

## Recommended execution order

### Phase 1 — Foundation (~4h)
**Plan 00 in full.** No user-visible changes. Just fixes the silent-failure bug in `turso_patch`, adds `disabled` + `updated_at` columns to Turso, and rotates the leaked tokens. Ship + verify no regressions in the running app.

**Exit criterion:** the smoke test from `00-tech-debt.md` §Verification passes — an INSERT with an unknown column now raises `sqlite3.OperationalError` instead of silently returning `lastrowid=None`.

### Phase 2 — Structured metadata (~10h)
**Plan D §5 only** (structured metadata recovery). Adds `pyq_exam`, `pyq_year`, `confidence`, `section`, `sub_topic`, `review_notes`, `confidence_reviewed_at` columns and backfills them from `data/extracted_questions/*.json`. No user-facing UI yet.

Why now: unblocks Plan A's PYQ filter and Plan E's search. Metadata columns are cheap to add early; painful to bolt on after features start reading them.

**Exit criterion:** running `SELECT COUNT(*) FROM questions WHERE pyq_exam IS NOT NULL` in Turso returns ~1500 (matches the PYQ count in the source JSONs).

### Phase 3 — Quick-win sprint (~13h)
Pull the three smallest changes that give the biggest immediate UX bump:

1. **Plan A F4 — Bookmarks** (~3h) — new table, star toggle in test.html, `/bookmarks` list route
2. **Plan A F3 — PYQ filter** (~3h) — reuses Phase 2 columns; adds "PYQ only" toggle to test setup
3. **Plan E structured flagging refresh** (~2h) — 7-category radio list replacing current `<select>`; the underlying whitelist in `bp_api.py:10` is already structured, only the UI changes
4. **Plan B schema + mode toggle** (~3h) — adds `test_mode` (exam/practice) column to `mock_tests`; groundwork for the palette

**Ship at this point** — Kartik gets bookmarks, PYQ filtering, better flag UI, and the plumbing for the palette. Test everything before Phase 4.

### Phase 4 — Test-taking overhaul (~27h)
**Plan B in full**, minus the schema prep already done in Phase 3.

Order within B:
1. Question palette + keyboard shortcuts (highest muscle-memory value for exam day)
2. Timer + per-question time tracking
3. Negative marking config
4. Print export

**Exit criterion:** end-to-end test as if it were exam day — 100-question mock, palette navigation only, keyboard only, timer visible, neg-marking on. Compare to a real RPSC mock UI screenshot.

### Phase 5 — Analytics + spaced repetition (~26h)
Interleave A and C because they read the same tables (`error_log`, `topic_mastery`, `test_responses`):

1. **Plan C mastery grid** (~3h) — surface existing `topic_mastery` table with 18-tile visualization
2. **Plan A F1 — Leitner spaced repetition** (~9h) — extend `error_log` with box + due_at, `/review` route pulling due cards
3. **Plan C next-weak-topic** (~4h) — `gap × weightage × recency × confidence` picker
4. **Plan A F2 — Weakness heatmap** (~4h) — placed on analytics *below* the mastery grid
5. **Plan C consistency score** (~3h) — 28-day rolling, 20-day denominator (weekend-friendly)
6. **Plan C pacing chart** (~3h) — time-per-question benchmarks

**Exit criterion:** dashboard tells Kartik in one glance: "You're 62% ready. Weakest topic is X worth Y points. 7 cards due today. Study 45m for 3 more days to stay on track."

### Phase 6 — Content quality (~9h)
**Plan D remaining** (§2 mid-confidence review UI + §3 dedupe + §4 backfill).

Order: dedupe first (removes noise before review), then mid-confidence review, then backfill for the 9 under-floor topics.

**Exit criterion:** all ~90 medium-confidence rows reviewed and either promoted to `confidence=high`, edited, or disabled. Duplicates count drops below 50.

### Phase 7 — Polish (~18h)
**Plan E remaining** (dark mode → mobile → search).

Dark mode first per the soft-block above; mobile second (biggest LOC touch); search last since it needs Phase 2 columns.

**Exit criterion:** iPhone SE (375px) portrait works end-to-end — take a test, view analytics, review a bookmark. Dark mode toggles without flash. Cmd-K opens search from any page.

---

## Total sequencing summary

| Phase | Focus | Effort | User-visible change |
|---|---|---|---|
| 1 | Tech debt (Plan 00) | 4h | None (invisible bug fixes) |
| 2 | Structured metadata (Plan D §5) | 10h | None (schema + backfill) |
| 3 | Quick wins (A F3/F4 + E flag + B schema) | 13h | Bookmarks, PYQ filter, cleaner flag form |
| 4 | Test-taking (Plan B) | 27h | Palette, shortcuts, timer, neg-marking, print |
| 5 | Analytics + SRS (Plan C + A F1/F2) | 26h | Mastery grid, next-topic, review queue, heatmap, pacing |
| 6 | Content quality (Plan D §2-4) | 9h | Dedupe, mid-conf review, backfill |
| 7 | Polish (Plan E) | 18h | Dark mode, mobile, search |
| **Total** | | **~107h** | |

(Slightly less than the sum of individual plan estimates because Plan D §5 and Plan B schema are pulled forward into shared phases, and some overlap credit.)

---

## Key design decisions to lock in *before* starting

Skim these before Phase 1 so we don't re-litigate mid-implementation:

1. **Spaced repetition algorithm** — Plan A recommends **Leitner-5** (not SM-2 or FSRS). Fixed exam date + cold-start data + explainability + solo-dev maintenance all favor Leitner. Confirm you're OK with this or push back now.

2. **Streak vs consistency score** — Plan C recommends **consistency score** (28-day rolling, weekend-friendly) instead of Duolingo-style streaks. Kartik's Mon-Fri rhythm would break a strict streak in week one and demotivate. Confirm.

3. **Palette color convention** — Plan B adopts the **TCS-iON** color palette (green=answered, red=not visited, purple=marked-for-review, etc.) to match the real RPSC exam-day interface. This is a UX-fidelity choice, not a stylistic one. Confirm.

4. **Search backend** — Plan E recommends **libSQL FTS5** (server-side, ranked) not client-side JSON filter. Turso bundles FTS5. Confirm.

5. **Synthetic question generation** — Plan D suggests filling under-floor topics with Claude-generated synthetic questions tagged `source='synthetic-v1'` and capped at 40% of any topic. This is content policy — some users would prefer PYQ-only. Confirm you're OK with synthetic fills.

6. **Token rotation urgency** — Plan 00 puts rotation as low-risk deferred. If you plan to push this repo to a public fork soon, upgrade rotation priority.

---

## What's NOT in these plans

Out of scope for now (may become future plans):

- Bilingual (Hindi/English) content improvements — extraction was English-only
- Audio playback of questions (accessibility, exam commute study)
- LLM-generated explanations for questions where `explanation` is empty
- Multi-user features (leaderboards, study groups) — solo-user tool
- Native mobile app — the mobile plan is responsive web only
- CI/CD, automated deploys — Render dashboard is manual
- Feature flags / A/B testing — solo user, no need

---

## Cross-plan file / route inventory

Rough summary of touch surface — useful for estimating merge conflicts if plans get parallelized.

| File | Touched by |
|---|---|
| `turso_patch.py` | 00 |
| `db.py` schema | 00 (2 cols), A (3 tables + `error_log` cols + `bookmarks`), B (`test_mode`, `marked_for_review`), C (0 cols), D (7 cols + 2 tables), E (0 cols) |
| `bp_admin.py` | 00 (upload_import fix), D (review UI, dedupe UI) |
| `bp_tests.py` | A (SRS integration in submit flow), B (palette state, timer, mode-aware submit), C (mastery update tune) |
| `bp_analytics.py` | A (heatmap data endpoint), C (mastery grid, next-topic, pacing) |
| `bp_errorlog.py` | A (SRS due-cards route) |
| `bp_api.py` | A (bookmark toggle), E (structured flag categories) |
| `bp_main.py` | A (bookmarks list), C (dashboard hero card), E (flag form) |
| `templates/index.html` | C (hero card), E (dark toggle, mobile nav) |
| `templates/test.html` | A (bookmark star), B (palette, timer, shortcuts), E (flag radio, mobile layout) |
| `templates/test_setup.html` | A (PYQ toggle), B (mode toggle, neg-marking) |
| `templates/analytics.html` | A (heatmap), C (mastery grid, pacing, consistency), E (mobile layout) |
| `templates/errorlog.html` | A (SRS review link), E (mobile layout) |
| `templates/results.html` | B (per-question time, neg-marking breakdown), E (mobile layout) |
| `static/style.css` | B (palette + print @media), E (dark tokens + mobile media queries — massive rewrite) |
| `static/script.js` | A (star toggle, heatmap hover), B (palette state, timer tick, shortcuts) — biggest growth |
| `scripts/` (new dir) | 00 (migrate.py), D (backfill_question_metadata.py, dedupe helpers) |

`static/style.css` (737 L today) and `static/script.js` (145 L) are the highest-conflict files. Plan E's mobile pass alone could push CSS past 1500 lines. Consider extracting per-feature CSS files or a build step if it gets unwieldy.

---

## How to use this doc

- **Starting implementation?** Read `00-tech-debt.md` end-to-end, then come back here for the phase-1 checklist.
- **Deciding what to build next?** The "Recommended execution order" section above IS the queue. Pick the top-most unblocked phase.
- **A plan seems too big?** Each plan file has a "Quick-win first sprint" or equivalent 3-item quick-list at the top. Cherry-pick from there.
- **Something doesn't fit anymore?** Update this file and the plan it affects. Don't let stale plans drift.

---

_Written: 2026-07-17. Six plans totalling 4,560 lines. This roadmap is the seventh._
