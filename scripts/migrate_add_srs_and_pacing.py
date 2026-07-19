#!/usr/bin/env python3
"""
Phase 5 (Plan A F1 + Plan C pacing) — spaced-repetition columns + target pace setting.

Adds:
    error_log.sr_box           INTEGER DEFAULT 1
    error_log.sr_due_at        TEXT       -- ISO date; when this card is next due
    error_log.sr_last_reviewed TEXT       -- ISO datetime of most recent review

Plus INSERT-OR-IGNORE two settings:
    target_seconds_per_q     = '72'        # BCI: 100 Q in 120 min = 72 s/Q
    daily_goal_min           = '30'        # counts a day as "active" if >= 10 min

Backfill for existing error_log rows:
    UPDATE error_log SET sr_box = 1,
        sr_due_at = date(COALESCE(created_at, 'now'), '+1 day')
    WHERE sr_due_at IS NULL;
    -- Advance rows that already have redo_1 correct into box 2:
    UPDATE error_log SET sr_box=2, sr_due_at=date('now','+3 days')
    WHERE (redo_1_score IS NOT NULL AND redo_1_score >= 1);
    UPDATE error_log SET sr_box=3, sr_due_at=date('now','+7 days')
    WHERE (redo_2_score IS NOT NULL AND redo_2_score >= 1);

Idempotent — inspects PRAGMA table_info per table and skips columns that
already exist. Prints table_info before and after so the caller can diff.

Runs against whatever database TURSO_DB_URL points at (via turso_patch).

Usage:
    export TURSO_DB_URL=libsql://...
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/migrate_add_srs_and_pacing.py            # apply
    python3 scripts/migrate_add_srs_and_pacing.py --dry-run  # print only
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


# (table, column_name, ALTER SQL, optional backfill SQL)
TARGET_COLUMNS = [
    (
        "error_log",
        "sr_box",
        "ALTER TABLE error_log ADD COLUMN sr_box INTEGER DEFAULT 1",
        "UPDATE error_log SET sr_box = 1 WHERE sr_box IS NULL",
    ),
    (
        "error_log",
        "sr_due_at",
        "ALTER TABLE error_log ADD COLUMN sr_due_at TEXT",
        # First: every legacy row with no due date gets 'created_at + 1 day' so
        # they surface in the queue but don't overwhelm it.
        "UPDATE error_log SET sr_due_at = date(COALESCE(created_at, 'now'), '+1 day') "
        "WHERE sr_due_at IS NULL",
    ),
    (
        "error_log",
        "sr_last_reviewed",
        "ALTER TABLE error_log ADD COLUMN sr_last_reviewed TEXT",
        None,
    ),
]

# Second-pass backfills — applied only after the columns exist. Bump rows that
# already have redo history into higher boxes so they don't all pile onto
# tomorrow.
POST_BACKFILL_SQL = [
    "UPDATE error_log SET sr_box = 2, sr_due_at = date('now','+3 days') "
    "WHERE sr_box = 1 AND redo_1_score IS NOT NULL AND redo_1_score >= 1",
    "UPDATE error_log SET sr_box = 3, sr_due_at = date('now','+7 days') "
    "WHERE sr_box = 2 AND redo_2_score IS NOT NULL AND redo_2_score >= 1",
]

SETTINGS_SEEDS = [
    ("target_seconds_per_q", "72"),
    ("daily_goal_min", "30"),
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

    for sql in POST_BACKFILL_SQL:
        print(f"  post-backfill: {sql}")
        con.execute(sql)

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

    # Report queue distribution.
    try:
        due_today = con.execute(
            "SELECT COUNT(*) FROM error_log WHERE date(sr_due_at) <= date('now')"
        ).fetchone()[0]
        by_box = con.execute(
            "SELECT sr_box, COUNT(*) FROM error_log GROUP BY sr_box ORDER BY sr_box"
        ).fetchall()
        print(f"\nerror_log: due_today={due_today}")
        for b in by_box:
            print(f"  box {b[0]}: {b[1]}")
    except Exception as e:  # noqa: BLE001
        print(f"[verify skipped] {e}")

    print("\nOK — SRS columns present + pacing settings seeded.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
