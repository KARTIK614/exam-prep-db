#!/usr/bin/env python3
"""
Plan D §3 — precompute character trigrams for every enabled question.

Populates the `question_trigrams` table so `/admin/duplicates` can execute
the Jaccard-similarity query without recomputing on every load.

Normalization per Plan D §3:
    1. Strip bilingual suffix (everything after first '\n')
    2. Lowercase
    3. Punctuation → space
    4. Collapse whitespace
    5. Emit char n-grams (n=3) as a set

Skip rows with normalized text < 20 chars (too short — trigram matching
on 5-10 grams produces noise).

Idempotency:
    INSERT OR IGNORE keeps re-runs safe. Rows already in the table for a
    given question_id are left alone (the assumption is question_text is
    immutable in practice — if it changes, run `--rebuild` to wipe that
    question's trigrams first).

Usage:
    export TURSO_DB_URL=libsql://...
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/build_trigram_index.py               # incremental
    python3 scripts/build_trigram_index.py --rebuild     # wipe + rebuild
    python3 scripts/build_trigram_index.py --dry-run     # report only
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

if not os.environ.get("TURSO_DB_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
    sys.exit("ERROR: set TURSO_DB_URL and TURSO_AUTH_TOKEN before running.")

os.environ.setdefault("DB_PATH", os.path.join(BASE, "data", "exam_prep.db"))
import turso_patch  # noqa: F401
import sqlite3

from content_metadata import compute_trigrams


def main(dry_run=False, rebuild=False):
    con = sqlite3.connect(os.environ["DB_PATH"])

    total_rows = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    active_rows = con.execute(
        "SELECT COUNT(*) FROM questions WHERE disabled IS NULL OR disabled=0"
    ).fetchone()[0]
    trigram_rows_before = con.execute(
        "SELECT COUNT(*) FROM question_trigrams"
    ).fetchone()[0]
    print(f"questions: total={total_rows} active={active_rows}")
    print(f"question_trigrams (before): {trigram_rows_before} rows")

    if rebuild and not dry_run:
        print("--rebuild: DELETE FROM question_trigrams")
        con.execute("DELETE FROM question_trigrams")
        con.commit()

    # Fetch all rows we intend to index. Skip disabled.
    rows = con.execute(
        "SELECT id, question_text FROM questions "
        "WHERE disabled IS NULL OR disabled=0"
    ).fetchall()

    # If not rebuilding, skip rows that already have trigrams.
    already = set()
    if not rebuild:
        for r in con.execute(
            "SELECT DISTINCT question_id FROM question_trigrams"
        ).fetchall():
            already.add(r[0])
        print(f"already indexed: {len(already)} questions (skipping)")

    to_index = [r for r in rows if r[0] not in already]
    print(f"to index: {len(to_index)} questions")

    if dry_run:
        print("--dry-run: not writing.")
        con.close()
        return 0

    total_grams = 0
    skipped_short = 0
    for i, r in enumerate(to_index):
        qid, qtext = r[0], r[1] or ""
        grams = compute_trigrams(qtext)
        if len(grams) < 20:
            skipped_short += 1
            continue
        params = [(qid, g) for g in grams]
        # Insert in a single executemany per question (~150 rows each).
        con.executemany(
            "INSERT OR IGNORE INTO question_trigrams (question_id, trigram) VALUES (?, ?)",
            params,
        )
        total_grams += len(params)
        if (i + 1) % 100 == 0:
            print(f"  ... {i+1}/{len(to_index)} questions, {total_grams} trigrams inserted")
    con.commit()

    trigram_rows_after = con.execute(
        "SELECT COUNT(*) FROM question_trigrams"
    ).fetchone()[0]
    print(f"\nquestion_trigrams (after):  {trigram_rows_after} rows")
    print(f"inserted:                    {total_grams} trigrams")
    print(f"skipped (< 20 grams):        {skipped_short} questions")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(
        dry_run="--dry-run" in sys.argv,
        rebuild="--rebuild" in sys.argv,
    ))
