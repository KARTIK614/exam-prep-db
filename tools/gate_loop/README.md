# GATE learning loop

Practice in the platform → diagnose mistakes with the tutor → turn them into Anki cards → review 15–20 min a day.

```
platform test (timed, confidence + one-line note per answer)
   └─► results + per-attempt data in Turso (time, answer, confidence, note, marks)
         └─► tutor review: diagnose each wrong / guessed answer, give it a mistake signature
               ├─► anki_push.py → "GATE" deck (AnkiConnect) → AnkiWeb → phone
               └─► whole question → platform review queue (Leitner 1/3/7/14/30 days)
```

## Platform support for GATE papers (v4)

- **Question types:** MCQ, MSQ (exact set, no partial credit) and NAT (inclusive range).
  - Keys live in `questions.correct_option`: `"B"`, `"A;C"`, `"2.5:2.6"`.
  - Grading: `backend/src/services/grading.rs`, mirrored in `frontend/src/lib/utils/grading.ts`.
- **Marking:**
  - Per-question `marks` and `neg_marks`. GATE rule: a wrong MCQ costs marks/3; a wrong MSQ or NAT costs nothing.
  - Practice mode never deducts.
- **Full papers:**
  - `POST /api/v1/tests {paper_code}` serves a whole paper in order; `GET /api/v1/papers` lists the papers.
  - Questions are images under `frontend/public/gate/<paper_code>/`, so maths and diagrams stay exactly as printed. The images never contain answers.
- **Per answer:** `confidence` (sure / unsure / guess), a `note` (≤ 500 chars, editable after finishing) and `marks_awarded`.
- **Test screen:** pause (P), auto-pause when the tab is hidden, and 50-minute active blocks with a 10-minute break screen.
- **Review queue:** fixed to match the Rust API (shape + `/review/answers/{id}`), and grades MSQ/NAT re-attempts.
- **DB connection:** the shared libSQL connection is replaced when idle > 4 s or after a `STREAM_EXPIRED` error. Before this, one expired Hrana stream made every later query fail.

## Deploy order (important)

The new backend selects the v4 columns, so **run the migration before the backend deploys**:

1. `python3 scripts/migrate_v4_gate_question_types.py --dry-run`, then run it without `--dry-run`. It is additive and idempotent, and the old code ignores the new columns.
2. Import the papers (below).
3. Merge → Render (backend) and Vercel (frontend + question images) deploy.

## Import an official paper

```bash
export TURSO_DB_URL=... TURSO_AUTH_TOKEN=...
python3 tools/gate_loop/import_gate_paper.py \
  --qp GATE2024_CS_S1_QP.pdf --key GATE2024_CS_S1_Key.pdf \
  --code GATE2024_CS_S1 --exam "GATE CS" --year 2024 \
  --source "GATE 2024 CS Set 1 (official, IISc)"
```

- **What it does:**
  - Crops each question from the PDF by its `Q.n` marker.
  - Removes the light-grey watermark and squeezes blank gaps (table borders are ignored).
  - Takes type, section, key and marks from the key PDF.
  - Upserts by `(paper_code, q_number)`.
- **Options:** `--images-only` or `--dry-run` skip the DB.
- **Known cosmetic loss:** light-grey fills in diagrams are whitened along with the watermark (e.g. one pie slice in CS 2024 S1 Q8; its label and outline remain).

## Anki

`anki_push.py cards.json` upserts cards by stable UID into the `GATE` deck (note type "GATE Card"), then syncs to AnkiWeb.
- Pushing an existing UID **updates** that card, which is how a repeated mistake rewrites its card.
- `"due_now": true` brings it back today.

`anki_push.py --report` lists:
- red/orange-flagged cards and leeches;
- daily review minutes against the 15–20 minute budget.

Anki must be running on the laptop: AnkiConnect listens on 127.0.0.1:8765 only.
