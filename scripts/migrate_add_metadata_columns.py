#!/usr/bin/env python3
"""
Add 7 metadata columns to the Turso `questions` table (Plan D §5):
    confidence               TEXT DEFAULT 'high'
    section                  TEXT
    sub_topic                TEXT
    pyq_exam                 TEXT
    pyq_year                 INTEGER
    review_notes             TEXT
    confidence_reviewed_at   TEXT

Idempotent — inspects PRAGMA table_info first and skips columns that
already exist. Prints table_info before and after so the caller can diff.

Runs against whatever database TURSO_DB_URL points at. Requires both
TURSO_DB_URL and TURSO_AUTH_TOKEN to be set.

Usage:
    export TURSO_DB_URL=libsql://...
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/migrate_add_metadata_columns.py            # apply
    python3 scripts/migrate_add_metadata_columns.py --dry-run  # print only
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

if not os.environ.get("TURSO_DB_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
    sys.exit("ERROR: set TURSO_DB_URL and TURSO_AUTH_TOKEN before running.")

# Route sqlite3.connect through the Hrana HTTP adapter.
os.environ.setdefault("DB_PATH", os.path.join(BASE, "data", "exam_prep.db"))
import turso_patch  # noqa: F401 — monkey-patches sqlite3
import sqlite3


TARGET_COLUMNS = [
    ("confidence",              "ALTER TABLE questions ADD COLUMN confidence TEXT DEFAULT 'high'"),
    ("section",                 "ALTER TABLE questions ADD COLUMN section TEXT"),
    ("sub_topic",               "ALTER TABLE questions ADD COLUMN sub_topic TEXT"),
    ("pyq_exam",                "ALTER TABLE questions ADD COLUMN pyq_exam TEXT"),
    ("pyq_year",                "ALTER TABLE questions ADD COLUMN pyq_year INTEGER"),
    ("review_notes",            "ALTER TABLE questions ADD COLUMN review_notes TEXT"),
    ("confidence_reviewed_at",  "ALTER TABLE questions ADD COLUMN confidence_reviewed_at TEXT"),
]


def _table_info(con):
    return list(con.execute("PRAGMA table_info(questions)").fetchall())


def _existing_column_names(rows):
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    return {r[1] for r in rows}


def _print_table_info(label, rows):
    print(f"\n=== {label} PRAGMA table_info(questions) ===")
    print(f"{'cid':>4}  {'name':<26} {'type':<15} {'notnull':>7} {'dflt_value':<15} {'pk':>3}")
    for r in rows:
        cid, name, typ, notnull, dflt, pk = r[0], r[1], r[2], r[3], r[4], r[5]
        print(f"{cid:>4}  {name:<26} {(typ or ''):<15} {notnull:>7} {str(dflt or ''):<15} {pk:>3}")


def main(dry_run=False):
    con = sqlite3.connect(os.environ["DB_PATH"])

    before = _table_info(con)
    _print_table_info("BEFORE", before)

    existing = _existing_column_names(before)
    to_apply = [(name, sql) for name, sql in TARGET_COLUMNS if name not in existing]

    if not to_apply:
        print("\nAll target columns already present. Nothing to do.")
        con.close()
        return 0

    print("\nPlanned ALTERs:")
    for name, sql in to_apply:
        print(f"  + add column '{name}':  {sql}")

    if dry_run:
        print("\n--dry-run: not executing.")
        con.close()
        return 0

    row_count_before = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    print(f"\nRow count before: {row_count_before}")

    for name, sql in to_apply:
        print(f"  applying: {sql}")
        con.execute(sql)
    con.commit()

    row_count_after = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    print(f"Row count after:  {row_count_after}")
    if row_count_before != row_count_after:
        print("WARNING: row count changed during migration!")

    after = _table_info(con)
    _print_table_info("AFTER", after)

    # Assert every target is now present.
    after_names = _existing_column_names(after)
    missing = [name for name, _ in TARGET_COLUMNS if name not in after_names]
    if missing:
        print(f"\nERROR: columns still missing after ALTER: {missing}")
        con.close()
        return 1

    print("\nOK — all target columns present.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
