#!/usr/bin/env python3
"""
Phase 3 (Plan A F4) — create the `bookmarks` table + unique index.

Schema (matches docs/plans/A-study-effectiveness.md §4.4, simplified to the
task-3c spec):

    CREATE TABLE IF NOT EXISTS bookmarks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      question_id INTEGER REFERENCES questions(id),
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      note TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_bookmarks_qid ON bookmarks(question_id);

Idempotent — CREATE IF NOT EXISTS + CREATE UNIQUE INDEX IF NOT EXISTS.

Usage:
    export TURSO_DB_URL=libsql://...
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/migrate_add_bookmarks.py            # apply
    python3 scripts/migrate_add_bookmarks.py --dry-run  # print only
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


STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER REFERENCES questions(id),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        note TEXT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_bookmarks_qid ON bookmarks(question_id)",
]


def main(dry_run=False):
    con = sqlite3.connect(os.environ["DB_PATH"])

    print("Planned statements:")
    for s in STATEMENTS:
        print(f"  - {' '.join(s.split())[:120]}")

    if dry_run:
        print("\n--dry-run: not executing.")
        con.close()
        return 0

    for s in STATEMENTS:
        con.execute(s)
    con.commit()

    # Verify + report count.
    rows = list(con.execute("PRAGMA table_info(bookmarks)").fetchall())
    print("\n=== AFTER PRAGMA table_info(bookmarks) ===")
    for r in rows:
        print(f"  {r[0]:>2}  {r[1]:<15} {(r[2] or ''):<10} default={r[4]}")

    count = con.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
    print(f"\nbookmarks row count: {count}")

    print("\nOK — bookmarks table + index in place.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
