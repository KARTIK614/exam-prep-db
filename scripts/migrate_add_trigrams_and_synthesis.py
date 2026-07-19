#!/usr/bin/env python3
"""
Phase 6 (Plan D §3 + §4) — dedupe helper table + synthesis-batch tracker.

Creates two new tables on Turso:

    question_trigrams:
        question_id INTEGER REFERENCES questions(id),
        trigram TEXT,
        PRIMARY KEY (question_id, trigram)
    CREATE INDEX idx_trigrams_trigram ON question_trigrams(trigram);

    synthesis_batches:
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER REFERENCES topics(id),
        generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        n_requested INTEGER, n_generated INTEGER, n_approved INTEGER,
        n_disabled INTEGER, n_pending INTEGER,
        prompt_hash TEXT, model TEXT,
        status TEXT DEFAULT 'pending',
        notes TEXT

Idempotent — CREATE TABLE IF NOT EXISTS makes reruns safe.

Prints table_info before and after so the caller can diff.

Usage:
    export TURSO_DB_URL=libsql://...
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/migrate_add_trigrams_and_synthesis.py            # apply
    python3 scripts/migrate_add_trigrams_and_synthesis.py --dry-run  # print only
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
    """CREATE TABLE IF NOT EXISTS question_trigrams (
        question_id INTEGER REFERENCES questions(id),
        trigram TEXT,
        PRIMARY KEY (question_id, trigram)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_trigrams_trigram ON question_trigrams(trigram)",
    """CREATE TABLE IF NOT EXISTS synthesis_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER REFERENCES topics(id),
        generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        n_requested INTEGER,
        n_generated INTEGER DEFAULT 0,
        n_approved INTEGER DEFAULT 0,
        n_disabled INTEGER DEFAULT 0,
        n_pending INTEGER DEFAULT 0,
        prompt_hash TEXT,
        model TEXT,
        status TEXT DEFAULT 'pending',
        notes TEXT
    )""",
]

TABLES = ["question_trigrams", "synthesis_batches"]


def _table_info(con, table):
    try:
        return list(con.execute(f"PRAGMA table_info({table})").fetchall())
    except Exception as e:  # noqa: BLE001
        print(f"[table_info skip {table}] {e}")
        return []


def _print_table_info(label, table, rows):
    print(f"\n=== {label} PRAGMA table_info({table}) ===")
    if not rows:
        print("  (table absent)")
        return
    print(f"{'cid':>4}  {'name':<26} {'type':<15} {'notnull':>7} {'dflt_value':<15} {'pk':>3}")
    for r in rows:
        cid, name, typ, notnull, dflt, pk = r[0], r[1], r[2], r[3], r[4], r[5]
        print(f"{cid:>4}  {name:<26} {(typ or ''):<15} {notnull:>7} {str(dflt or ''):<15} {pk:>3}")


def main(dry_run=False):
    con = sqlite3.connect(os.environ["DB_PATH"])

    for t in TABLES:
        _print_table_info("BEFORE", t, _table_info(con, t))

    print("\nPlanned DDL statements:")
    for sql in DDL:
        line1 = sql.strip().split("\n", 1)[0]
        print(f"  + {line1}")

    if dry_run:
        print("\n--dry-run: not executing.")
        con.close()
        return 0

    for sql in DDL:
        print(f"  applying: {sql.strip().split(chr(10),1)[0]}")
        con.execute(sql)
    con.commit()

    for t in TABLES:
        _print_table_info("AFTER", t, _table_info(con, t))

    # Sanity check that both target tables now exist.
    missing = []
    for t in TABLES:
        if not _table_info(con, t):
            missing.append(t)
    if missing:
        print(f"\nERROR: tables still missing after DDL: {missing}")
        con.close()
        return 1

    # Report row counts as a smoke check.
    for t in TABLES:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n} rows")
        except Exception as e:  # noqa: BLE001
            print(f"  {t}: count failed: {e}")

    print("\nOK — question_trigrams + synthesis_batches present.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
