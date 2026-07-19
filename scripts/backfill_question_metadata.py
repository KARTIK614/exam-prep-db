#!/usr/bin/env python3
"""
Re-parse data/extracted_questions/*.json and backfill the 7 new columns
added by scripts/migrate_add_metadata_columns.py:

    confidence, section, sub_topic, pyq_exam, pyq_year, review_notes,
    (confidence_reviewed_at stays NULL — reviewer sign-off is a Sprint 2
    concern, not this script's job.)

Match strategy per Plan D §5:
    key = (question_text[:100], option_a[:50])
Ambiguous keys (more than one DB row) are reported but NOT updated —
those rows need §3's dedupe pass instead.

Idempotency:
    - confidence / section / sub_topic: writes only if DB value is NULL
      or differs from the JSON value.
    - pyq_exam / pyq_year: writes only if DB value is NULL, OR the JSON
      value is more specific (existing NULL year but JSON has year, etc).
    - review_notes: writes only if DB value is NULL.
    - explanation: writes the stripped version only if the current
      explanation ends with a `[Reviewer note: ...]` blob AND the note
      matches the JSON's `notes` field.

Usage:
    export TURSO_DB_URL=libsql://...
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/backfill_question_metadata.py --dry-run   # scan only
    python3 scripts/backfill_question_metadata.py             # apply
    python3 scripts/backfill_question_metadata.py --verbose   # print misses
"""
import os
import sys
import json
import glob
import time
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

