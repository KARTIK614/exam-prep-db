"""
Add `user_id` to `synthesis_batches` so the Rust backend can enforce a
per-admin daily cap on LLM synthesis spend (VAPT H-5).

Existing rows get user_id=NULL (unattributed — pre-migration batches).
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


def cols():
    r = call([
        {"type": "execute", "stmt": {"sql": "PRAGMA table_info(synthesis_batches)"}}
    ])
    return {row[1]["value"] for row in r["results"][0]["response"]["result"]["rows"]}


def main():
    have = cols()
    print(f"existing synthesis_batches columns: {sorted(have)}")
    if "user_id" in have:
        print("user_id already present — no-op")
        return
    call([
        {"type": "execute", "stmt": {"sql":
            "ALTER TABLE synthesis_batches ADD COLUMN user_id INTEGER"}}
    ])
    print("added user_id; done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
