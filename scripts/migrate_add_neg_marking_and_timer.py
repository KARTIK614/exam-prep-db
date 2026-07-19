#!/usr/bin/env python3
"""
Phase 4 (Plan B) — add columns for timer, negative-marking, per-question
visit tracking, plus default settings rows:

    mock_tests.duration_sec        INTEGER
    mock_tests.negative_ratio      REAL DEFAULT 0
    mock_tests.raw_marks           REAL
    mock_tests.wrong_count         INTEGER
    mock_tests.unanswered_count    INTEGER
    test_responses.visit_count     INTEGER DEFAULT 1

Plus INSERT-OR-IGNORE two settings:
    default_neg_ratio           = '0.333333'
    default_test_duration_min   = '60'

Idempotent — inspects PRAGMA table_info per table and skips columns that
already exist. Prints table_info before and after so the caller can diff.

Runs against whatever database TURSO_DB_URL points at. Requires both
TURSO_DB_URL and TURSO_AUTH_TOKEN to be set.

Backfills:
- Any existing mock_tests rows with NULL negative_ratio get 0.0 (the default).
- Any existing test_responses rows with NULL visit_count get 1.

Usage:
    export TURSO_DB_URL=libsql://...
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/migrate_add_neg_marking_and_timer.py            # apply
    python3 scripts/migrate_add_neg_marking_and_timer.py --dry-run  # print only
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
        "duration_sec",
        "ALTER TABLE mock_tests ADD COLUMN duration_sec INTEGER",
        None,
    ),
    (
        "mock_tests",
        "negative_ratio",
        "ALTER TABLE mock_tests ADD COLUMN negative_ratio REAL DEFAULT 0",
        "UPDATE mock_tests SET negative_ratio = 0 WHERE negative_ratio IS NULL",
    ),
    (
        "mock_tests",
        "raw_marks",
        "ALTER TABLE mock_tests ADD COLUMN raw_marks REAL",
        None,
    ),
    (
        "mock_tests",
        "wrong_count",
        "ALTER TABLE mock_tests ADD COLUMN wrong_count INTEGER",
        None,
    ),
    (
        "mock_tests",
        "unanswered_count",
        "ALTER TABLE mock_tests ADD COLUMN unanswered_count INTEGER",
        None,
    ),
    (
        "test_responses",
        "visit_count",
        "ALTER TABLE test_responses ADD COLUMN visit_count INTEGER DEFAULT 1",
        "UPDATE test_responses SET visit_count = 1 WHERE visit_count IS NULL",
    ),
]

SETTINGS_SEEDS = [
    ("default_neg_ratio", "0.333333"),
    ("default_test_duration_min", "60"),
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
        print("\nAll target columns already present.")
    else:
        print("\nPlanned ALTERs:")
        for table, col, alter_sql, _ in to_apply:
            print(f"  + add {table}.{col}: {alter_sql}")

    print("\nSettings seeds (INSERT OR IGNORE):")
    for k, v in SETTINGS_SEEDS:
        print(f"  + {k} = {v}")

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

    for k, v in SETTINGS_SEEDS:
        con.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (k, v),
        )

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

    # Report the exam/practice + neg-ratio distribution.
    try:
        exam_count = con.execute(
            "SELECT COUNT(*) FROM mock_tests WHERE test_mode = 'exam'"
        ).fetchone()[0]
        practice_count = con.execute(
            "SELECT COUNT(*) FROM mock_tests WHERE test_mode = 'practice'"
        ).fetchone()[0]
        neg_rows = con.execute(
            "SELECT COUNT(*) FROM mock_tests WHERE negative_ratio > 0"
        ).fetchone()[0]
        print(
            f"\nmock_tests: exam={exam_count}, practice={practice_count}, "
            f"with_neg_marking={neg_rows}"
        )
    except Exception as e:  # noqa: BLE001
        print(f"[verify skipped] {e}")

    print("\nOK — all target columns present + settings seeded.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
