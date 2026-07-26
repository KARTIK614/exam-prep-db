#!/usr/bin/env python3
"""
v3 Phase 5 addendum — add UNIQUE(user_id, test_id, question_id) index to
error_log so /tests/{id}/finish is naturally idempotent (double-submit
just fails INSERT OR IGNORE, no duplicates).

Idempotent. Prints existing indexes on error_log before + after.
"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

if not os.environ.get("TURSO_DB_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
    sys.exit("ERROR: TURSO_DB_URL and TURSO_AUTH_TOKEN must be set")

os.environ.setdefault("DB_PATH", os.path.join(BASE, "data", "exam_prep.db"))
import turso_patch, sqlite3

con = sqlite3.connect(os.environ["DB_PATH"])
cur = con.cursor()

def show_indexes():
    rows = cur.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='error_log' ORDER BY name").fetchall()
    for r in rows:
        print(f"  {r[0]}: {r[1] or '(auto)'}")

print("BEFORE indexes on error_log:")
show_indexes()

sql = "CREATE UNIQUE INDEX IF NOT EXISTS idx_error_log_unique ON error_log(user_id, test_id, question_id)"
print(f"\napplying: {sql}")
try:
    cur.execute(sql)
    print("OK")
except sqlite3.Error as e:
    msg = str(e).lower()
    if "unique constraint" in msg or "duplicate" in msg:
        print(f"  → duplicate rows exist already; would need dedupe first: {e}")
    else:
        raise

print("\nAFTER indexes on error_log:")
show_indexes()

# quick check: any duplicate (user_id, test_id, question_id)?
dupes = cur.execute(
    "SELECT user_id, test_id, question_id, COUNT(*) c FROM error_log "
    "GROUP BY user_id, test_id, question_id HAVING c > 1"
).fetchall()
if dupes:
    print(f"\nWARN: {len(dupes)} duplicate error_log rows exist; UNIQUE index will fail on next insert of one of these.")
    for d in dupes[:5]:
        print(f"  user={d[0]} test={d[1]} q={d[2]} count={d[3]}")
else:
    print("\nNo duplicate (user_id, test_id, question_id) rows in error_log — index safe.")
