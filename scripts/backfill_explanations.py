#!/usr/bin/env python3
"""
Bulk-generate concise explanations for questions where `explanation` is
NULL, empty, or very short (<=30 chars).

Supports multi-provider rotation (round-robin) across:
  - DeepSeek (env: DEEPSEEK_PRIMARY_KEY, DEEPSEEK_SECONDARY_KEY)
  - GLM / Zhipu (env: GLM_API_KEY)
  - Gemini (env: GEMINI_API_KEY) — used as fallback if no provider keys set

On 429 / quota errors, that provider is marked exhausted for 5 minutes
and the next in the rotation is used. If all providers are exhausted
simultaneously the script sleeps 60s and retries.

Idempotent: skips rows that already have a non-trivial explanation.
Resumable: re-query after crash — it picks up where it left off.

Usage:
  export TURSO_DB_URL=... TURSO_AUTH_TOKEN=...
  export DEEPSEEK_PRIMARY_KEY=sk-... DEEPSEEK_SECONDARY_KEY=sk-... GLM_API_KEY=...
  python3 scripts/backfill_explanations.py --dry-run       # preview 3
  python3 scripts/backfill_explanations.py                 # go
  python3 scripts/backfill_explanations.py --limit 50      # bounded
  python3 scripts/backfill_explanations.py --topic 33      # DBMS only
"""
import os
import sys
import time
import json
import argparse
import sqlite3
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

if not os.environ.get("TURSO_DB_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
    sys.exit("ERROR: TURSO_DB_URL and TURSO_AUTH_TOKEN must be set")

os.environ.setdefault("DB_PATH", os.path.join(BASE, "data", "exam_prep.db"))
import turso_patch  # noqa: F401


# ── Provider config ────────────────────────────────────────────────
# Each entry: {name, endpoint, model, key_env, header_style}
# OpenAI-compatible: DeepSeek + GLM both accept {model, messages: [{role, content}]}

PROVIDERS = []


def _register_provider(name, key, endpoint, model, header_key="Authorization",
                       header_prefix="Bearer "):
    if key:
        PROVIDERS.append({
            "name": name,
            "key": key,
            "endpoint": endpoint,
            "model": model,
            "header_key": header_key,
            "header_prefix": header_prefix,
            "exhausted_until": 0,
            "requests_made": 0,
            "failures": 0,
        })


# Order matters: primary → secondary → GLM → Gemini (last-resort fallback)
_register_provider(
    "deepseek-primary",
    os.environ.get("DEEPSEEK_PRIMARY_KEY"),
    "https://api.deepseek.com/v1/chat/completions",
    "deepseek-chat",
)
_register_provider(
    "deepseek-secondary",
    os.environ.get("DEEPSEEK_SECONDARY_KEY"),
    "https://api.deepseek.com/v1/chat/completions",
    "deepseek-chat",
)
_register_provider(
    "glm-flash",
    os.environ.get("GLM_API_KEY"),
    "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "glm-4-flash",
)
# Gemini fallback (different schema — special-cased below)
_gemini_key = os.environ.get("GEMINI_API_KEY")
if _gemini_key:
    PROVIDERS.append({
        "name": "gemini-flash",
        "key": _gemini_key,
        "endpoint": None,  # signals special handling
        "model": "gemini-2.5-flash",
        "exhausted_until": 0,
        "requests_made": 0,
        "failures": 0,
    })

if not PROVIDERS:
    sys.exit("ERROR: at least one of DEEPSEEK_PRIMARY_KEY, "
             "DEEPSEEK_SECONDARY_KEY, GLM_API_KEY, GEMINI_API_KEY must be set")


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


# ── Provider dispatch ──────────────────────────────────────────────

def _call_openai_compat(provider, prompt, timeout=30):
    """DeepSeek + GLM — both OpenAI-compatible chat completions."""
    body = {
        "model": provider["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 300,
    }
    headers = {
        provider["header_key"]: provider["header_prefix"] + provider["key"],
        "Content-Type": "application/json",
    }
    resp = requests.post(provider["endpoint"], json=body, headers=headers, timeout=timeout)
    if resp.status_code == 429:
        raise RuntimeError(f"HTTP 429 rate-limit on {provider['name']}: {resp.text[:200]}")
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} on {provider['name']}: {resp.text[:200]}")
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"No choices in {provider['name']} response: {json.dumps(data)[:200]}")
    text = (choices[0].get("message") or {}).get("content", "").strip()
    if not text:
        raise RuntimeError(f"Empty content from {provider['name']}")
    return text


def _call_gemini_rest(provider, prompt, timeout=30):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{provider['model']}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(url, params={"key": provider["key"]}, json=body,
                         headers={"Content-Type": "application/json"}, timeout=timeout)
    if resp.status_code == 429:
        raise RuntimeError(f"HTTP 429 rate-limit on gemini: {resp.text[:200]}")
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} on gemini: {resp.text[:200]}")
    data = resp.json()
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError("Gemini blocked or empty candidates")
    parts = ((cands[0].get("content") or {}).get("parts")) or []
    text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise RuntimeError("Gemini empty text")
    return text


