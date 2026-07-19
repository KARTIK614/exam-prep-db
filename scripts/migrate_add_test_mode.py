#!/usr/bin/env python3
"""
Phase 3 (Plan B schema prep) — add:
    mock_tests.test_mode          TEXT DEFAULT 'practice'
    test_responses.marked_for_review INTEGER DEFAULT 0

Idempotent — inspects PRAGMA table_info per table and skips columns that
already exist. Prints table_info before and after so the caller can diff.

Runs against whatever database TURSO_DB_URL points at. Requires both
TURSO_DB_URL and TURSO_AUTH_TOKEN to be set.

Backfills:
- Any existing mock_tests rows with NULL test_mode get 'practice' (the default).
- Any existing test_responses rows with NULL marked_for_review get 0.

Usage:
    export TURSO_DB_URL=libsql://...
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/migrate_add_test_mode.py            # apply
    python3 scripts/migrate_add_test_mode.py --dry-run  # print only
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


# (table, column_name, ALTER SQL, backfill SQL or None)
TARGET_COLUMNS = [
    (
        "mock_tests",
        "test_mode",
        "ALTER TABLE mock_tests ADD COLUMN test_mode TEXT DEFAULT 'practice'",
        "UPDATE mock_tests SET test_mode = 'practice' WHERE test_mode IS NULL",
    ),
    (
        "test_responses",
        "marked_for_review",
        "ALTER TABLE test_responses ADD COLUMN marked_for_review INTEGER DEFAULT 0",
        "UPDATE test_responses SET marked_for_review = 0 WHERE marked_for_review IS NULL",
    ),
]


def _table_info(con, table):
    return list(con.execute(f"PRAGMA table_info({table})").fetchall())


def _existing_column_names(rows):
    return {r[1] for r in rows}


def _print_table_info(label, table, rows):
    print(f"\n=== {label} PRAGMA table_info({table}) ===")
    print(f"{'cid':>4}  {'name':<22} {'type':<15} {'notnull':>7} {'dflt_value':<15} {'pk':>3}")
    for r in rows:
        cid, name, typ, notnull, dflt, pk = r[0], r[1], r[2], r[3], r[4], r[5]
        print(f"{cid:>4}  {name:<22} {(typ or ''):<15} {notnull:>7} {str(dflt or ''):<15} {pk:>3}")


def main(dry_run=False):
    con = sqlite3.connect(os.environ["DB_PATH"])

    tables = sorted({t for t, *_ in TARGET_COLUMNS})
    for t in tables:
        _print_table_info("BEFORE", t, _table_info(con, t))

    to_apply = []
    for table, col, alter_sql, backfill_sql in TARGET_COLUMNS:
        existing = _existing_column_names(_table_info(con, table))
        if col not in existing:
            to_apply.append((table, col, alter_sql, backfill_sql))

    if not to_apply:
        print("\nAll target columns already present. Nothing to do.")
        con.close()
        return 0

    print("\nPlanned ALTERs:")
    for table, col, alter_sql, _ in to_apply:
        print(f"  + add {table}.{col}: {alter_sql}")

    if dry_run:
        print("\n--dry-run: not executing.")
        con.close()
        return 0

    for table, col, alter_sql, backfill_sql in to_apply:
        print(f"  applying: {alter_sql}")
        con.execute(alter_sql)
        if backfill_sql:
            print(f"  backfill: {backfill_sql}")
            con.execute(backfill_sql)
    con.commit()

    for t in tables:
        _print_table_info("AFTER", t, _table_info(con, t))

    # Assert every target column is present now.
    missing = []
    for table, col, _, _ in TARGET_COLUMNS:
        after = _existing_column_names(_table_info(con, table))
        if col not in after:
            missing.append(f"{table}.{col}")
    if missing:
        print(f"\nERROR: columns still missing after ALTER: {missing}")
        con.close()
        return 1

    # Report the exam-vs-practice split for the assertion in the task list.
    try:
        practice_count = con.execute(
            "SELECT COUNT(*) FROM mock_tests WHERE test_mode = 'practice'"
        ).fetchone()[0]
        total_count = con.execute("SELECT COUNT(*) FROM mock_tests").fetchone()[0]
        print(f"\nmock_tests: {practice_count}/{total_count} rows have test_mode='practice'")
    except Exception as e:  # noqa: BLE001
        print(f"[verify skipped] {e}")

    print("\nOK — all target columns present.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
