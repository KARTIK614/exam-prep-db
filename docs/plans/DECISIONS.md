# Pending design decisions

Six decisions to lock in before Phase 1 of implementation.
Tick the box next to your choice, edit the "Chosen" line, then start Phase 1.

Referenced from `docs/plans/README.md` "Key design decisions to lock in before starting".

---

## 1. Spaced repetition algorithm

Where used: **Plan A F1** (spaced repetition on wrong answers).

- [ ] **Leitner-5** — 5 boxes, cards move up on correct, back to box 1 on wrong. Simple, explainable, no per-card state beyond a box number.
- [ ] **SM-2** (Anki default) — ease factor + interval per card. More adaptive, more state to persist.
- [ ] **FSRS** — modern ML-derived; needs a lot of review history to tune. Overkill until you have thousands of reviews.

**Recommended:** Leitner-5. Fixed exam date + cold-start data + solo-dev maintenance all favor it.

**Chosen:** _____________

---

## 2. Streak system vs consistency score

Where used: **Plan C** (dashboard motivation feature).

- [ ] **Duolingo-style streak** — days in a row, resets to 0 if you miss one day
- [ ] **Consistency score** — 28-day rolling, weekend-friendly (20-day denominator so Sat/Sun off doesn't hurt)
- [ ] **No motivation metric at all**

**Recommended:** Consistency score. Kartik's Mon-Fri rhythm would break a strict streak in week one and demotivate.

**Chosen:** _____________

---

## 3. Question palette color convention

Where used: **Plan B** (test-taking UI palette).

- [ ] **TCS-iON convention** — matches real RPSC/SSC/IBPS exam interface (green=answered, red=not visited, purple=marked-for-review, blue=current, etc.)
- [ ] **Custom clean palette** — designer choice, may differ from what Kartik sees on exam day
- [ ] **Anki-style** — simple 2-color (done / not done)

**Recommended:** TCS-iON. UX-fidelity to exam-day muscle memory beats aesthetic preference.

**Chosen:** _____________

---

## 4. Search backend

Where used: **Plan E** (global question search).

- [ ] **libSQL FTS5** — server-side, ranked, sub-100ms on 3712 rows. Turso bundles it.
- [ ] **Client-side JSON filter** — ship the whole question bank to browser as JSON, filter in JS. Simpler backend, ~2MB payload.
- [ ] **Both** — start with FTS5, fall back to client if FTS5 breaks

**Recommended:** FTS5. Server-side ranked search is worth the small backend complexity for query quality.

**Chosen:** _____________

---

## 5. Synthetic question generation

Where used: **Plan D §4** (backfill under-represented topics).

- [ ] **Allow synthetic questions** — Claude generates fillers for topics with <20 rows, tagged `source='synthetic-v1'`, capped at 40% of any topic
- [ ] **PYQ-only, never synthetic** — accept coverage gaps, only add real past-year questions
- [ ] **Synthetic allowed but heavily flagged** — always shown with a "generated" badge in the UI

**Recommended:** Allow, with cap and versioned tagging (option 1).

**Chosen:** _____________

---

## 6. Token rotation urgency

Where used: **Plan 00** (tech debt).

- [ ] **Rotate now** — includes it in Phase 1
- [ ] **Deferred (current default)** — leave until broader secrets audit; two leaked tokens in git history + this session's transcript
- [ ] **Rotate before any public push** — if you push this repo to a public fork, rotate first

**Recommended:** Deferred if repo stays private, otherwise rotate. Both leaked tokens are in `project_turso_token_rotation.md` memory.

**Chosen:** _____________

---

## When all six are chosen

Update this file, commit, then:

```
Ready to start Phase 1 of docs/plans/README.md — I've locked in the decisions in DECISIONS.md.
```

That tells the assistant everything it needs to begin Plan 00 execution.

---

_Created: 2026-07-17. To be resolved: at home ~10 PM IST 2026-07-17._