def call_provider(provider, prompt, timeout=30):
    if provider["endpoint"] is None:  # gemini
        return _call_gemini_rest(provider, prompt, timeout)
    return _call_openai_compat(provider, prompt, timeout)


# ── Rotation logic ─────────────────────────────────────────────────

def _next_available_idx(rotation_idx):
    """Find next provider not currently exhausted. Returns -1 if all exhausted."""
    now = time.time()
    n = len(PROVIDERS)
    for offset in range(n):
        idx = (rotation_idx + offset) % n
        if PROVIDERS[idx]["exhausted_until"] < now:
            return idx
    return -1


def call_with_rotation(prompt, timeout=30, rotation_state=[0]):
    """Try each provider in round-robin. On 429, mark provider exhausted for 5 min.

    Returns (text, provider_name) or raises RuntimeError if all providers dead.
    """
    tried = []
    while True:
        idx = _next_available_idx(rotation_state[0])
        if idx == -1:
            # All exhausted — wait a bit and reset
            print(f"  all providers exhausted; sleeping 60s ({','.join(tried)})", flush=True)
            time.sleep(60)
            # Reset the earliest one to try again
            earliest_idx = min(range(len(PROVIDERS)), key=lambda i: PROVIDERS[i]["exhausted_until"])
            PROVIDERS[earliest_idx]["exhausted_until"] = 0
            tried.clear()
            continue

        p = PROVIDERS[idx]
        try:
            text = call_provider(p, prompt, timeout)
            p["requests_made"] += 1
            rotation_state[0] = (idx + 1) % len(PROVIDERS)  # advance for next call
            return text, p["name"]
        except RuntimeError as e:
            p["failures"] += 1
            msg = str(e)
            if "429" in msg or "quota" in msg.lower() or "rate" in msg.lower():
                # Mark this provider exhausted for 5 min
                p["exhausted_until"] = time.time() + 300
                tried.append(p["name"])
                print(f"  {p['name']} rate-limited, rotating", flush=True)
                continue
            # Non-rate-limit failure — try next provider once but don't mark exhausted
            tried.append(p["name"])
            if len(tried) >= len(PROVIDERS):
                raise
            rotation_state[0] = (idx + 1) % len(PROVIDERS)
            continue


# ── DB helpers ─────────────────────────────────────────────────────

def fetch_eligible(cur, limit=None, topic_id=None):
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
    if not text:
        return ""
    t = text.strip()
    for prefix in ("Explanation:", "Answer:", "**Explanation:**"):
        if t.lower().startswith(prefix.lower()):
            t = t[len(prefix):].lstrip()
    t = " ".join(t.split())
    return t


# ── Main ───────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--topic", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.3,
                    help="Sleep between rows (safety pacing, default 0.3s)")
    args = ap.parse_args()

    print(f"Providers registered: {[p['name'] for p in PROVIDERS]}", flush=True)

    db_path = os.environ["DB_PATH"]
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    rows = fetch_eligible(cur, limit=args.limit, topic_id=args.topic)
    print(f"Eligible questions: {len(rows)}", flush=True)

    if args.dry_run:
        print("--- DRY RUN — first 3 previews ---", flush=True)
        for r in rows[:3]:
            print(f"\n[Q#{r['id']}]  {(r['question_text'] or '')[:100]}...", flush=True)
            try:
                text, provider = call_with_rotation(build_prompt(r), timeout=30)
                out = clean_response(text)
                print(f"  ({provider}) {out}", flush=True)
            except Exception as e:
                print(f"  ERR: {e}", flush=True)
        return

    ok = 0
    fail = 0
    provider_counts = {}
    start = time.time()
    for i, r in enumerate(rows, 1):
        try:
            text, provider = call_with_rotation(build_prompt(r), timeout=30)
            expl = clean_response(text)
            if not expl or len(expl) < 20:
                print(f"[{i}/{len(rows)}] Q#{r['id']} — SKIP (short response from {provider})", flush=True)
                fail += 1
                continue
            cur.execute(
                "UPDATE questions SET explanation = ?, updated_at = datetime('now') WHERE id = ?",
                (expl, r["id"]),
            )
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
            ok += 1
            if i % 25 == 0 or i == len(rows):
                elapsed = time.time() - start
                rate = i / elapsed if elapsed else 0
                remaining = (len(rows) - i) / rate if rate else 0
                per_prov = ", ".join(f"{k}={v}" for k, v in provider_counts.items())
                print(f"[{i}/{len(rows)}] ok={ok} fail={fail} rate={rate:.1f}/s "
                      f"eta={remaining/60:.1f}min | {per_prov}", flush=True)
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(rows)}] Q#{r['id']} — ERR: {type(e).__name__}: {str(e)[:150]}", flush=True)
        if args.sleep > 0:
            time.sleep(args.sleep)

    print(f"\nDone. Updated {ok}, failed {fail}, total {len(rows)}.", flush=True)
    print(f"Provider breakdown: {provider_counts}", flush=True)


if __name__ == "__main__":
    main()
