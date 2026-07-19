# Plan D — Content Quality

**Status:** Proposal — not implemented
**Scope:** Four features that raise the signal-to-noise of the 3,712-row question bank *without* re-running expensive PDF vision extractions.

1. **Bulk medium-confidence review UI** — one-pass triage of the 79 flagged rows (and any future ones).
2. **Duplicate detection** across the full 3,712 rows.
3. **Under-represented topic backfill** — a workflow, not a one-off ingest.
4. **Structured metadata recovery** — recover `section`, `sub_topic`, `pyq_exam`, `pyq_year`, `confidence` from the source JSONs and make them queryable.

**Author:** research fork, 2026-07-17. Planning only, no code changes.

**Prerequisite:** [Plan 00](00-tech-debt.md) Phase B adds `disabled` + `updated_at`
to Turso `questions` and makes `turso_patch` fail loud on schema drift. Every
`ALTER TABLE` in this document assumes those two columns already exist.

**Downstream unlock:** Plan A's "PYQ-only mode" filter requires `pyq_exam` and
`pyq_year` — see §5 for column-name commitments and how Plan A queries them.

---

## 0. TL;DR — Recommended Build Order

| # | Feature | Effort | Prereq | Why here |
|---|---------|--------|--------|----------|
| 1 | **Structured metadata recovery** (schema + one-shot backfill) | 4h | Plan 00 Phase A + B | Unblocks 2, 3, 4 — every other feature reads `confidence`/`section`/`pyq_year`. |
| 2 | **Bulk medium-confidence review UI** | 5h | #1 | 79 rows waiting today. Fixed-size backlog — get it done. |
| 3 | **Duplicate detection admin page** (trigram Jaccard + merge UI) | 6h | #1 | Payoff scales with corpus; do after metadata so we can merge intelligently (keep the PYQ, drop the non-PYQ dupe). |
| 4 | **Backfill workflow** (thin-topic report + synthesis loop) | 4h planning + open-ended execution | #1 (topic column integrity) | Long tail; needs the reviewer UI (#2) to police synthetic questions. |
| — | Update `upload_import` to preserve new metadata columns | +1h | #1 | Bundle into #1's PR. |

**Mandatory total:** ~19h across items 1–3. Item 4 is a workflow, not a fixed task.

**Recommended sequence:** all four in one branch, gated by #1 landing. #2 can ship the same day as #1 (they share the same schema fields). #3 needs a quality bar the reviewer UI provides. #4 is the long tail — plan it now, execute over weeks.

---

## Contents