if not os.environ.get("TURSO_DB_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
    sys.exit("ERROR: set TURSO_DB_URL and TURSO_AUTH_TOKEN before running.")

os.environ.setdefault("DB_PATH", os.path.join(BASE, "data", "exam_prep.db"))
import turso_patch  # noqa: F401
import sqlite3

from content_metadata import (
    metadata_from_json_question,
    extract_reviewer_note,
)


DATA_DIR = os.path.join(BASE, "data", "extracted_questions")

# 7 new columns must exist before this script runs.
REQUIRED_COLUMNS = {
    "confidence", "section", "sub_topic",
    "pyq_exam", "pyq_year", "review_notes",
    "confidence_reviewed_at",
}


def _preflight(con):
    rows = con.execute("PRAGMA table_info(questions)").fetchall()
    existing = {r[1] for r in rows}
    missing = REQUIRED_COLUMNS - existing
    if missing:
        sys.exit(
            "ERROR: questions table is missing columns "
            f"{sorted(missing)}. Run scripts/migrate_add_metadata_columns.py first."
        )


def _prefix_key(text, n):
    if text is None:
        return ""
    return text[:n]


def _execute_with_retry(con, sql, params=None, attempts=6, base_delay=1.5):
    """Wrap con.execute() with exponential-backoff retry on connection
    errors — the Hrana HTTP endpoint occasionally returns
    ECONNREFUSED / 'No route to host' under load. Non-connection errors
    (schema drift, bad SQL) still propagate immediately.
    """
    import requests  # requests is already a transitive dep via turso_patch
    last_err = None
    for i in range(attempts):
        try:
            if params is None:
                return con.execute(sql)
            return con.execute(sql, params)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_err = e
            delay = base_delay * (2 ** i)
            print(f"    ! transient network error, retry {i+1}/{attempts} in {delay:.1f}s: {type(e).__name__}")
            time.sleep(delay)
    raise last_err  # noqa: F821 — last_err set on first exception


def main(dry_run=False, verbose=False):
    con = sqlite3.connect(os.environ["DB_PATH"])
    _preflight(con)

    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
    print(f"Found {len(files)} JSON files under {DATA_DIR}")

    total_json = 0
    matched   = 0
    updated   = 0
    ambiguous_rows = []  # (json_key, db_ids)
    missed_rows    = []  # (fname, n, first-100-chars)
    exam_dist = Counter()
    conf_dist = Counter()

    for path in files:
        fname = os.path.basename(path)
        with open(path) as fh:
            data = json.load(fh)
        questions = data.get("questions", []) or []
        print(f"  {fname:32s}  {len(questions):5d} questions in JSON")

        for q in questions:
            total_json += 1
            qtext_key = _prefix_key(q.get("question_text", ""), 100)
            opta_key  = _prefix_key(q.get("option_a", ""), 50)

            # Prefix-match against DB.
            rows = _execute_with_retry(
                con,
                "SELECT id, explanation, confidence, section, sub_topic, "
                "pyq_exam, pyq_year, review_notes "
                "FROM questions "
                "WHERE substr(question_text, 1, 100) = ? "
                "  AND substr(option_a, 1, 50) = ?",
                (qtext_key, opta_key),
            ).fetchall()

            if len(rows) == 0:
                missed_rows.append((fname, q.get("n"), qtext_key[:60]))
                continue
            if len(rows) > 1:
                ambiguous_rows.append(
                    (fname, q.get("n"), [r[0] for r in rows], qtext_key[:60])
                )
                continue

            row = rows[0]
            matched += 1

            meta = metadata_from_json_question(q)
            conf_dist[meta["confidence"]] += 1
            if meta["pyq_exam"]:
                exam_dist[meta["pyq_exam"]] += 1

            # Compute the update set — only fields that need writing.
            fields = []
            values = []

            db_conf = row["confidence"]
            if db_conf != meta["confidence"]:
                # `high` is the DEFAULT so DB may already have it; only
                # override if the JSON explicitly disagrees (medium).
                if meta["confidence"] != "high" or db_conf in (None, "", "high"):
                    fields.append("confidence = ?")
                    values.append(meta["confidence"])

            if meta["section"] and row["section"] != meta["section"]:
                fields.append("section = ?")
                values.append(meta["section"])

            if meta["sub_topic"] and row["sub_topic"] != meta["sub_topic"]:
                fields.append("sub_topic = ?")
                values.append(meta["sub_topic"])

            if meta["pyq_exam"] and row["pyq_exam"] != meta["pyq_exam"]:
                fields.append("pyq_exam = ?")
                values.append(meta["pyq_exam"])

            if meta["pyq_year"] is not None and row["pyq_year"] != meta["pyq_year"]:
                fields.append("pyq_year = ?")
                values.append(meta["pyq_year"])

            # Explanation: strip `[Reviewer note:]` blob and split into
            # review_notes if the DB row still has it embedded.
            db_expl = row["explanation"] or ""
            stripped, note = extract_reviewer_note(db_expl)
            if note is not None:
                # We found a note to lift out. Prefer the JSON's notes
                # field as the canonical review_notes value when
                # available (it's the raw source), else use the parsed
                # note.
                canonical_note = meta["review_notes"] or note
                if row["review_notes"] != canonical_note:
                    fields.append("review_notes = ?")
                    values.append(canonical_note)
                if db_expl != stripped:
                    fields.append("explanation = ?")
                    values.append(stripped)
            elif meta["review_notes"] and row["review_notes"] != meta["review_notes"]:
                # Explanation doesn't carry the note (either it was
                # already stripped, or the note was never concatenated).
                # Still record the note.
                fields.append("review_notes = ?")
                values.append(meta["review_notes"])

            if not fields:
                continue  # nothing to write for this row

            if dry_run:
                updated += 1
                continue

            values.append(row["id"])
            _execute_with_retry(
                con,
                f"UPDATE questions SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            updated += 1

        # Commit after each JSON file — keeps progress durable if a
        # later Turso outage kills the run.
        if not dry_run:
            con.commit()

    print()
    print("=" * 60)
    print("Backfill summary")
    print("=" * 60)
    print(f"  JSON questions scanned : {total_json}")
    print(f"  Matched to a DB row    : {matched}")
    print(f"  Updated                : {updated}"
          + ("  (dry-run — no writes)" if dry_run else ""))
    print(f"  Missed (no DB row)     : {len(missed_rows)}")
    print(f"  Ambiguous (multi-match): {len(ambiguous_rows)}")
    if total_json:
        pct = 100.0 * matched / total_json
        print(f"  Match rate             : {pct:.1f}%")

    print()
    print("=== confidence values from JSONs (matched only) ===")
    for k, v in conf_dist.most_common():
        print(f"    {v:5d}  {k!r}")

    print()
    print(f"=== pyq_exam distribution ({len(exam_dist)} distinct) ===")
    for k, v in exam_dist.most_common(20):
        print(f"    {v:5d}  {k}")

    if ambiguous_rows:
        print()
        print("=== First 20 ambiguous rows (multi-match — need dedupe) ===")
        for fname, n, ids, preview in ambiguous_rows[:20]:
            print(f"    {fname:32s} Q{n}  db_ids={ids}  '{preview}...'")

    if missed_rows and (verbose or len(missed_rows) <= 30):
        print()
        print("=== Missed rows (no DB match) ===")
        for fname, n, preview in missed_rows[:60]:
            print(f"    {fname:32s} Q{n}  '{preview}...'")

    # Extra verification numbers, run against DB.
    print()
    print("=== Post-backfill DB counters ===")
    for label, sql in [
        ("count with pyq_exam NOT NULL",   "SELECT COUNT(*) FROM questions WHERE pyq_exam IS NOT NULL"),
        ("distinct pyq_exam values",       "SELECT COUNT(DISTINCT pyq_exam) FROM questions WHERE pyq_exam IS NOT NULL"),
        ("count with confidence='medium'", "SELECT COUNT(*) FROM questions WHERE confidence = 'medium'"),
        ("count with section NOT NULL",    "SELECT COUNT(*) FROM questions WHERE section IS NOT NULL"),
        ("count with sub_topic NOT NULL",  "SELECT COUNT(*) FROM questions WHERE sub_topic IS NOT NULL"),
        ("count with review_notes NOT NULL","SELECT COUNT(*) FROM questions WHERE review_notes IS NOT NULL"),
        ("total questions",                "SELECT COUNT(*) FROM questions"),
    ]:
        n = con.execute(sql).fetchone()[0]
        print(f"    {label:40s} {n:>6d}")

    con.close()

    # Guardrail: if we matched <90%, exit non-zero so caller stops.
    if total_json and matched / total_json < 0.90:
        pct = 100.0 * matched / total_json
        print()
        print(f"MATCH RATE {pct:.1f}% BELOW 90% THRESHOLD — investigate before pressing on.")
        return 2

    return 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv
    sys.exit(main(dry_run=dry_run, verbose=verbose))
