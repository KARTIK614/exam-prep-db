#!/usr/bin/env python3
"""
v4 — GATE question types (MCQ / MSQ / NAT), per-question marks, question
images, full-paper metadata, and per-answer confidence + note capture.

Additive only. Every new column is nullable or has a DEFAULT that keeps
existing RSSB rows behaving exactly as before:

  questions.qtype          TEXT DEFAULT 'MCQ'   MCQ | MSQ | NAT
  questions.marks          REAL DEFAULT 1       marks for a correct answer
  questions.neg_marks      REAL                 marks lost on a wrong answer in
                                                exam mode. NULL = use the test's
                                                negative_ratio × marks (old rule).
  questions.image_url      TEXT                 question rendered as an image
                                                (official papers: math + diagrams)
  questions.paper_code     TEXT                 e.g. GATE2024_CS_S1 — a full paper
  questions.q_number       INTEGER              question number inside the paper
  questions.paper_section  TEXT                 e.g. GA / CS / DA (exam section)

  test_responses.note          TEXT   the student's one-line "why I chose this"
  test_responses.answered_at   TEXT   ISO timestamp of the last answer change
  test_responses.marks_awarded REAL   marks scored for this question at finish

Answer encoding (no new column — `correct_option` / `selected_option` are
free TEXT already):
  MCQ  "B"         (several accepted answers: "A;B", marks to all: "MTA")
  MSQ  "A;C"       letters, sorted, ';'-separated
  NAT  "2.5:2.6"   inclusive range lo:hi (a single value is "6:6")

The existing `test_responses.confidence` column (default 'medium', never
written until now) starts receiving sure | unsure | guess.

Idempotent — PRAGMA-checks every column and skips the ones present.

Usage:
    export TURSO_DB_URL=libsql://exam-prep-db-pandit.aws-ap-south-1.turso.io
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/migrate_v4_gate_question_types.py --dry-run
    python3 scripts/migrate_v4_gate_question_types.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

if not os.environ.get("TURSO_DB_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
    sys.exit("ERROR: set TURSO_DB_URL and TURSO_AUTH_TOKEN before running.")

os.environ.setdefault("DB_PATH", os.path.join(BASE, "data", "exam_prep.db"))
import turso_patch  # noqa: F401 — monkey-patches sqlite3
import sqlite3


NEW_COLUMNS = [
    ("questions", "qtype", "ALTER TABLE questions ADD COLUMN qtype TEXT DEFAULT 'MCQ'"),
    ("questions", "marks", "ALTER TABLE questions ADD COLUMN marks REAL DEFAULT 1"),
    ("questions", "neg_marks", "ALTER TABLE questions ADD COLUMN neg_marks REAL"),
    ("questions", "image_url", "ALTER TABLE questions ADD COLUMN image_url TEXT"),
    ("questions", "paper_code", "ALTER TABLE questions ADD COLUMN paper_code TEXT"),
    ("questions", "q_number", "ALTER TABLE questions ADD COLUMN q_number INTEGER"),
    ("questions", "paper_section", "ALTER TABLE questions ADD COLUMN paper_section TEXT"),
    ("test_responses", "note", "ALTER TABLE test_responses ADD COLUMN note TEXT"),
    ("test_responses", "answered_at", "ALTER TABLE test_responses ADD COLUMN answered_at TEXT"),
    ("test_responses", "marks_awarded", "ALTER TABLE test_responses ADD COLUMN marks_awarded REAL"),
]

NEW_INDEXES = [
    ("idx_questions_paper",
     "CREATE INDEX IF NOT EXISTS idx_questions_paper ON questions(paper_code, q_number)"),
]


def _column_names(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


def main(dry_run=False):
    con = sqlite3.connect(os.environ["DB_PATH"])
    print("=" * 68)
    print(" v4 — GATE question types, marks, images, confidence + note")
    print("=" * 68)

    for table, col, sql in NEW_COLUMNS:
        if col in _column_names(con, table):
            print(f"[{table}] {col} already present — skip")
            continue
        print(f"[{table}] applying: {sql}")
        if not dry_run:
            con.execute(sql)

    for name, sql in NEW_INDEXES:
        print(f"[index] {name}: {sql}")
        if not dry_run:
            con.execute(sql)

    if dry_run:
        print("\n--dry-run: not executing.")
        con.close()
        return 0

    con.commit()

    missing = [(t, c) for t, c, _ in NEW_COLUMNS if c not in _column_names(con, t)]
    if missing:
        print(f"\nVERIFICATION FAILED — missing columns: {missing}")
        con.close()
        return 2
    print("\nVERIFICATION OK — all v4 columns present.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
