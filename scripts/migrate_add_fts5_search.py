#!/usr/bin/env python3
"""
Phase 7 (Plan E §2.18) — global question search via FTS5.

Creates a libSQL/SQLite FTS5 virtual table `questions_fts` mirroring the
searchable text columns of `questions`, plus INSERT/UPDATE/DELETE triggers
that keep the index in sync. After the DDL is applied we rebuild the index
so existing rows are backfilled.

Idempotent:
  * `CREATE VIRTUAL TABLE IF NOT EXISTS` — safe re-run
  * Triggers use `CREATE TRIGGER IF NOT EXISTS`
  * The rebuild step is a no-op if the FTS content already matches (still
    fine to re-run; it just rescans).

Turso caveat:
  If Turso's libSQL build doesn't include FTS5 the CREATE VIRTUAL TABLE will
  fail. This script surfaces the error rather than silently swallowing it.
  In that case fall back to LIKE-based search in bp_main.py.

Usage:
    export TURSO_DB_URL=libsql://...
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/migrate_add_fts5_search.py            # apply
    python3 scripts/migrate_add_fts5_search.py --dry-run  # print only
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


DDL = [
    # Contentless FTS5 pointing at `questions` — Hrana/libSQL handles this.
    """CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts USING fts5(
        question_text, option_a, option_b, option_c, option_d, explanation,
        content='questions', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    )""",
    """CREATE TRIGGER IF NOT EXISTS questions_fts_ai AFTER INSERT ON questions
       BEGIN
         INSERT INTO questions_fts(rowid, question_text, option_a, option_b, option_c, option_d, explanation)
         VALUES (new.id, new.question_text, new.option_a, new.option_b, new.option_c, new.option_d, new.explanation);
       END""",
    """CREATE TRIGGER IF NOT EXISTS questions_fts_ad AFTER DELETE ON questions
       BEGIN
         INSERT INTO questions_fts(questions_fts, rowid, question_text, option_a, option_b, option_c, option_d, explanation)
         VALUES ('delete', old.id, old.question_text, old.option_a, old.option_b, old.option_c, old.option_d, old.explanation);
       END""",
    """CREATE TRIGGER IF NOT EXISTS questions_fts_au AFTER UPDATE ON questions
       BEGIN
         INSERT INTO questions_fts(questions_fts, rowid, question_text, option_a, option_b, option_c, option_d, explanation)
         VALUES ('delete', old.id, old.question_text, old.option_a, old.option_b, old.option_c, old.option_d, old.explanation);
         INSERT INTO questions_fts(rowid, question_text, option_a, option_b, option_c, option_d, explanation)
         VALUES (new.id, new.question_text, new.option_a, new.option_b, new.option_c, new.option_d, new.explanation);
       END""",
]

REBUILD = "INSERT INTO questions_fts(questions_fts) VALUES('rebuild')"


def _fts_exists(con):
    try:
        r = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='questions_fts'"
        ).fetchone()
        return bool(r)
    except Exception as e:  # noqa: BLE001
        print(f"[fts exists check] {e}")
        return False


def _fts_count(con):
    try:
        r = con.execute("SELECT COUNT(*) FROM questions_fts").fetchone()
        return int(r[0]) if r else 0
    except Exception as e:  # noqa: BLE001
        print(f"[fts count] {e}")
        return -1


def main(dry_run=False):
    con = sqlite3.connect(os.environ["DB_PATH"])

    print("=== BEFORE ===")
    print(f"  questions_fts exists: {_fts_exists(con)}")
    print(f"  questions_fts rows:   {_fts_count(con)}")
    try:
        n_q = int(con.execute("SELECT COUNT(*) FROM questions").fetchone()[0])
    except Exception as e:  # noqa: BLE001
        n_q = -1
        print(f"  questions count failed: {e}")
    print(f"  questions rows:       {n_q}")

    print("\nPlanned DDL:")
    for sql in DDL:
        line1 = sql.strip().split("\n", 1)[0]
        print(f"  + {line1}")
    print(f"  + {REBUILD}")

    if dry_run:
        print("\n--dry-run: not executing.")
        con.close()
        return 0

    for sql in DDL:
        print(f"\n  applying: {sql.strip().split(chr(10),1)[0]}")
        try:
            con.execute(sql)
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED: {e}")
            con.close()
            return 1
    con.commit()

    print("\n  applying: rebuild index")
    try:
        con.execute(REBUILD)
        con.commit()
    except Exception as e:  # noqa: BLE001
        print(f"  rebuild FAILED: {e}")
        # Continue — rebuild fails on some libSQL builds even after triggers work.
        # New questions will still index via triggers, existing rows may be missing.

    print("\n=== AFTER ===")
    print(f"  questions_fts exists: {_fts_exists(con)}")
    print(f"  questions_fts rows:   {_fts_count(con)}")

    # Smoke test — sample query.
    try:
        r = con.execute(
            "SELECT COUNT(*) FROM questions_fts WHERE questions_fts MATCH ?",
            ("computer",),
        ).fetchone()
        print(f"  smoke test: MATCH 'computer' → {r[0] if r else '?'} hits")
    except Exception as e:  # noqa: BLE001
        print(f"  smoke test failed: {e}")

    print("\nOK — questions_fts + triggers present.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
