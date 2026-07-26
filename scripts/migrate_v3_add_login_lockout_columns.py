"""
Add the two columns the Rust backend needs to enforce per-username
login lockout (VAPT H-4):

    ALTER TABLE users ADD COLUMN failed_login_count INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN locked_until TEXT;

Idempotent: checks existing PRAGMA table_info first and skips columns
that are already present. Safe to re-run on any environment (local,
staging, prod).

Run:  python3 scripts/migrate_v3_add_login_lockout_columns.py
"""

import json
import os
import sys
import urllib.request

TURSO_URL = os.environ["TURSO_DB_URL"]
TURSO_TOKEN = os.environ["TURSO_AUTH_TOKEN"]
HTTP_BASE = TURSO_URL.replace("libsql://", "https://")


def call(reqs):
    body = {"requests": reqs + [{"type": "close"}]}
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


def existing_columns():
    r = call([{"type": "execute", "stmt": {"sql": "PRAGMA table_info(users)"}}])
    return {row[1]["value"] for row in r["results"][0]["response"]["result"]["rows"]}


def main():
    cols = existing_columns()
    print(f"existing users columns: {sorted(cols)}")

    to_add = []
    if "failed_login_count" not in cols:
        to_add.append(
            "ALTER TABLE users ADD COLUMN failed_login_count INTEGER NOT NULL DEFAULT 0"
        )
    if "locked_until" not in cols:
        to_add.append("ALTER TABLE users ADD COLUMN locked_until TEXT")

    if not to_add:
        print("no columns to add — already migrated")
        return

    for stmt in to_add:
        print(f"executing: {stmt}")
        call([{"type": "execute", "stmt": {"sql": stmt}}])

    print("done — verify:", sorted(existing_columns()))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