1. [Current state of the 3,712 rows](#1-current-state-of-the-3712-rows)
2. [Feature 1 — Bulk medium-confidence review UI](#2-feature-1--bulk-medium-confidence-review-ui)
3. [Feature 2 — Duplicate detection](#3-feature-2--duplicate-detection)
4. [Feature 3 — Under-represented topic backfill](#4-feature-3--under-represented-topic-backfill)
5. [Feature 4 — Structured metadata recovery](#5-feature-4--structured-metadata-recovery)
6. [Competitor scan — content-quality workflows](#6-competitor-scan--content-quality-workflows)
7. [Effort estimates + implementation order](#7-effort-estimates--implementation-order)
8. [Rollout risks + rollback plans](#8-rollout-risks--rollback-plans)
9. [Out of scope](#9-out-of-scope)

---

## 1. Current state of the 3,712 rows

Grounded numbers from `data/extracted_questions/*.json` (13 files, 2,433 questions pushed by `push_extracted_to_turso.py`) plus the pre-existing 1,279 rows from `seed.py`.

### Corpus composition (post-push)

| Source | Rows | Method |
|--------|------|--------|
| `seed.py` hand-authored | 1,279 | Written by hand for Paper I + early Paper II topics |
| 13 extracted JSON files | 2,433 | Claude Opus 4.7 vision on scanned PDFs |
| **Total** | **3,712** | |

### Confidence distribution (from source JSONs)

```
$ grep -h '"confidence"' data/extracted_questions/*.json | sort | uniq -c | sort -rn
   2354  "confidence": "high"
     79  "confidence": "medium"
      0  "confidence": "low"
```

79 medium, zero low. But those 79 are the ones that will actively mislead study — every one has a `notes` field explaining an ambiguity, printing error, or answer-key conflict. Sampled examples:

- `U4_Ch2.json Q75`: "OCR of printed answer key was ambiguous between (A) and (B). Universally-accepted CS answer is (B) — flagged for reviewer to verify against physical PDF."
- `U8_Complete.json Q67`: "Textbook C but tree (B) is more common answer." (Q asks for the logical structure with 1-to-many relationship; both tree and chain are wrong-for-different-reasons.)
- `last_bci_paper_2022.json Q15`: "Textbook marks answer with [*] — both A and D (Gothic) are sans-serif. Ambiguous. Flagged."
- `last_bci_paper_2022.json Q97`: "Textbook explanation says ii, iii, iv are wrong (option would be B+iv). Answer key notation [*] is ambiguous."

These are the *good* kind of flags — they explain the disagreement rather than papering over it. `push_extracted_to_turso.py:88-89` flattens the `notes` field into `explanation` with a `[Reviewer note: ...]` prefix, so they're already visible to the user *at test time*. That's wrong for review workflow but right for transparency; the reviewer UI needs to lift them back out.

### Topic distribution (per `seed.py` topic table, IDs 25-42, Paper II)

Approximate row counts by joining `FILE_TOPIC` (in `push_extracted_to_turso.py:30`) and the hand-seeded `qs` array in `seed.py`:

| Topic ID | Name | Weightage | Approx rows | Comment |
|----------|------|-----------|-------------|---------|
| 25 | Computer Fundamentals | 10 | ~531 | Bloated — U5_Ch1 alone is 187 rows |
| 26 | Number Systems | 5 | ~20 | Thin |
| 27 | MS Office Suite | 8 | ~30 | Thin for weightage |
| 28 | Programming C/C++ | 8 | ~40 | Thin |
| 29 | OOP & Java | 5 | ~15 | Thin |
| 30 | Python Programming | 4 | 9 | **Critical** |
| 31 | Data Structures | 8 | ~380 | Fine |
| 32 | Algorithms | 5 | 4 | **Critical** |
| 33 | DBMS & SQL | 10 | ~360 | Fine |
| 34 | Operating System | 8 | ~280 | Fine |
| 35 | Computer Networks | 8 | ~215 | Fine |
| 36 | Network Security | 5 | ~230 | Bloated for weightage (Paper II reality: Security is 5%) |
| 37 | Web Technologies | 5 | ~5 | **Critical** |
| 38 | System Analysis & Design | 4 | ~285 | Bloated for weightage |
| 39 | IoT & Emerging Tech | 3 | 9 | Thin but weightage-appropriate |
| 40 | Pedagogy & Teaching | 5 | ~20 | Thin |
| 41 | Computer Organization | 5 | ~410 | Bloated (U5_Ch2 + U5_Ch4) |
| 42 | AI & Machine Learning | 3 | ~5 | Thin but weightage-appropriate |

Danger tier ("weightage ≥ 5 and rows < 20"): **32 Algorithms, 30 Python, 37 Web Tech, 40 Pedagogy, 29 OOP&Java, 26 Number Systems, 27 MS Office, 28 C/C++.** Nine topics with 116 combined rows against 45+ combined weightage points. §4 addresses this.

### Section values inside JSONs (not currently stored in Turso)

The JSONs have a `section` field with ~40 distinct values (`DBMS`, `DBMS-PYQ`, `SAD`, `OS`, `Tree`, `Ch5 - OSI Model`, etc.). These are chapter-level sub-topics *and* PYQ tags collapsed together. Any question with `section` ending in `-PYQ` or starting with `PYQ` is a past-year question — 505 rows total by grep. Currently that PYQ signal is *lost* on push: `push_extracted_to_turso.py:84-89` reads `section` only for topic disambiguation in `U5_Ch2_Ch3.json`, then discards it.

### `source` field state

`source` in the JSON contains gold data like `"PYQ RPSC Programmer"`, `"BCI 18 June 2022 Q91"`, `"DSSSB PGT 2018"`. On push, `push_extracted_to_turso.py:86` writes it verbatim to `questions.source` when non-null, else `f"pdf:{src_pdf}"`. So `source` is preserved but is unstructured free text — not filterable as "give me all PYQs from 2022" without regex gymnastics.

### The core content-quality problem

Three parallel data losses on push:

1. **`confidence`** field dropped entirely — reviewer can't SELECT medium-confidence rows.
2. **`notes`** field concatenated into `explanation` — user sees `[Reviewer note: ...]` at test time; reviewer can't SELECT rows-with-notes cleanly.
3. **`section`** field dropped, taking sub-topic granularity and the PYQ-tag with it.

Item #1 (structured metadata recovery) fixes all three at once by adding columns and re-parsing JSONs. Everything else builds on that.

---

## 2. Feature 1 — Bulk medium-confidence review UI

### What it is

An admin page — `/admin/review` — that lists every question where `confidence != 'high'` OR `explanation LIKE '%[Reviewer note:%'`, with inline edit for correct answer + explanation and one-click "confirm high / disable question / mark good enough". One-pass triage of the current 79 rows and any future medium flags.

### Why not use `question_flags` for this?

`question_flags` (`db.py:88-98`) exists for *user-reported* problems mid-test. It's the right table for "user during a test says this question is broken." It's the wrong table for "extraction-time uncertainty on 79 pre-existing rows." Two reasons:

- Populating `question_flags` for 79 rows on push means either creating a fake `reporter` value (breaks the audit semantics) or a NULL reporter (breaks `bp_admin.py:33`'s recent-flags widget which assumes reporter is present).
- The review workflow is different: extraction flags are single-shot, single-reviewer, close-out. User flags are dialogic (may need clarification, may recur across users). Same table hides those differences.

So: `question_flags` stays for user reports. A new source of triage state lives on `questions` itself as `confidence`. §5 adds it.

### Data model (assumes §5 has run)

`questions` already has `confidence` (from §5) and `explanation` may still contain `[Reviewer note: <text>]` prefixes. The reviewer UI reads both.

**Optional new columns (bundle with §5's ALTER):**

- `confidence_reviewed_at TEXT` — timestamp when the reviewer signed off; NULL means still-pending
- `confidence_reviewed_by TEXT` — username of the reviewer (for the eventual multi-admin case)

Not strictly needed if `confidence='high' AND updated_at IS NOT NULL` is enough of a signal. Recommend adding — cheap and disambiguates "was high all along" from "was medium, reviewer marked high on YYYY-MM-DD".

### Route + template plan

**Backend — new routes in `bp_admin.py`:**

```
GET  /admin/review                  → review queue list
POST /admin/review/<qid>/confirm    → confirm as high-confidence
POST /admin/review/<qid>/edit       → save corrected fields + set confidence=high
POST /admin/review/<qid>/disable    → sets disabled=1 (question hidden from tests)
POST /admin/review/<qid>/defer      → adds a `deferred` marker (see below)
```

`defer` is important — the reviewer may see a question, realise it needs a physical-PDF lookup, and not want to block on it. Store this as `confidence='deferred'` (a fourth value) or as a distinct `deferred_until TEXT` column. Recommend the value — no extra column, still filterable.

**Filter chips on the review page:**

```
[ Medium (79) ] [ With notes (79) ] [ Deferred (0) ] [ All non-high (79) ]
```

Numbers are live counts. Default filter: "Medium".

**Row layout in `templates/admin/review.html`:**

Each row is a card, not a table row — 79 rows is small enough to render full-detail cards and eye-scan them. Card includes:

```
┌────────────────────────────────────────────────────────────┐
│ Q#847 · DBMS · U8 · [medium]                    [confirm] │
│                                                             │
│ Statement 1: The entity that has a Primary Key is called—  │
│                                                             │
│ (A) Strong Entity     ← currently marked correct           │
│ (B) Weak Entity                                             │
│ (C) Partial Entity                                          │
│ (D) Regular Entity                                          │
│                                                             │
│ Explanation: Strong entity has PK.                          │
│ [Reviewer note: Textbook says A but "Regular Entity" is   │ ← highlighted
│   also common CS terminology.]                              │
│                                                             │
│ Source: pdf:U8 Complete Mcqs .pdf                          │
│                                                             │
│  [ Confirm as High ] [ Edit ] [ Disable ] [ Defer ]        │
└────────────────────────────────────────────────────────────┘
```

The `[Reviewer note: ...]` block is visually highlighted (light-yellow background). One-click "Confirm as High" is the fast path — for 60% of the 79 rows, Kartik will read the note, agree with the textbook, and confirm. Only the remaining ~30 need the Edit modal.

**Keyboard shortcuts on the review page:**

Because it's a 79-item queue and Kartik will do it in one sitting:

- `J` / `↓` — next card, `K` / `↑` — previous card
- `Enter` — Confirm as High
- `E` — Edit modal
- `D` — Disable
- `S` — Defer ("skip")
- `?` — cheat sheet

Same key set as Anki's card review (`Enter=Good`, `1-4=grades`) — muscle memory carries over. Model: 79 cards @ ~15 seconds/card via keyboard = 20 minutes. Compare against a mouse-only workflow (~2 minutes/card = 2.5 hours).

**Confirm-as-high side effects:** UPDATE `confidence='high'`, `confidence_reviewed_at=now`, `updated_at=now`; then strip the `[Reviewer note:...]` block from explanation in Python (SQLite has no regexp), only if the trailing regex `\s*\[Reviewer note:.+?\]\s*$` matches — otherwise leave alone. Preserve the raw note in `review_notes TEXT` for audit history (§5 adds this column).

**Edit modal:**

Full form with option_a/b/c/d, correct_option, explanation, difficulty, topic_id fields. Submit sets `confidence='high'` implicitly (editing is a stronger commitment than confirming). Reuse `templates/admin/question_edit.html` — it already does everything except stripping the reviewer-note prefix, which we do server-side in the POST handler.

### Sanity-check queries (run before shipping)

- `SELECT COUNT(*) FROM questions WHERE confidence = 'medium'` — verify the "79 rows" figure post-migration
- `SELECT COUNT(*) FROM questions WHERE confidence='high' AND explanation LIKE '%[Reviewer note:%'` — expect 0; non-zero means backfill missed rows
- `SELECT id, question_text FROM questions WHERE confidence='medium' AND confidence_reviewed_at IS NULL` — post-session, expect empty (or just the deferred rows)

### Effort

- Schema (bundle with §5): 20min
- Backend routes: 1h
- Template: 1.5h
- Keyboard shortcut JS: 30min
- Testing (walk through 5-10 real cards): 30min
- Documentation of the workflow: 15min

**Total: 4-5h.**

---

## 3. Feature 2 — Duplicate detection

### Why it matters

Sampled evidence: `last_bci_paper_2022.json Q75` and `U4_Ch2.json Q?` both ask about Locality of Reference, both are labeled `PYQ`, both have "medium" confidence. When Kartik takes a mock test filtered to "Data Structures" topic, seeing the same PYQ twice inflates his confidence and wastes a slot that could have been a fresh question. Multiply that across 505 PYQs and the practice-set signal degrades.

Two duplication modes to detect:

1. **Exact / near-exact restatements** — the same PYQ appears in multiple chapter PDFs. Should be merged to a single canonical row.
2. **Reworded restatements** — same fact, different sentence. Kartik should see one, not both.

### Evaluated approaches

| Approach | Precision | Recall | Cost | SQL-doable | Verdict |
|----------|-----------|--------|------|------------|---------|
| Exact string match on `question_text` | Very high | Very low — misses 90% of dupes because whitespace / punctuation / bilingual suffix differs | Free | Yes, `GROUP BY question_text` | Not enough alone. Use as a first pass. |
| Normalized exact match (lowercase, strip punctuation, collapse whitespace, strip Hindi) | High | Low — still misses paraphrases | Free | Yes with `LOWER` + `REPLACE` chains | Better than raw exact but still misses reworded pairs. Use as second pass. |
| Levenshtein distance (Python `python-Levenshtein`) | Medium | Medium — good on 1-3 word paraphrases | O(n²) = 6.9M pairs at 3,712 rows | No (extension needed) | Too slow for interactive review. Fine for a batch nightly job. |
| Fuzzy ratio (SequenceMatcher, ratio > 0.85) | Medium-high | Medium | O(n²), ~10min in Python for 3712 rows | No | Same latency profile as Levenshtein. Batch only. |
| **Trigram Jaccard similarity** | **Medium-high** | **Medium-high** — catches word-reorderings and small edits | **Fast — set intersection** | **Yes (with a helper table)** | **Recommended.** |
| Embedding cosine (Voyage / OpenAI / local sentence-transformers) | Very high | Very high — catches semantic paraphrases | $$: 3,712 embeds ≈ $0.01 one-time; latency 30s | No, needs vector store | Best quality but overkill for 3,712 rows and adds an API dependency. Revisit only if trigram gives too many false negatives. |

### Recommendation: Trigram Jaccard with a helper table

Compute character trigrams over normalized `question_text` (lowercase, strip Hindi, collapse whitespace, strip punctuation). Two rows with trigram-set overlap ≥ 0.6 are candidate duplicates. Store trigrams in a helper table so we don't recompute on every review-page load.

**Schema addition:**

```sql
CREATE TABLE IF NOT EXISTS question_trigrams (
    question_id INTEGER REFERENCES questions(id),
    trigram TEXT,
    PRIMARY KEY (question_id, trigram)
);
CREATE INDEX IF NOT EXISTS idx_trigrams_trigram ON question_trigrams(trigram);
```

At 3,712 rows × ~150 trigrams/row = 556K rows. Fine for Turso.

**Population script — `scripts/build_trigram_index.py`:**

```python
def trigrams(text):
    # 1. Strip bilingual suffix (everything after \n)
    text = text.split("\n")[0]
    # 2. Lowercase
    text = text.lower()
    # 3. Strip punctuation to spaces
    text = re.sub(r"[^\w\s]", " ", text)
    # 4. Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # 5. Char trigrams over the normalized text
    return set(text[i:i+3] for i in range(len(text) - 2))

rows = con.execute("SELECT id, question_text FROM questions").fetchall()
for row in rows:
    grams = trigrams(row["question_text"])
    con.executemany(
        "INSERT OR IGNORE INTO question_trigrams (question_id, trigram) VALUES (?, ?)",
        [(row["id"], g) for g in grams]
    )
```

**Detection query — pairs with Jaccard ≥ 0.6:**

```sql
WITH pairs AS (
    SELECT a.question_id AS q1, b.question_id AS q2,
           COUNT(*) AS intersection_size
      FROM question_trigrams a
      JOIN question_trigrams b
        ON a.trigram = b.trigram
       AND a.question_id < b.question_id
     GROUP BY a.question_id, b.question_id
    HAVING intersection_size >= 10          -- prune obvious non-matches
),
sizes AS (
    SELECT question_id, COUNT(*) AS n
      FROM question_trigrams
     GROUP BY question_id
)
SELECT p.q1, p.q2,
       CAST(p.intersection_size AS REAL) /
       (s1.n + s2.n - p.intersection_size) AS jaccard,
       q1.question_text AS text_1,
       q2.question_text AS text_2
  FROM pairs p
  JOIN sizes s1 ON s1.question_id = p.q1
  JOIN sizes s2 ON s2.question_id = p.q2
  JOIN questions q1 ON q1.id = p.q1
  JOIN questions q2 ON q2.id = p.q2
 WHERE CAST(p.intersection_size AS REAL) /
       (s1.n + s2.n - p.intersection_size) >= 0.6
 ORDER BY jaccard DESC;
```

Second `q1.question_id < q2.question_id` filter avoids self-pairs and double-counting. `intersection_size >= 10` is a cheap pre-filter — a real duplicate at 150 trigrams shares ≥90; 10 is very conservative and just kills the O(n²) blowup on unrelated pairs.

Expected result on 3,712 rows: 100-400 candidate pairs. Manageable in a UI.

### Admin UI — `/admin/duplicates`

Simple two-column diff view per candidate pair:

```
┌───────────────────────────────────────────────────────────────┐
│ Pair #14  jaccard=0.82                                        │
├───────────────────────────────────────────────────────────────┤
│ Q #1204                        │ Q #2891                      │
│ Topic: Data Structures         │ Topic: Data Structures       │
│ PYQ: RPSC Programmer 2019      │ PYQ: — (blank)               │
│ Source: pdf:U4_Ch2.json        │ Source: seed.py              │
├────────────────────────────────┼──────────────────────────────┤
│ What is the time complexity    │ What is the worst-case time  │
│ of the binary search           │ complexity of binary search  │
│ algorithm on a sorted array?   │ on a sorted array of n?      │
│                                │                              │
│ (A) O(n)                       │ (A) O(n)                     │
│ (B) O(log n) ✓                 │ (B) O(log n) ✓               │
│ ...                            │ ...                          │
├────────────────────────────────┴──────────────────────────────┤
│ [ Keep #1204, disable #2891 ] [ Keep #2891, disable #1204 ]   │
│ [ Keep both (not a dupe) ] [ Merge into new ]                 │
└───────────────────────────────────────────────────────────────┘
```

"Merge into new" opens the edit modal on Q #1204 pre-filled with the best fields of both — mostly useful when one has better explanation, the other has PYQ metadata.

**Which one to keep when the reviewer picks "auto-keep-better"?** Priority order:

1. Row with PYQ metadata (`pyq_exam` non-null) beats row without — PYQ is authoritative
2. `confidence='high'` beats `confidence='medium'`
3. Longer `explanation` (proxy for more effort put in)
4. Newer `updated_at` (reviewer has already touched it)

Encode this as a heuristic score and pre-select the winner. Reviewer overrides with one click.

### "Disable" vs "Delete" — soft-delete only

Never `DELETE FROM questions` — a row may be referenced by `test_responses`, `error_log`, `question_flags`. Set `disabled=1` (added in Plan 00 Phase B) and it won't be served by `bp_tests.py` question-selection queries but stays intact for historical joins.

**Add a foreign-key hygiene check:** on the duplicates page, show if the row-being-disabled has any `test_responses` — that's a signal Kartik has already answered it and disabling it will orphan analytics. UI: a small red badge "referenced in 3 tests" next to the disable button. Doesn't block; informs.

### Incremental updates

When a new PDF is imported through `upload_import`, trigger a background recompute for the new rows only:

```python
def compute_trigrams_for_new_rows(db, new_ids):
    for qid in new_ids:
        row = db.execute("SELECT question_text FROM questions WHERE id=?", (qid,)).fetchone()
        grams = trigrams(row["question_text"])
        db.executemany(
            "INSERT OR IGNORE INTO question_trigrams (question_id, trigram) VALUES (?, ?)",
            [(qid, g) for g in grams]
        )
    db.commit()
```

Called from `bp_admin.py:upload_import` after the INSERT loop finishes. Fast — ~150 inserts × ~20 new questions = 3,000 rows.

### Effort

- Trigram helper table + `build_trigram_index.py`: 1.5h
- Detection SQL wrapped in a Flask route: 1h
- Admin template with pair-view + action buttons: 2h
- "Keep-better" heuristic + wire-up: 45min
- Incremental hook in `upload_import`: 30min
- Testing on real data — spot-check 20 pairs: 30min

**Total: ~6h.**

### Edge cases to acknowledge in the code

- **Bilingual questions** — `question_text` often has `English\nHindi`. Strip the `\n...` suffix before trigraming (see `trigrams()` step 1) else the Hindi half dominates.
- **Match-column questions** — `Match List-I (Data Models) with List-II ...` — these are format-similar but not content-similar. Trigram Jaccard will falsely flag many of these. Trigger warning: expect ~50 false positives from this pattern. Reviewer will click through them.
- **Very short questions** — questions under 50 chars have too few trigrams and any pair looks similar. Filter: only compare pairs where both `question_text` are ≥50 chars.

---

## 4. Feature 3 — Under-represented topic backfill

### What "under-represented" means numerically

From §1's topic distribution, the danger tier is:

| Topic ID | Name | Weightage | Rows | Deficit |
|----------|------|-----------|------|---------|
| 32 | Algorithms | 5 | 4 | -46 |
| 37 | Web Technologies | 5 | ~5 | -45 |
| 30 | Python Programming | 4 | 9 | -31 |
| 40 | Pedagogy & Teaching | 5 | ~20 | -30 |
| 26 | Number Systems | 5 | ~20 | -30 |
| 29 | OOP & Java | 5 | ~15 | -35 |
| 27 | MS Office Suite | 8 | ~30 | -50 |
| 28 | Programming C/C++ | 8 | ~40 | -40 |

**Deficit calculation:** minimum viable pool = `weightage × 10`. Rationale: at weightage 5, an exam pulls 5 questions from this topic. To get a reasonable range of practice questions and not repeat the same 5 across mock tests, we want ~50 rows. Weightage 8 → 80. This is roughly what the well-covered topics have (DBMS at weightage 10 has 360 rows — 4.5x the minimum).

Total deficit: **~307 rows** to bring the corpus to a reasonable floor.

### Three fill options — evaluated

**Option A — More PYQ scraping**

Sources for Rajasthan Basic Computer Instructor / adjacent exams:

- **rpsc.rajasthan.gov.in** — official PYQs, but only recent papers as PDF scans; not machine-readable
- **Testbook.com / Adda247 / Career Power** — user-uploaded question banks; quality varies, licensing murky
- **Old physical books** — YCT, Kiran Prakashan, ATP publish exam-prep books with hundreds of PYQ compilations. These are what we already scanned for extraction.
- **RPSC Programmer / Senior Computer Instructor** exams — same subject syllabus, so PYQs transfer. Already partially represented (`PYQ RPSC Programmer` appears 42 times).
- **DSSSB PGT Computer Science** — Delhi exam, overlapping syllabus.

**Verdict:** PYQ scraping has diminishing returns. The books Kartik owns have been extracted. Downloading random PDFs from Testbook has quality/licensing issues. But there are two high-yield sources not yet extracted:

- Old BCI papers (2018, 2019) if available in scan form
- RPSC Programmer PYQ compilations for 2015-2020

Both need physical PDFs — not something to promise without them in hand.

**Option B — Synthetic questions via Claude, few-shot on existing PYQs**

For Algorithms (topic 32, 4 rows), we already have ~40 high-quality Data Structures questions (topic 31) that use similar formats and patterns. Show Claude 10 existing Algorithms-adjacent questions as few-shot and ask it to generate 20 new Algorithms MCQs on specified sub-topics.

**Advantages:**
- Fills the pool fast
- Can target sub-topics precisely (`sorting`, `graph algorithms`, `time complexity`)
- Zero licensing worry — original content

**Disadvantages:**
- Not "gold" PYQ material — actual exam won't have these exact questions
- Hallucination risk: Claude can generate plausible-looking wrong answers or subtly wrong explanations
- Kartik needs to trust the reviewer UI (§2) to catch bad generations

**Quality control workflow (critical):**

```
1. Prompt Claude to generate 20 MCQs at a time with source="synthetic" and confidence="medium".
   Never confidence="high" — force them through review.
2. The reviewer UI (§2) surfaces them alongside the extraction-medium queue.
3. Kartik reviews each: confirm/edit/disable. Roughly 15 sec each = 5 min per batch of 20.
4. Rate-limit generation: 20 per topic per week. Prevents flooding the review queue.
```

**Prompt sketch:**

```
You are an expert exam-question writer for the Rajasthan Basic Computer
Instructor exam (Paper II).

Below are 10 existing MCQs on {topic}, drawn from previous exams. Study the
style, difficulty distribution (~30% easy, 50% medium, 20% hard), the
bilingual English + Hindi format, and the level of explanation detail.

<existing_questions>
{{...}}
</existing_questions>

Generate 20 NEW multiple-choice questions on {topic}, covering the sub-topics:
{sub_topics}. Each question must:
- Be answerable from general CS knowledge at the level of the syllabus (never
  ask about brand-new tech, specific vendors, or trivia).
- Have exactly 4 options, one clearly correct.
- Include a 1-3 sentence explanation.
- Include an English question. Hindi translation is optional — mark
  needs_translation:true if omitted.
- Have "source": "synthetic-v1", "confidence": "medium".

Return JSON with the same shape as U8_Complete.json.
```

Model choice: **claude-opus-4-7 for generation, claude-sonnet-4-6 for translation.** Opus is worth the cost for content quality when we're targeting a static bank; sonnet is enough for mechanical English→Hindi.

**Option C — More extracted PDFs from Kartik's collection**

Ask Kartik: are there physical books / PDFs of PYQs for Algorithms, Python, Web Tech that haven't been scanned yet? If yes, run them through the existing `/admin/uploads` flow. This is the highest-quality fill but depends on inventory.

### Recommended workflow — hybrid

```
Phase 1 (week 1): Inventory
├─ Kartik lists any PYQ PDFs he owns that haven't been extracted.
│  (Focus: Algorithms, Web Tech, Python, MS Office, C/C++.)
├─ Run through /admin/uploads for the thin-topic ones.
└─ Ideal outcome: recover 100+ rows on these topics from real PYQs.

Phase 2 (week 2-3): Targeted synthesis for remaining deficit
├─ For each topic still under the floor, generate 20 synthetic MCQs per week.
├─ Route them through the reviewer UI (§2).
├─ Track a "% synthetic in this topic" — cap at 40% per topic to keep
│  the practice pool anchored to real PYQs.
└─ Ideal outcome: hit 50-row floor on the 5-weightage topics within
   3-4 weeks of casual review time.

Phase 3 (ongoing): Backfill dashboard tile
├─ On the admin dashboard, surface a small "topic-fill" tile:
│  each danger-tier topic gets a progress bar (rows_present / rows_target).
├─ Warm colour when < 50% of target; green when ≥ 100%.
└─ Kartik glances at it weekly; decides whether to run more synthesis.
```

### Backfill queries to expose

**Thin-topic report** — run daily by admin dashboard:

```sql
SELECT t.id, t.name, t.weightage,
       COUNT(q.id) AS n_rows,
       t.weightage * 10 AS target,
       CAST(COUNT(q.id) AS REAL) / (t.weightage * 10) AS coverage_ratio,
       COUNT(CASE WHEN q.source = 'synthetic-v1' THEN 1 END) AS n_synthetic
  FROM topics t
  LEFT JOIN questions q ON q.topic_id = t.id
       AND (q.disabled IS NULL OR q.disabled = 0)
 WHERE t.paper = 'II'
 GROUP BY t.id, t.name, t.weightage
 ORDER BY coverage_ratio ASC;
```

Row where `coverage_ratio < 0.4` → warm colour on dashboard. `n_synthetic > 0.4 * n_rows` → warn "over 40% synthetic — mix in real PYQs."

**Synthesis-batch tracker table:**

```sql
CREATE TABLE IF NOT EXISTS synthesis_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER REFERENCES topics(id),
    generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    n_generated INTEGER,
    n_approved INTEGER DEFAULT 0,
    n_disabled INTEGER DEFAULT 0,
    n_pending INTEGER DEFAULT 0,
    prompt_hash TEXT,
    model TEXT
);
```

Lets us track "approval rate by prompt version" — if a prompt tweak improves review pass-rate from 60% to 85%, we know to keep it.

### Effort

Backfill is a *workflow*, not a fixed task. Planning + tooling:

- Thin-topic report SQL + dashboard tile: 1h
- Synthesis batch route (`/admin/synthesize/<topic_id>`) — takes topic ID, calls Claude via `ai_anthropic.py`, tags results, writes to DB with `confidence='medium'`: 2h
- `synthesis_batches` table + write hooks: 30min
- Prompt engineering + few-shot selection logic: 1h
- Documentation for the "how to run a synthesis batch" workflow: 30min

**Tooling total: ~5h.** Then the execution is measured in Kartik-review-minutes per week, not engineering hours.

### Not doing (and why)

- **Auto-generation without human review.** Never. Even at claude-opus quality, 5% wrong-answer rate applied to a 300-question fill = 15 misleading questions Kartik would internalize. Human review is non-negotiable.
- **Community-sourced questions.** Not applicable — this is a single-user platform.
- **Scraping Testbook / Adda247.** Licensing + quality-verification cost outweighs the yield when Claude synthesis is available.

---

## 5. Feature 4 — Structured metadata recovery

### Data currently lost on push

Recap of §1 findings. On `push_extracted_to_turso.py`:

| JSON field | Destination | Loss |
|------------|-------------|------|
| `question_text`, `option_a-d`, `correct_option` | Direct columns | None |
| `explanation` | `explanation` | None |
| `notes` | Concatenated into `explanation` with `[Reviewer note:]` prefix | Semi-preserved but not queryable |
| `confidence` | (dropped) | **Total loss** |
| `source` | `source` | Preserved as free text |
| `section` | Only read for topic disambiguation, then discarded | **Total loss** for sub-topic + PYQ tagging |
| `difficulty` | `difficulty` | None |
| JSON top-level `topic_proposed.sub_topics` | (dropped) | Total loss (but same info per-question is in `section`) |
| JSON top-level `source_pdf` | Baked into `source` | Preserved indirectly |

### Schema evolution — new columns

Add to `questions`:

```sql
ALTER TABLE questions ADD COLUMN confidence TEXT DEFAULT 'high';
ALTER TABLE questions ADD COLUMN section TEXT;          -- raw JSON section value
ALTER TABLE questions ADD COLUMN sub_topic TEXT;        -- normalized sub-topic (see mapping)
ALTER TABLE questions ADD COLUMN pyq_exam TEXT;         -- normalized exam name, e.g. "RPSC Programmer"
ALTER TABLE questions ADD COLUMN pyq_year INTEGER;      -- 2018, 2022, etc. NULL if not a PYQ
ALTER TABLE questions ADD COLUMN review_notes TEXT;     -- extracted from [Reviewer note: ...] blob
ALTER TABLE questions ADD COLUMN confidence_reviewed_at TEXT;
```

**Idempotency:** the existing `db.py:_run_alter_migrations` pattern already handles this — just append the seven statements. Each `ADD COLUMN` fails silently on re-run (SQLite raises "duplicate column"; the except clause swallows it).

**Assumption on defaults:** `confidence='high'` for existing rows is the conservative wrong assumption — most were high, but 79 are medium. The backfill script overrides.

**Assumption on `pyq_exam`, `pyq_year`, `section`, `sub_topic`:** NULL by default; backfill fills for the 2,433 extracted rows. `seed.py`-authored 1,279 rows stay NULL for `section`/`sub_topic` (they have no section info) but may get `pyq_exam`/`pyq_year` filled where the hand-authored `explanation` mentions the source (e.g. `"RPSC 2nd Grade 2015 exam had this exact question"`). That's a stretch — probably leave those NULL and skip the regex-mining of explanations.

### One-shot migration script — `scripts/backfill_question_metadata.py`

The script reads `data/extracted_questions/*.json` and UPDATEs the DB rows via a prefix-match key `(question_text[:100], option_a[:50])`. Idempotent — only writes NULL → value. Requires `TURSO_DB_URL`, `TURSO_AUTH_TOKEN`.

**Three helpers live in a new `content_metadata.py` module (shared with `bp_admin.py`):**

- `SUBTOPIC_MAP: dict[str, str|None]` — curated section→sub_topic mapping. About 42 keys, covering the section strings seen in `grep '"section"' data/extracted_questions/*.json | sort -u`. Values collapse close variants (`DBMS` and `DBMS-PYQ` both → `"DBMS fundamentals"`). `"PYQ"` alone maps to `None` (generic tag, no sub-topic info).
- `is_pyq_section(section) -> bool` — true if section starts with `PYQ` or ends with `-PYQ`.
- `parse_pyq_source(src) -> (exam, year)` — regex-based parser handling the 20 observed source patterns:
    - Year: `re.search(r"(20\d{2})", src)` → int or None
    - Exam: strip `^PYQ\s+`, strip trailing `Q##`, strip trailing dates (`\d{1,2}[.\-]\d{1,2}[.\-]\d{2,4}`), strip trailing year
    - Normalize: `"Basic Computer Instructor"` → `"BCI"`, `"Informatics Assistant"` → `"Raj IA"`
- `extract_reviewer_note(explanation) -> (stripped, note)` — anchored regex `r"\s*\[Reviewer note:\s*(.+?)\]\s*$"` with DOTALL. Returns `(explanation, None)` when no match. Never strips unless the regex matches — this is the safety property that makes it safe to run against the whole table.

**Main loop pseudocode:**

```
for json_file in glob(DATA_DIR/*.json):
    for q in json_file["questions"]:
        rows = SELECT id, explanation FROM questions
               WHERE substr(question_text,1,100)=? AND substr(option_a,1,50)=?
        if len(rows) == 0: missed += 1; continue
        if len(rows) > 1:  ambiguous.append(...); continue
        row = rows[0]
        pyq_exam, pyq_year = parse_pyq_source(q["source"]) if is_pyq_section(q.get("section","")) or "PYQ" in (q.get("source") or "") else (None, None)
        stripped, note = extract_reviewer_note(row["explanation"] or "")
        UPDATE questions SET confidence=?, section=?, sub_topic=?,
             pyq_exam=?, pyq_year=?, review_notes=?, explanation=?
             WHERE id=?
```

**Expected first-run output on the 2,433 extracted rows:**

- Matched: ~2,400
- Missed: <30 (whitespace / normalization differences with what `push_extracted_to_turso.py` inserted)
- Ambiguous: ~5-20 (real duplicates that got inserted twice — signal for §3 to pick up)

For missed rows, add a `--verbose` flag that prints `question_text[:60]` — Kartik hand-matches the ~30 edge cases.

### Update `bp_admin.py:upload_import` to preserve new metadata

`bp_admin.py:396-413` currently writes 10 fields. Extend to 15 by adding `confidence`, `section`, `sub_topic`, `pyq_exam`, `pyq_year`, `review_notes` — populated by calling `SUBTOPIC_MAP.get(q["section"])` and `parse_pyq_source(q["source"])` from `content_metadata.py` (the same module the backfill script uses). Continue to concat the `[Reviewer note: ...]` block into `explanation` on insert — the reviewer UI (§2) strips it on confirm, not on import.

### Downstream: Plan A's PYQ-only mode filter

Plan A wants to filter mock tests to "PYQs only". After §5 lands, that filter is a one-line WHERE:

```sql
SELECT * FROM questions
 WHERE pyq_exam IS NOT NULL
   AND (disabled IS NULL OR disabled = 0)
   [AND topic_id = ?]
   [AND pyq_year >= ?]
```

Plan A can also add a "PYQ exam picker" (dropdown of distinct `pyq_exam` values). Committed column names Plan A can rely on:

- `pyq_exam TEXT` — normalized exam name, non-null iff row is a PYQ
- `pyq_year INTEGER` — year the PYQ was administered, may be NULL even when `pyq_exam` is set (e.g. `"PYQ RPSC Programmer"` with no year info)

If Plan A wants "PYQs from year >= 2020 only", the query works even for rows with NULL year — they'll be filtered out. Kartik should be aware of this if the results feel sparse; either add a "Include undated PYQs" toggle or backfill years by re-parsing the raw `source` when we have more info.

### Effort

- `content_metadata.py` shared module: 30min
- Schema `ALTER TABLE` additions in `db.py`: 15min
- `scripts/backfill_question_metadata.py`: 2h (bulk of parsing + testing)
- Turso migration (backup + run script + verify): 30min
- `bp_admin.py:upload_import` update: 45min
- Testing (grep-verify 5-10 pyq_exam / pyq_year rows): 30min

**Total: ~4h.** This is the highest-leverage 4 hours of the plan.

---

## 6. Competitor scan — content-quality workflows

Solo reviewer, no crowd, no votes. Which patterns transfer?

| Platform | Signature pattern | Applies here as | Reject |
|----------|-------------------|-----------------|--------|
| **Wikipedia** | `{{disputed}}` templates, category-as-queue, edit history | Reviewer-note prefix in `explanation` = `{{disputed}}` at read time; `WHERE confidence='medium'` = category queue; `updated_at` = mini edit history | Talk pages (no second reviewer), watchlist (nothing to watch) |
| **Stack Overflow** | Flag-review queue with fixed dismiss/close/delete states; duplicate marking picks canonical | State machine `open/resolved/dismissed` already exists on `question_flags`; Feature 2 "keep #A, disable #B" = SO's dupe-close | 5-vote thresholds, rep gates |
| **Anki shared decks** | Leech auto-tag (fail 8+ times), suspend-not-delete, keyboard-first review (`Space/1-4`) | Soft-delete via `disabled=1`; §2 keyboard shortcuts `J/K/Enter/E/D/S`; leech tag = future extension via `test_responses` error counts | Card/note split — MCQs are single-form |
| **Testbook / Adda247** | User "Report" button with fixed categories: wrong_answer / ambiguous / wrong_explanation / translation_error / other; silent multi-week backend triage | Category constraint on `question_flags.category` (currently free text); instant reviewer loop = solo advantage | Long resolution latency, opaque status |
| **MediaWiki dashboards** | Categorized backlogs with live counts on a maintainer landing page | Filter-chip counts `[Medium (79)] [With notes (79)] [Deferred (0)]` on `/admin/review`; topic-fill dashboard tile (§4) | Pending-changes review (two-writer), recent-changes patrol (community) |

### Distilled patterns applied

1. **Queue with fixed states** — Wikipedia categories = SO review queue = Anki leech = same idea. Feature 1 = queue for medium-confidence; Feature 2 = queue for dupe pairs.
2. **Keyboard-first review** — Anki's grade keys inspire §2's `J/K/Enter/E/D/S`.
3. **Soft-delete, never hard-delete** — Anki suspend + SO tombstoning = `disabled=1`.
4. **Transparent flags at read time** — Wikipedia `{{disputed}}` = the `[Reviewer note: ...]` blob currently sitting in `explanation`. Keep it visible until reviewer confirms.
5. **Categorized backlog counts** — MediaWiki-style live counts on admin dashboard.

### Explicitly rejected

Testbook's slow silent triage (solo → instant); Anki's card/note split (overkill); Wikipedia talk pages (no counterpart); SO rep gates (no rep system); any voting mechanism (crowd of one).

---

## 7. Effort estimates + implementation order

### Summary table

| # | Feature | Effort | Blocks | Blocked by |
|---|---------|--------|--------|------------|
| 1 | Structured metadata recovery (§5) | 4h | 2, 3, 4 | Plan 00 Phase A + B |
| 2 | Medium-confidence review UI (§2) | 4-5h | Frees 79 rows | 1 |
| 3 | Duplicate detection (§3) | 6h | Cleaner corpus | 1, 2 |
| 4 | Backfill workflow tooling (§4) | 5h + ongoing | — | 1, 2 |

**Mandatory total: ~19h.** Backfill *execution* (Kartik's actual review of synthetic questions) is measured in review-minutes, not engineering hours.

### Suggested sprint layout

- **Sprint 1 (one evening, ~5h):** §5 schema + metadata backfill. Biggest single unlock.
- **Sprint 2 (one evening, ~5h):** §2 review UI. Exit criteria: Kartik burns through the 79-row queue in one 25-min session.
- **Sprint 3 (one evening, ~6h):** §3 duplicate detection. Kartik reviews candidates in 2-3 sittings.
- **Sprint 4 (one evening, ~4h):** §4 backfill tooling. No generation execution yet.
- **Ongoing:** 20 min/week of synthesis review + report checking.

### Where to cut if time is short (10h budget)

Keep §5 in full and §2 review UI. Cut §3's admin page — run the trigram query as a one-off script, dump top 20 pairs as HTML, disable manually via `/admin/questions`. Cut §4 entirely; imbalance is annoying but not fatal.

### Where to expand if time is generous (25h+)

Audit log table for reviewer actions; nightly cron for §3 with email summary; Anki-style leech auto-tagging from `test_responses` error counts; explanation-length outlier detector (`LENGTH(explanation) < 20`).

---

## 8. Rollout risks + rollback plans

### Risk 1 — Metadata backfill matches the wrong row

Prefix-match `(question_text[:100], option_a[:50])` may not be unique for very short questions. Impact is cosmetic: ~5-20 rows with wrong `pyq_exam`/`section`. The script already skips ambiguous matches (reports them; doesn't UPDATE). Take a Turso `.dump questions` backup *before* running so rollback is `UPDATE questions SET confidence='high', section=NULL, sub_topic=NULL, pyq_exam=NULL, pyq_year=NULL, review_notes=NULL WHERE updated_at > <migration_ts>` plus a targeted re-INSERT of `explanation` from the dump.

### Risk 2 — Review UI accidentally clears explanation

The confirm-as-high action strips `[Reviewer note: ...]` from `explanation`. If the regex overreaches it deletes real content. Mitigation: anchor the regex to end-of-string (`$`), match only the exact template `push_extracted_to_turso.py:89` writes, unit-test before wiring. Belt-and-braces: copy pre-strip explanation into `review_notes` on every confirm — reversible by re-concat.

### Risk 3 — Trigram false positives fatigue the reviewer

400 candidate pairs where 380 are unrelated match-column or short-generic questions. Kartik gives up. Mitigation:
- Start Jaccard threshold at 0.7, not 0.6
- Filter out pairs where both start with `"Match "` (match-column pattern)
- Require both `question_text` ≥ 100 chars
- Sort descending Jaccard so the reviewer stops when precision drops

"Keep both" does not mutate data; even 380 noise clicks damage nothing.

### Risk 4 — Synthetic-question quality pollutes the practice pool

Synthesis approves 18/20; later 3 turn out subtly wrong. Kartik studies wrong facts — high-cost. Mitigation:
- Version the source tag (`source='synthetic-v1'`); bad batches disable via one UPDATE
- Cap synthetic ratio per topic at 40% — real PYQs anchor the pool
- Reject generations with `LENGTH(explanation) < 30`
- Track approval-rate per prompt version in `synthesis_batches`; retire prompts under 60%

Rollback: `UPDATE questions SET disabled=1 WHERE source LIKE 'synthetic-%';`.

### Risk 5 — Plan A depends on `pyq_year` semantics we haven't finalized

`pyq_year IS NULL` for ~30% of PYQ rows (source string had exam name but no year). Plan A's "PYQs from 2022+" filter would silently drop them. Options: strict (`>= 2022`), inclusive (`>= 2022 OR pyq_year IS NULL`), or user-toggle. Recommend user-toggle with "Include undated PYQs" defaulting to checked. Plan A must reference this explicitly.

### Risk 6 — Turso ALTER TABLE fails silently (Plan 00 Item #1)

**Scenario:** §5's `ALTER TABLE questions ADD COLUMN confidence TEXT DEFAULT 'high'` runs against Turso. Turso rejects it (unlikely — libSQL supports this). `turso_patch._post` swallows the error.

**Impact:** Migration script runs, thinks it succeeded, all subsequent UPDATEs fail with "no such column." Feature 1/2/3 all crash.

**Mitigation:** Plan 00 Phase A (surfacing Hrana errors) MUST land before this. Do not run this plan's migrations until Phase A is verified.

**Verification step to add to the migration script:** after ALTER, run `PRAGMA table_info('questions')` and assert every new column is present. Refuse to proceed otherwise.

---

## 9. Out of scope

Explicitly punted, so we don't argue about them mid-implementation:

- **Full audit log of every review action.** A `review_actions (id, question_id, actor, action, before_json, after_json, at)` table would be nice. Not building it now — solo user, low branch factor. Revisit if a second reviewer joins or if we ever need to prove a question was reviewed.
- **Multi-language quality checks.** Hindi translations are currently baked into `question_text` as `English\nHindi`. Detecting bad translations is a separate NLP problem — punt.
- **Embedding-based dupe detection.** Trigram Jaccard covers 90% of cases at zero API cost. Only revisit if we find systematic misses (semantic paraphrases not caught by trigram).
- **User-facing PYQ filter.** That's Plan A. This plan makes the *data* filterable; Plan A builds the *UI*.
- **Difficulty recalibration.** The extraction assigns `easy/medium/hard` based on the model's guess. Actual user performance would let us recalibrate. That's a Plan C (analytics) concern, not a content-quality one.
- **Automatic re-import if source PDF changes.** No plan to re-scan PDFs. If we do, `pdf_uploads.uploaded_at` gives us a re-run trigger — but we're not building watch-and-reimport.
- **Localized error messages / accessibility.** Belongs in a polish plan.

---

## 10. Execution checklist

Do these in strict order. Do not batch across sprints unless you're deliberately choosing to compress the review passes.

### Sprint 1 — Metadata recovery (§5)

- [ ] Confirm Plan 00 Phase A (turso_patch fix) is deployed. Do not skip.
- [ ] Confirm Plan 00 Phase B (`disabled` + `updated_at` on Turso) is deployed.
- [ ] `git checkout -b content-quality/metadata-recovery`
- [ ] Create `content_metadata.py` with `SUBTOPIC_MAP`, `parse_pyq_source`, `is_pyq_section`, `extract_reviewer_note`
- [ ] Unit tests for `parse_pyq_source` covering the 20 most common `source` strings from the JSONs
- [ ] Unit tests for `extract_reviewer_note` — must be strict about the anchor pattern
- [ ] Add 7 new ALTER TABLE statements to `db.py:_run_alter_migrations`
- [ ] Deploy schema change to Turso (via `db.init_db` on boot OR via a manual `scripts/migrate_metadata_columns.py`)
- [ ] Verify: `PRAGMA table_info('questions')` shows all 7 new columns
- [ ] Snapshot Turso before running the backfill:  `turso db shell exam-prep-db-pandit ".dump questions" > backups/pre-content-quality-metadata-$(date +%Y%m%d).sql`
- [ ] Write `scripts/backfill_question_metadata.py` per §5
- [ ] Run with `--dry-run`; verify matched count ≈ 2400, ambiguous list looks reasonable
- [ ] Run for real
- [ ] Verify: `SELECT COUNT(*) FROM questions WHERE confidence='medium'` returns ~79
- [ ] Verify: `SELECT DISTINCT pyq_exam FROM questions WHERE pyq_exam IS NOT NULL` returns a sensible list
- [ ] Verify: `SELECT COUNT(*) FROM questions WHERE explanation LIKE '%[Reviewer note:%' AND review_notes IS NULL` returns 0 (backfill covered them)
- [ ] Update `bp_admin.py:upload_import` to write the new columns
- [ ] Upload a small test PDF; verify new questions have populated `confidence`, `section`, etc.
- [ ] Merge to main, deploy

### Sprint 2 — Review UI (§2)

- [ ] `git checkout -b content-quality/review-ui`
- [ ] Add `/admin/review` route + template
- [ ] Add filter-chip counts to `/admin` dashboard tile
- [ ] Add `/admin/review/<qid>/confirm|edit|disable|defer` routes
- [ ] JS keyboard handlers
- [ ] Walk-through: review 5 real medium-confidence rows end-to-end
- [ ] Merge, deploy
- [ ] Kartik burns through the 79-row queue in one sitting (target: 25 minutes)
- [ ] Verify: after the session, `SELECT COUNT(*) FROM questions WHERE confidence='medium'` = 0 (or near-zero if any were deferred)

### Sprint 3 — Duplicate detection (§3)

- [ ] `git checkout -b content-quality/dedup`
- [ ] Add `question_trigrams` table to `db.py:SCHEMA`
- [ ] Add `ALTER`-idempotent statement for it in `_run_alter_migrations` (belt-and-braces — `CREATE TABLE IF NOT EXISTS` in SCHEMA already handles this on cold start)
- [ ] Write `scripts/build_trigram_index.py`
- [ ] Run it against Turso — verify `SELECT COUNT(*) FROM question_trigrams` is in the 400K-700K range
- [ ] Add `/admin/duplicates` route with the detection query
- [ ] Template with pair-diff view + action buttons
- [ ] "Keep-better" heuristic
- [ ] Hook into `bp_admin.py:upload_import` to compute trigrams for new rows
- [ ] Walk-through: review the top 10 candidates
- [ ] Merge, deploy
- [ ] Kartik reviews the queue in two or three sittings

### Sprint 4 — Backfill tooling (§4)

- [ ] `git checkout -b content-quality/backfill-tooling`
- [ ] Add `synthesis_batches` table
- [ ] Add thin-topic report SQL to `bp_admin.py:dashboard`
- [ ] Add topic-fill dashboard tile with colour-coded progress bars
- [ ] Add `/admin/synthesize/<topic_id>` route that calls `ai_anthropic.py`
- [ ] Draft the few-shot synthesis prompt in `content_metadata.py:SYNTHESIS_PROMPT`
- [ ] Test-generate 5 questions on Algorithms (topic 32); verify they land with `confidence='medium'`
- [ ] Verify they appear in the medium review queue
- [ ] Document the "how to run a synthesis batch" workflow at the top of `content_metadata.py`
- [ ] Merge, deploy

### Ongoing — weekly execution

- [ ] Every Monday: check the dashboard topic-fill tile
- [ ] For any topic with coverage_ratio < 0.4 and synthetic_ratio < 0.4: trigger a synthesis batch (20 rows)
- [ ] For any topic already at 40% synthetic: skip; wait for real PYQs
- [ ] Every Friday: burn through whatever's accumulated in the review queue (~5-10 minutes)

---

## 11. Effort summary

| Sprint | Effort | Risk | Value |
|--------|--------|------|-------|
| 1 — Metadata recovery | 4h | Low | Unblocks 2/3/4 + Plan A's PYQ filter |
| 2 — Review UI | 4-5h | Low | Frees 79 misleading rows |
| 3 — Duplicate detection | 6h | Medium (FP fatigue) | Cleaner practice pool |
| 4 — Backfill tooling | 5h | Medium (synthesis quality) | Long-term coverage floor |
| **Mandatory total** | **~19h** | | |
| Ongoing execution | ~30 min/week | Low | Sustains quality over time |

Not building anything means the 79 medium rows keep misleading Kartik, the ~200 duplicate pairs keep inflating false-confidence, and the 9 thin topics stay under-practiced. Cost of inaction is real.

Do Sprint 1 in one evening. Everything else can wait a week if needed.
