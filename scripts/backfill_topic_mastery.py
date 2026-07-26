"""
Backfill `topic_mastery` for users who took tests before the legacy
`UNIQUE(topic_id)` constraint was dropped. Those tests successfully
seeded `test_responses` and `error_log` but their `finish_impl` upsert
into `topic_mastery` silently failed.

Semantics: for each (user_id, topic_id) that has answered rows but no
`topic_mastery` row, apply the same 60/40 EMA the Rust backend applies
per completed test, in chronological order.

Idempotent: for any (user_id, topic_id) that already has a row, we skip
— the live finish path is now healthy and will maintain it.

Run:  python3 scripts/backfill_topic_mastery.py
"""

import json
import os
import sys
import time
import urllib.request
from collections import defaultdict

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


def exec_sql(sql, args=()):
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [_to_value(a) for a in args]
    return call([{"type": "execute", "stmt": stmt}])


def _to_value(v):
    if v is None:
        return {"type": "null", "value": None}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def rows(r):
    return r["results"][0]["response"]["result"]["rows"]


def cell(r, i):
    v = r[i]
    if v.get("type") == "null":
        return None
    val = v.get("value")
    t = v.get("type")
    if t == "integer":
        return int(val)
    if t == "float":
        return float(val)
    return val


def round1(x):
    return round(x * 10) / 10


def main():
    # 1) find (user_id, topic_id) pairs with test_responses but no mastery row
    r = exec_sql(
        "SELECT tr.user_id, q.topic_id "
        "FROM test_responses tr "
        "JOIN questions q ON q.id = tr.question_id "
        "WHERE q.topic_id IS NOT NULL "
        "GROUP BY tr.user_id, q.topic_id "
        "HAVING NOT EXISTS ("
        "  SELECT 1 FROM topic_mastery tm "
        "  WHERE tm.user_id = tr.user_id AND tm.topic_id = q.topic_id"
        ")"
    )
    pairs = [(cell(row, 0), cell(row, 1)) for row in rows(r)]
    print(f"Backfilling {len(pairs)} (user_id, topic_id) pairs")

    # 2) group by user for chronological pass across all their completed tests
    by_user = defaultdict(set)
    for uid, tid in pairs:
        by_user[uid].add(tid)

    for uid, topic_ids in sorted(by_user.items()):
        print(f"\nUser {uid}: {len(topic_ids)} topics to backfill")

        # Chronological list of this user's completed tests (with topic-level agg)
        r = exec_sql(
            "SELECT mt.id, mt.completed_at "
            "FROM mock_tests mt "
            "WHERE mt.user_id = ?1 AND mt.status = 'completed' "
            "ORDER BY datetime(mt.completed_at) ASC",
            args=(uid,),
        )
        test_rows = rows(r)
        print(f"  {len(test_rows)} completed tests")

        # In-memory current_score per topic; seed from DB in case some
        # topics already have partial rows (unlikely, but defensive).
        current = {}

        for trow in test_rows:
            test_id = cell(trow, 0)
            completed_at = cell(trow, 1)
            # per-topic (correct, total) for this test — filtered to
            # topics we still need to backfill for this user
            agg = exec_sql(
                "SELECT q.topic_id, "
                "       SUM(CASE WHEN tr.selected_option = q.correct_option THEN 1 ELSE 0 END), "
                "       COUNT(*) "
                "FROM test_responses tr "
                "JOIN questions q ON q.id = tr.question_id "
                "WHERE tr.test_id = ?1 AND tr.user_id = ?2 AND q.topic_id IS NOT NULL "
                "GROUP BY q.topic_id",
                args=(test_id, uid),
            )
            for row in rows(agg):
                tid = cell(row, 0)
                if tid not in topic_ids:
                    continue
                c = cell(row, 1) or 0
                t = cell(row, 2) or 0
                if t == 0:
                    continue
                this_pct = (c / t) * 100.0
                if tid in current:
                    new_score = round1(0.6 * current[tid] + 0.4 * this_pct)
                else:
                    new_score = round1(this_pct)
                current[tid] = new_score

        # 3) INSERT one row per topic with the final score
        for tid, score in current.items():
            status = "in_progress" if score < 70.0 else "stable"
            try:
                exec_sql(
                    "INSERT INTO topic_mastery "
                    "(topic_id, current_score, test_count, status, last_studied, user_id) "
                    "VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                    args=(tid, score, len(test_rows), status,
                          test_rows[-1][1].get("value") if test_rows else None, uid),
                )
            except Exception as e:
                print(f"  ! failed insert user={uid} topic={tid}: {e}")
        print(f"  inserted {len(current)} mastery rows")

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
