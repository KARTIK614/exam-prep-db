"""
Rebuild `topic_mastery` without the legacy per-column `UNIQUE(topic_id)`
constraint.

Why:
  * v2 was single-user, so `topic_mastery.topic_id UNIQUE` made sense.
  * v3 partitions the table by `user_id`, backed by a proper composite
    index `idx_topic_mastery_user_topic ON (user_id, topic_id)`.
  * The old per-column UNIQUE survived the multi-user migration, and it
    blocks any INSERT for `topic_id` values already claimed by user 1 —
    silently, when combined with the legacy Rust fallback UPDATE path.

Result of the bug: new users (kartik id=4, sujit_test, ...) show empty
mastery tiles and empty analytics after finishing tests, even though
their test_responses and error_log rows land correctly.

Steps (SQLite table rebuild):
  1. CREATE TABLE topic_mastery_new (...) — same shape minus the legacy
     UNIQUE.
  2. INSERT INTO topic_mastery_new SELECT * FROM topic_mastery.
  3. DROP TABLE topic_mastery.
  4. ALTER TABLE topic_mastery_new RENAME TO topic_mastery.
  5. Re-create the v3 composite unique index.

Idempotent: if the new table already lacks the legacy constraint, the
migration is a no-op.

Run:  python3 scripts/migrate_v3_drop_legacy_topic_mastery_unique.py
"""

import json
import os
import sys
import urllib.request

TURSO_URL = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_AUTH_TOKEN"]

HTTP_BASE = TURSO_URL.replace("libsql://", "https://")


def pipeline(*stmts):
    body = {
        "requests": [
            {"type": "execute", "stmt": {"sql": s}} for s in stmts
        ] + [{"type": "close"}]
    }
    req = urllib.request.Request(
        f"{HTTP_BASE}/v2/pipeline",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def current_schema():
    r = pipeline("SELECT sql FROM sqlite_master WHERE name = 'topic_mastery' AND type = 'table'")
    rows = r["results"][0]["response"]["result"]["rows"]
    return rows[0][0]["value"] if rows else None


def main():
    sql = current_schema()
    if sql is None:
        print("topic_mastery does not exist — nothing to do", flush=True)
        return

    print("Current schema:")
    print("  " + sql.replace("\n", "\n  "))

    if "topic_id INTEGER REFERENCES topics(id) UNIQUE" not in sql:
        print("\nLegacy UNIQUE(topic_id) already gone — nothing to do")
        return

    print("\nRebuilding topic_mastery without UNIQUE(topic_id)…")

    # 1) create new table
    pipeline(
        """CREATE TABLE topic_mastery_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id),
            diagnostic_score REAL,
            current_score REAL,
            study_hours REAL DEFAULT 0,
            status TEXT DEFAULT 'not_started',
            last_studied TEXT,
            test_count INTEGER DEFAULT 0,
            user_id INTEGER NOT NULL DEFAULT 1
        )""",
    )

    # 2) copy
    pipeline(
        "INSERT INTO topic_mastery_new "
        "(id, topic_id, diagnostic_score, current_score, study_hours, "
        " status, last_studied, test_count, user_id) "
        "SELECT id, topic_id, diagnostic_score, current_score, study_hours, "
        "       status, last_studied, test_count, user_id "
        "FROM topic_mastery"
    )

    # 3) drop the composite index BEFORE dropping the parent (SQLite drops it
    # automatically, but on Turso the DROP TABLE can fail otherwise on some
    # replicas). Best to do it explicitly.
    pipeline("DROP INDEX IF EXISTS idx_topic_mastery_user_topic")

    # 4) drop the old table
    pipeline("DROP TABLE topic_mastery")

    # 5) rename new -> old
    pipeline("ALTER TABLE topic_mastery_new RENAME TO topic_mastery")

    # 6) re-create v3 composite unique index
    pipeline(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_mastery_user_topic "
        "ON topic_mastery(user_id, topic_id)"
    )

    print("Done.")
    print("\nNew schema:")
    print("  " + (current_schema() or "").replace("\n", "\n  "))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
