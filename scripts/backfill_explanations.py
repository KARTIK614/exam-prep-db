#!/usr/bin/env python3
"""
Bulk-generate concise explanations for questions where `explanation` is
NULL, empty, or very short (<=30 chars). Uses Gemini REST.

Idempotent: skips rows that already have a non-trivial explanation.
Resumable: run again after a crash — it picks up where it left off.

Progress printed per row. Failures logged and skipped (script continues).

Usage:
  export TURSO_DB_URL=... TURSO_AUTH_TOKEN=... GEMINI_API_KEY=...
  python3 scripts/backfill_explanations.py --dry-run       # preview first 3
  python3 scripts/backfill_explanations.py                 # go
  python3 scripts/backfill_explanations.py --limit 50      # bounded run
  python3 scripts/backfill_explanations.py --topic 33      # DBMS only
"""
import os
import sys
import time
import argparse
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

if not os.environ.get("TURSO_DB_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
    sys.exit("ERROR: TURSO_DB_URL and TURSO_AUTH_TOKEN must be set")
if not os.environ.get("GEMINI_API_KEY"):
    sys.exit("ERROR: GEMINI_API_KEY must be set")

os.environ.setdefault("DB_PATH", os.path.join(BASE, "data", "exam_prep.db"))
import turso_patch  # noqa: F401
from ai_utils import call_gemini


PROMPT = """You are helping a student prep for a competitive exam (Rajasthan Basic Computer Instructor). Give a concise 2-3 sentence explanation for why the correct answer is right for this MCQ.

Rules:
- 2-3 sentences only. No filler.
- Do NOT restate the question or options.
- Focus on the key concept or fact that makes the answer correct.
- Plain text, no markdown, no bullets.
- No preamble like "The correct answer is X because..." — just explain the concept.

Question: {question_text}
(A) {option_a}
(B) {option_b}
(C) {option_c}
(D) {option_d}
Correct answer: ({correct_option})

Explanation:"""


def build_prompt(row):
    return PROMPT.format(
        question_text=(row["question_text"] or "").strip(),
        option_a=(row["option_a"] or "").strip(),
        option_b=(row["option_b"] or "").strip(),
        option_c=(row["option_c"] or "").strip(),
        option_d=(row["option_d"] or "").strip(),
        correct_option=(row["correct_option"] or "?").strip().upper()[:1],
    )


def fetch_eligible(cur, limit=None, topic_id=None):
    """Rows with NULL/empty/short explanation. Ordered by id for reproducibility."""
    sql = (
        "SELECT id, topic_id, question_text, option_a, option_b, option_c, "
        "option_d, correct_option, COALESCE(explanation,'') AS explanation "
        "FROM questions "
        "WHERE (disabled = 0 OR disabled IS NULL) "
        "  AND LENGTH(TRIM(COALESCE(explanation, ''))) <= 30 "
    )
    params = []
    if topic_id is not None:
        sql += "  AND topic_id = ? "
        params.append(topic_id)
    sql += "ORDER BY id"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return cur.execute(sql, params).fetchall()


def clean_response(text):
    """Strip common LLM artifacts."""
    if not text:
        return ""
    t = text.strip()
    # Remove leading "Explanation:" if the model echoed it
    for prefix in ("Explanation:", "Answer:", "**Explanation:**"):
        if t.lower().startswith(prefix.lower()):
            t = t[len(prefix):].lstrip()
    # Collapse whitespace
    t = " ".join(t.split())
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print first 3 previews, no DB writes")
    ap.add_argument("--limit", type=int, default=None, help="Cap number of rows processed")
    ap.add_argument("--topic", type=int, default=None, help="Restrict to a single topic_id")
    ap.add_argument("--sleep", type=float, default=0.5, help="Seconds between API calls (rate limit safety)")
    args = ap.parse_args()

    db_path = os.environ["DB_PATH"]
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    rows = fetch_eligible(cur, limit=args.limit, topic_id=args.topic)
    print(f"Eligible questions: {len(rows)}")
    if args.dry_run:
        print("--- DRY RUN — first 3 previews ---")
        for r in rows[:3]:
            print(f"\n[Q#{r['id']}]  {(r['question_text'] or '')[:100]}...")
            try:
                out = clean_response(call_gemini(build_prompt(r), timeout=30))
                print(f"  gen: {out}")
            except Exception as e:
                print(f"  ERR: {e}")
        return

    ok = 0
    fail = 0
    start = time.time()
    for i, r in enumerate(rows, 1):
        try:
            expl = clean_response(call_gemini(build_prompt(r), timeout=30))
            if not expl or len(expl) < 20:
                print(f"[{i}/{len(rows)}] Q#{r['id']} — SKIP (empty/short response)")
                fail += 1
                continue
            cur.execute(
                "UPDATE questions SET explanation = ?, updated_at = datetime('now') WHERE id = ?",
                (expl, r["id"]),
            )
            ok += 1
            if i % 25 == 0 or i == len(rows):
                elapsed = time.time() - start
                rate = i / elapsed if elapsed else 0
                remaining = (len(rows) - i) / rate if rate else 0
                print(f"[{i}/{len(rows)}] ok={ok} fail={fail} rate={rate:.1f}/s eta={remaining/60:.1f}min")
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(rows)}] Q#{r['id']} — ERR: {type(e).__name__}: {str(e)[:120]}")
            # Backoff on rate-limit-looking errors
            if "429" in str(e) or "rate" in str(e).lower() or "quota" in str(e).lower():
                print("  (rate-limit detected, sleeping 60s)")
                time.sleep(60)
                continue
        if args.sleep > 0:
            time.sleep(args.sleep)

    print(f"\nDone. Updated {ok}, failed {fail}, total {len(rows)}.")


if __name__ == "__main__":
    main()
