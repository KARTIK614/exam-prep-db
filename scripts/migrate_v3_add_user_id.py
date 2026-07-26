#!/usr/bin/env python3
"""
v3 Phase 2 — Multi-user schema migration.

Adds `user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)` to seven
per-user tables, plus supporting composite indexes and users-table
identity columns for multi-user prep. Also ensures user id=1 exists
(kartik/admin) so existing rows have a valid owner.

Design constraints (per docs/plans/v3-R2-turso-schema.md):
  * libSQL does NOT support `IF NOT EXISTS` on `ADD COLUMN`. We PRAGMA
    table_info() each table and skip columns that already exist.
  * `ALTER TABLE ADD COLUMN` in libSQL does NOT permit a REFERENCES
    constraint that would fail on existing rows, and cannot add a
    NOT NULL column that lacks a DEFAULT. We use `DEFAULT 1` so the
    existing rows immediately satisfy the NOT NULL. Turso does not
    enforce FKs by default; the `REFERENCES users(id)` is documentation.
  * Backfill is implicit — DEFAULT 1 fills existing rows during ALTER.
    We verify after with `SELECT COUNT(*) WHERE user_id IS NULL`.

Idempotent — safe to run multiple times. Skips columns / indexes that
already exist. Prints PRAGMA table_info() before and after each of the
seven tables.

Usage:
    export TURSO_DB_URL=libsql://exam-prep-db-pandit.aws-ap-south-1.turso.io
    export TURSO_AUTH_TOKEN=eyJ...
    python3 scripts/migrate_v3_add_user_id.py            # apply
    python3 scripts/migrate_v3_add_user_id.py --dry-run  # print only
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


# The seven per-user tables that need `user_id` bolted on.
USER_ID_TABLES = [
    "mock_tests",
    "test_responses",
    "error_log",
    "topic_mastery",
    "study_sessions",
    "bookmarks",
    "question_flags",
]

# Column additions on `users` for multi-user prep. Nullable to preserve
# existing user 1 (which has no email yet).
USERS_NEW_COLUMNS = [
    ("email", "ALTER TABLE users ADD COLUMN email TEXT"),
    ("email_verified_at", "ALTER TABLE users ADD COLUMN email_verified_at TEXT"),
    ("password_reset_token", "ALTER TABLE users ADD COLUMN password_reset_token TEXT"),
    ("password_reset_expires_at",
     "ALTER TABLE users ADD COLUMN password_reset_expires_at TEXT"),
    ("refresh_token_hash", "ALTER TABLE users ADD COLUMN refresh_token_hash TEXT"),
]

# Composite indexes per R2 recommendations. Ordered so we can drop the
# conflicting `idx_bookmarks_qid` before adding the composite unique.
INDEX_STATEMENTS = [
    ("idx_mock_tests_user_id",
     "CREATE INDEX IF NOT EXISTS idx_mock_tests_user_id ON mock_tests(user_id)"),
    ("idx_test_responses_user_test",
     "CREATE INDEX IF NOT EXISTS idx_test_responses_user_test "
     "ON test_responses(user_id, test_id)"),
    ("idx_error_log_user_due",
     "CREATE INDEX IF NOT EXISTS idx_error_log_user_due "
     "ON error_log(user_id, sr_due_at)"),
    ("idx_topic_mastery_user_topic",
     "CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_mastery_user_topic "
     "ON topic_mastery(user_id, topic_id)"),
    ("idx_study_sessions_user_date",
     "CREATE INDEX IF NOT EXISTS idx_study_sessions_user_date "
     "ON study_sessions(user_id, date)"),
    ("idx_bookmarks_user_qid",
     "CREATE UNIQUE INDEX IF NOT EXISTS idx_bookmarks_user_qid "
     "ON bookmarks(user_id, question_id)"),
    ("idx_question_flags_user",
     "CREATE INDEX IF NOT EXISTS idx_question_flags_user ON question_flags(user_id)"),
    # High-traffic non-user indexes worth having.
    ("idx_questions_topic",
     "CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic_id)"),
    ("idx_questions_disabled",
     "CREATE INDEX IF NOT EXISTS idx_questions_disabled ON questions(disabled)"),
    ("idx_error_log_qid",
     "CREATE INDEX IF NOT EXISTS idx_error_log_qid ON error_log(question_id)"),
]


def _table_info(con, table):
    return list(con.execute(f"PRAGMA table_info({table})").fetchall())


def _column_names(rows):
    return {r[1] for r in rows}


def _index_names(con, table):
    return {r[1] for r in con.execute(f"PRAGMA index_list({table})").fetchall()}


def _all_index_names(con):
    """All indexes across the DB (from sqlite_master)."""
    return {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }


def _print_table_info(label, table, rows):
    print(f"\n=== {label} PRAGMA table_info({table}) ===")
    print(f"{'cid':>4}  {'name':<28} {'type':<12} {'notnull':>7} "
          f"{'dflt_value':<15} {'pk':>3}")
    for r in rows:
        cid, name, typ, notnull, dflt, pk = r[0], r[1], r[2], r[3], r[4], r[5]
        print(f"{cid:>4}  {name:<28} {(typ or ''):<12} {notnull:>7} "
              f"{str(dflt or ''):<15} {pk:>3}")


def _ensure_user_one(con, dry_run):
    """Ensure users.id=1 exists (kartik/admin). Existing rows depend on it."""
    row = con.execute("SELECT id, username, role FROM users WHERE id = 1").fetchone()
    if row is not None:
        print(f"\n[users] id=1 already exists: username={row[1]!r}, role={row[2]!r}")
        return
    print("\n[users] id=1 MISSING — will insert placeholder kartik/admin "
          "(password_hash=NULL; seed separately).")
    if dry_run:
        return
    # Insert with explicit id=1 so backfilled user_id=1 references it.
    con.execute(
        "INSERT INTO users (id, username, password_hash, role, is_active, created_at) "
        "VALUES (1, ?, NULL, 'admin', 1, CURRENT_TIMESTAMP)",
        ("kartik",),
    )
    con.commit()
    row = con.execute("SELECT id, username, role FROM users WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("Failed to insert user id=1 — aborting migration.")
    print(f"[users] inserted id=1: username={row[1]!r}, role={row[2]!r}")


def _add_user_id_column(con, table, dry_run):
    """Add `user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)` if absent."""
    existing = _column_names(_table_info(con, table))
    if "user_id" in existing:
        print(f"[{table}] user_id column already present — skip ALTER.")
        return
    # SQLite rejects REFERENCES on ALTER TABLE ADD COLUMN with non-NULL DEFAULT.
    # Turso doesn't enforce FKs anyway (foreign_keys pragma off by default). The
    # reference is documentation-only, so we drop it from the ADD COLUMN and rely
    # on Rust-side type discipline + composite indexes for integrity.
    sql = f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1"
    print(f"[{table}] applying: {sql}")
    if dry_run:
        return
    con.execute(sql)


def _add_users_columns(con, dry_run):
    print("\n--- users identity columns ---")
    _print_table_info("BEFORE", "users", _table_info(con, "users"))
    existing = _column_names(_table_info(con, "users"))
    for col, sql in USERS_NEW_COLUMNS:
        if col in existing:
            print(f"[users] {col} already present — skip.")
            continue
        print(f"[users] applying: {sql}")
        if not dry_run:
            con.execute(sql)
    _print_table_info("AFTER", "users", _table_info(con, "users"))


def _drop_conflicting_bookmark_index(con, dry_run):
    """Old `idx_bookmarks_qid` is UNIQUE(question_id) — would prevent
    two users bookmarking the same question. Drop it so the composite
    UNIQUE(user_id, question_id) can take over."""
    names = _all_index_names(con)
    if "idx_bookmarks_qid" not in names:
        print("[bookmarks] no legacy idx_bookmarks_qid to drop.")
        return
    print("[bookmarks] dropping legacy idx_bookmarks_qid (UNIQUE question_id)")
    if not dry_run:
        con.execute("DROP INDEX IF EXISTS idx_bookmarks_qid")


def _create_indexes(con, dry_run):
    print("\n--- composite + high-traffic indexes ---")
    existing = _all_index_names(con)
    for name, sql in INDEX_STATEMENTS:
        if name in existing:
            print(f"[idx] {name} already present — skip.")
            continue
        print(f"[idx] applying: {sql}")
        if not dry_run:
            con.execute(sql)


def _verify(con):
    print("\n=== VERIFICATION ===")
    row = con.execute("SELECT COUNT(*) FROM users WHERE id = 1").fetchone()
    print(f"users(id=1) count: {row[0]}  (must be 1)")
    if row[0] != 1:
        print("ERROR: user id=1 missing — later inserts will violate FK "
              "and Rust code will 500.")

    print()
    all_ok = True
    for table in USER_ID_TABLES:
        total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        nulls = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL"
        ).fetchone()[0]
        with_uid = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_id = 1"
        ).fetchone()[0]
        status = "OK" if nulls == 0 else "FAIL"
        if nulls != 0:
            all_ok = False
        print(f"  [{status}] {table}: total={total}  "
              f"user_id IS NULL={nulls}  user_id=1={with_uid}")

    # Global stat.
    q_count = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    print(f"\n  questions (unchanged): total={q_count}  (expect 3712)")

    if not all_ok:
        print("\nVERIFICATION FAILED — one or more user_id columns still NULL.")
    else:
        print("\nVERIFICATION OK — every per-user row has user_id set.")
    return all_ok


def main(dry_run=False):
    con = sqlite3.connect(os.environ["DB_PATH"])

    print("=" * 68)
    print(" v3 Phase 2 — multi-user schema migration")
    print("=" * 68)

    # 1. Snapshot before.
    for table in USER_ID_TABLES:
        _print_table_info("BEFORE", table, _table_info(con, table))

    # 2. Make sure user 1 exists before backfill relies on it.
    _ensure_user_one(con, dry_run)

    # 3. Add users identity columns (email etc.) — idempotent.
    _add_users_columns(con, dry_run)

    # 4. Add `user_id` to each per-user table.
    print("\n--- add user_id columns ---")
    for table in USER_ID_TABLES:
        _add_user_id_column(con, table, dry_run)

    # 5. Legacy index cleanup (bookmarks) — must happen before the
    # composite UNIQUE gets created below.
    print("\n--- legacy index cleanup ---")
    _drop_conflicting_bookmark_index(con, dry_run)

    # 6. Composite + high-traffic indexes.
    _create_indexes(con, dry_run)

    if dry_run:
        print("\n--dry-run: not executing.")
        con.close()
        return 0

    con.commit()

    # 7. Snapshot after.
    print("\n" + "=" * 68)
    print(" AFTER state")
    print("=" * 68)
    for table in USER_ID_TABLES:
        _print_table_info("AFTER", table, _table_info(con, table))

    ok = _verify(con)

    con.close()
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
