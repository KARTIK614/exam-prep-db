# Backend Critical Review — Exam Prep Platform

> Scope: all Python files (`app.py`, `db.py`, `turso_patch.py`, `sr.py`, blueprints, scripts, tests) plus `render.yaml`.
> Date: 2026-07-19. Read-only review — no code changes.

## Severity Histogram

| Severity | Count |
|----------|-------|
| critical | 3     |
| high     | 9     |
| medium   | 21    |
| low      | 17    |
| **total**| **50**|

## Category Breakdown

| Cat | Meaning                | Count |
|-----|------------------------|-------|
| A   | Correctness bugs       | 15    |
| B   | Security               | 11    |
| C   | Performance            | 8     |
| D   | Data integrity         | 11    |
| G   | Ops/deploy             | 5     |
| I   | Deferred/multi-user    | 3     |
(Some findings tagged multiple categories, so sums may exceed 50.)

## Top 5 — Fix RIGHT NOW

1. **F06 / F31 / F43 — Delete `/diag` and `/setup/seed` endpoints.** Three critical severities all sitting in `bp_diag.py`. Authorization-by-substring-of-secret + built-in password oracle + password-in-query-string. Any URL leak = account takeover. The comment in the file says "Removed once the platform is stable — kept for one-time bootstrap" — that time is now.

2. **F01 — Gate `/api/settings` with `@require_admin` and whitelist keys.** Any authenticated user can rewrite scoring thresholds and negative-marking defaults. Blocks multi-user rollout. Fix is <5 lines.

3. **F09 — Fix `_run_alter_migrations`'s over-broad except and log via logger.warning.** MEMORY.md already logged this exact bug hitting prod (Turso schema drift on `disabled`/`updated_at`). The comment claims turso_patch fixed it; the surrounding `except Exception` still masks other classes of failure.

4. **F13 — Add `UNIQUE(test_id, question_id)` on `error_log` + double-submit guard on `finish()`.** Duplicate SR cards and drifted `topic_mastery` scores on a browser back-forward or double-submit. Combined with F49 (no idempotency key).

5. **F16 — Rate-limit `/api/deep-dive` and `/admin/api/synthesize/preview`.** Currently unbounded LLM calls per session. JWT theft = quota-burn. Adding flask-limiter is a one-day job that caps the blast radius.

Runner-up (F37): if multi-user is anywhere on the horizon, the schema migration to add `user_id` to seven tables + rewriting every query is a **days-long** effort. Doing it before user #2 saves the mess of retroactively assigning ownership.

---

## Findings

### F01: `/api/settings` (and other write endpoints) missing `@require_admin`
**Severity:** high
**Category:** B
**Location:** `bp_api.py:169-176`
**Evidence:**
```python
@bp.route("/settings", methods=["POST"])
def update_settings():
    data = request.json
    db = get_db()
    for k, v in data.items():
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (k, str(v)))
    db.commit()
    return jsonify({"status": "ok"})
```
Any logged-in user (JWT-cookie holder) can rewrite `settings` — including `target_score`, `weakness_threshold`, `default_neg_ratio`. It also **accepts arbitrary keys**, so a client can pollute the table with junk (or overwrite future settings keys before code adds validation).
**Impact:** Non-admin user can silently rewire scoring, negative-marking defaults, and threshold logic. Not catastrophic in solo-user mode, but the moment `user_id` is added this endpoint becomes a shared-state hazard.
**Fix:** Add `@require_admin` from `auth.py`. Also whitelist known keys (`target_score`, `weakness_threshold`, `daily_goal_min`, `target_seconds_per_q`, `default_neg_ratio`, `default_test_duration_min`, `accuracy_focus`).
**Effort:** minutes

### F02: `test_responses.visit_count` inflated on every question re-fetch
**Severity:** medium
**Category:** A
**Location:** `bp_api.py:62-67`
**Evidence:**
```python
key = str(idx)
if key in responses:
    responses[key]["visit_count"] = int(responses[key].get("visit_count", 1) or 1) + 1
```
`/api/question/<idx>` is called every time the user clicks a palette square or presses arrow keys — not just true re-visits. `visit_count` therefore over-reports "flip-flopping" behavior. It also **never** starts at 1 on first visit (only entries already in `responses` are incremented), so a question answered once has `visit_count = 1` while a question answered then merely re-viewed twice has `visit_count = 3`. Two different denominators.
**Impact:** Analytics on flip-flopping will be noisy; distinguishing "changed answer twice" from "peeked at question three times" is impossible.
**Fix:** Either (a) only bump when the previous state was already an answered response and this is a distinct visit (compare `q_start_time` window), or (b) rename the field to `view_count` and add a separate `changes_count` bumped inside `/api/submit_answer` when `selected` differs from prior.
**Effort:** hours

### F03: `mock_tests.paper` guessed from question 0 topic name
**Severity:** high
**Category:** A
**Location:** `bp_tests.py:326-328`
**Evidence:**
```python
"paper": "I" if questions and questions[0].get("topic_name", "").startswith("Raj") else "II",
```
The setup form already collected `paper` and stored it on the `mock_tests` row at `bp_tests.py:117-119`. `finish()` overrides that in the session's `last_result` with a string-prefix guess based only on the first question's topic name. If the user picks paper "both", the guess returns "II" regardless. The stored DB paper is correct; the results page/UI shows the guessed one.
**Impact:** Results page paper label is wrong for any "both"-mode test; can misattribute stats client-side.
**Fix:** Use the `paper` value from the DB row already fetched (`test = db.execute("SELECT * FROM mock_tests WHERE id=?"...)` in `results()`) or from the session's stored `paper` — do not guess from topic name.
**Effort:** minutes

### F04: FTS5 count query joins `questions` twice and can drop rows
**Severity:** medium
**Category:** C
**Location:** `bp_main.py:414-421`
**Evidence:**
```python
count_sql = (
    "SELECT COUNT(*) FROM questions_fts "
    "JOIN questions q ON q.id = questions_fts.rowid "
    "LEFT JOIN topics t ON t.id = q.topic_id "
    "WHERE questions_fts MATCH ?" + where_extra
)
```
Two issues: (1) `LEFT JOIN topics` in a COUNT is a waste; topics is not filtered on. (2) `questions_fts` is contentless and the JOIN to `questions` is redundant if no `q.*` predicate exists — but `where_extra` always adds `q.disabled` filter, so the join is required. Minor: BM25 rank is `ORDER BY rank` which is ascending, but BM25 returns lower = more relevant, so the ordering happens to be correct — this deserves a comment or a `-bm25(...)` sign flip if libSQL differs from stock SQLite.
**Impact:** Count query is measurably slower on 3.7k rows than necessary; not a bug, but wasteful.
**Fix:** Drop the `LEFT JOIN topics` from the count query; keep it on the row query. Add inline comment about BM25 sign convention.
**Effort:** minutes

### F05: `session["review_marks"]` and `session["responses"]` keyed by string, palette/finish keyed inconsistently
**Severity:** medium
**Category:** A
**Location:** `bp_api.py:92-110`, `bp_tests.py:251-268`
**Evidence:** `mark_for_review` stores `marks[str(idx)] = True`, but `finish()` iterates `for q_idx_str, r in responses.items(): ... review_marks.get(q_idx_str)`. That happens to work because both use `str(idx)`. However, `mark_for_review` writes flags for questions **not necessarily in `responses`** (per the docstring at `bp_tests.py:284-288`: "mark-for-review flags on questions that were marked but never answered are lost at finish time"). So marks on skipped questions silently vanish.
**Impact:** User marks Q10 for later review, skips it, submits test. Q10's mark is never recorded — palette state is lost. Undermines the "marked" analytics on the results page.
**Fix:** In `finish()`, iterate the union of `responses` and `review_marks` keys; for questions in `review_marks` but not `responses`, insert a `test_responses` row with `selected_option=NULL, is_correct=0, marked_for_review=1`. Alternatively, extend `unanswered_count` semantics to include marked-but-unanswered.
**Effort:** hours

### F06: `/diag/<token>` gate is authorization-by-substring-of-secret
**Severity:** critical
**Category:** B
**Location:** `bp_diag.py:16-18`, `auth.py:117`
**Evidence:**
```python
def _authorized(token):
    secret = current_app.config.get("JWT_SECRET") or ""
    return bool(secret) and token == secret[:16]
```
`_PUBLIC_ENDPOINTS` includes `"diag.diag"` and `"diag.force_seed"` so both are reachable pre-auth. The gate compares against the first 16 chars of `JWT_SECRET` — a URL leak (via referrer, browser history, proxy log, screenshot) discloses enough entropy to (a) call `/setup/seed/<token>?username=x&password=y` and take over any account and (b) is derivable from `JWT_SECRET` used to sign session tokens. `/diag` also happily returns `?probe_pw=<val>` — a **built-in password oracle** against the stored admin hash, no rate limit, no logging. Anyone who ever sees the token URL owns the platform.
**Impact:** Full account takeover; enumerate password via `probe_pw`; DB stats leak via `/diag`. Even without the URL, a substring compare on 16 chars is not authorization.
**Fix:** Delete both routes (comment in file says "removed once the platform is stable — kept for one-time bootstrap"). If they must survive, gate them with `@require_admin` and drop `probe_pw` entirely. Remove `"diag.diag"` and `"diag.force_seed"` from `_PUBLIC_ENDPOINTS`.
**Effort:** minutes

### F07: `topic_id` and `topic_name` cached in session snapshot go stale on edit
**Severity:** medium
**Category:** A
**Location:** `bp_tests.py:126`, `bp_admin.py:719-748`
**Evidence:** Test setup dumps full question dicts into `session["questions"]` at line 126. `finish()` reads `r.get("topic_id")` from `session["responses"]` (populated by `submit_answer` which copies `q.get("topic_id")` from the session snapshot). If an admin re-classifies question X to a new topic mid-test (via `/admin/questions/<qid>/edit`), the running test still writes `error_log.topic_id` and `topic_mastery` updates against the *stale* topic. Solo user today, but the fact that `topic_id` is duplicated in three places (questions row, session dict, test_responses via error_log) means one canonical fact has three faces.
**Impact:** Historical `test_responses` rows keep the frozen answer (correct — audit trail); but `topic_mastery` updates hit the wrong topic. Weakness heatmap misattributes.
**Fix:** In `finish()`, re-fetch each question's current `topic_id` from `questions` before writing `error_log`. Do not persist derived topic on `test_responses` (it already joins).
**Effort:** hours

### F08: Palette state = full question dicts serialized into filesystem session
**Severity:** medium
**Category:** C
**Location:** `bp_tests.py:126`, `config.py:20-22`
**Evidence:** `session["questions"] = [dict(q) for q in selected]` stores the entire text + all four options + explanation per row. For a 100-Q test that is easily 200 KB per session file. Flask-Session uses filesystem backend (`SESSION_TYPE = "filesystem"`, `SESSION_FILE_DIR = data/flask_session`). Every request (`/api/question/<idx>`, `/api/submit_answer`, `/api/mark_for_review`) re-reads and re-writes the entire pickled blob. On a slow filesystem or Render's ephemeral disk, this compounds fast. **The bp_admin.py:24 comment even admits it**: "Flask-session's filesystem backend rejects payloads this large". For that reason the extraction cache lives in a module dict, but tests still ride the session.
**Impact:** Slow per-question paint; filesystem I/O on every keystroke through the palette; Render ephemeral disk pressure. Also, on scale, sessions are per-user — multiplies quickly if multi-user lands.
**Fix:** Store only `session["question_ids"] = [q["id"] for q in selected]` and load the current question via `db.execute("SELECT ... WHERE id=?")` in `/api/question/<idx>`. `submit_answer` already keys by question_id in `responses`. Cost is one indexed lookup per navigation — cheaper than deserializing the full test.
**Effort:** hours

### F09: `_run_alter_migrations` swallows *all* exceptions including real schema errors
**Severity:** high
**Category:** D
**Location:** `db.py:205-231`
**Evidence:**
```python
for sql in migrations:
    try:
        db.execute(sql)
    except Exception as e:
        print(f"[migration skip] {sql}: {e}")
```
The comment says "Now that turso_patch raises on real Hrana errors, this except no longer masks schema drift" — but the `except Exception` is still too broad. A network blip against Turso mid-ALTER logs to stdout and moves on. `print()` to stdout is unstructured — Render's log viewer swallows it into the sea of gunicorn access lines. The user's memory MEMORY.md explicitly flags this: "Turso `questions` table missing `disabled`/`updated_at`; turso_patch silently swallows insert errors on bad columns."
**Impact:** Schema drift goes unnoticed until a query at request time explodes. MEMORY.md is the receipt for this bug already firing in production.
**Fix:** Catch only `sqlite3.OperationalError` and inspect the message: skip if it contains "duplicate column"; **re-raise** anything else so init_db bails visibly. Log via `logging.getLogger(__name__).warning(...)` not `print()`.
**Effort:** hours

### F10: `check_auth` swallows any `verify_token` exception silently via broad except
**Severity:** medium
**Category:** B
**Location:** `auth.py:120-131`
**Evidence:** `verify_token` catches only `ExpiredSignatureError` and `InvalidTokenError` — but PyJWT can also raise `DecodeError`, `ImmatureSignatureError`, `InvalidAudienceError`, `InvalidIssuerError`, etc. Those subclass `InvalidTokenError` so the current except catches them. **However**, if `current_app.config["JWT_SECRET"]` is `None` (misconfigured), `jwt.decode` raises `TypeError` — NOT caught — bubbles into `check_auth` where the `before_request` handler crashes with 500 on every request instead of falling back to login redirect. In `_fill_secret_fallbacks` in prod we `raise RuntimeError` if `JWT_SECRET` is missing at boot, so this shouldn't happen; but the layered exception handling is brittle.
**Impact:** Latent — activated only if JWT_SECRET is unset in prod, which the boot check catches. Still: defensive programming failure that reads as an accident waiting to happen.
**Fix:** Wrap `verify_token` in try/except `Exception` and treat any error as "no token"; the caller path already handles that. Additionally: on `probe_pw`-style diagnostics, never accept the raw password over the wire (already covered in F06).
**Effort:** minutes

### F11: No indexes on hot-path columns
**Severity:** high
**Category:** C
**Location:** `db.py:28-172` (schema), cross-cutting queries
**Evidence:** The only indexes created by `init_db()` are `idx_bookmarks_qid` and `idx_trigrams_trigram`. Queries that fire on every dashboard render:
* `questions WHERE (disabled IS NULL OR disabled = 0) AND topic_id = ?` — full-scan on ~3712 rows
* `error_log JOIN questions ON el.question_id = q.id WHERE date(el.sr_due_at) <= date('now')` — full scan of error_log for the SR pill
* `test_responses WHERE test_id = ?` — full scan for `/results/<id>`
* `topic_mastery WHERE topic_id = ?` — reasonable via UNIQUE, but explicit index would help
* `questions WHERE pyq_year BETWEEN ? AND ?` — full scan for the PYQ setup filter
* `error_log JOIN topics ON topic_id = t.id` — full scan

Turso is a network hop per query; each full scan is measurably slower than local SQLite.
**Impact:** Every dashboard render is O(N) across four tables. Adds up on Render's cold start. Palette re-render fetches the full question set every hop.
**Fix:** Add: `CREATE INDEX idx_questions_topic ON questions(topic_id)`, `CREATE INDEX idx_questions_disabled ON questions(disabled)`, `CREATE INDEX idx_questions_pyq_year ON questions(pyq_year)`, `CREATE INDEX idx_error_log_sr_due ON error_log(sr_due_at)`, `CREATE INDEX idx_error_log_question ON error_log(question_id)`, `CREATE INDEX idx_test_responses_test ON test_responses(test_id)`, `CREATE INDEX idx_error_log_resolved ON error_log(resolved, created_at)`. Wrap each in `IF NOT EXISTS` so init_db is idempotent.
**Effort:** hours

### F12: `question_flags`, `error_log`, `bookmarks`, `synthesis_batches`, `doubt_cache` all missing `question_id` / composite indexes
**Severity:** medium
**Category:** C
**Location:** `db.py:59-172`
**Evidence:** In addition to F10, admin flows have their own scan surface: `question_flags WHERE status='open' ORDER BY created_at DESC` is a full table scan every dashboard render; `doubt_cache WHERE cache_key=?` is UNIQUE (implicit index) — OK; `synthesis_batches ORDER BY id DESC LIMIT 20` — the primary key handles this; but `bookmarks WHERE question_id = ?` has the UNIQUE index (good).
**Impact:** Admin dashboard is slow after enough flags accumulate. Not urgent but easy fix.
**Fix:** Add `CREATE INDEX idx_flags_status_created ON question_flags(status, created_at DESC)`.
**Effort:** minutes

### F13: `error_log` has no UNIQUE constraint on (test_id, question_id)
**Severity:** high
**Category:** D
**Location:** `db.py:59-69`, `bp_tests.py:274-281`
**Evidence:** `finish()` inserts one `error_log` row per wrong `test_responses` — but the schema has no `UNIQUE(test_id, question_id)`. If `finish()` is called twice for the same test (double-submit on the results button, browser back+resubmit, network retry), duplicate `error_log` rows get created. Then `record_review` advances only one, and the SR queue shows two cards for the same historical error at box 1.
**Impact:** Duplicate SR cards; skewed by_box counts; user reviews the same lapse twice. `mock_tests` also has no `UNIQUE(id)` guard on second submission (test row gets updated in place, but responses/error_log get piled on).
**Fix:** Add `CREATE UNIQUE INDEX idx_error_log_test_question ON error_log(test_id, question_id)`; in `finish()`, guard by checking `status='completed'` on the mock_test row and 200-OK-noop if already finished. Or use `INSERT ... ON CONFLICT(test_id, question_id) DO NOTHING`.
**Effort:** hours

### F14: `int(request.form.get("num_questions", 50))` crashes on non-numeric input
**Severity:** low
**Category:** A
**Location:** `bp_tests.py:19`
**Evidence:** `num_qs = int(request.form.get("num_questions", 50))`. If the form field contains anything non-numeric (`"abc"` from a modified form, empty string from a bug in the setup UI), `int()` raises `ValueError` and Flask returns a 500 page. Same pattern exists for the other year fields but those wrap `try/except ValueError` (`bp_tests.py:60-66`).
**Impact:** Preventable 500. Small UX/reliability nit.
**Fix:** `try: num_qs = int(...) except (TypeError, ValueError): num_qs = 50` (mirror the pattern already used for year fields).
**Effort:** minutes

### F15: `topic_scores[None]` created when a question has no topic_id
**Severity:** low
**Category:** A
**Location:** `bp_tests.py:290-318`
**Evidence:** `tid = r.get("topic_id")` — if a question in the test bank has `topic_id IS NULL` (or if the session snapshot lost it), `topic_scores[None]` gets created and then the SQL `UPDATE topic_mastery SET ... WHERE topic_id=None` matches zero rows (NULL != NULL in SQLite). Silently drops a score update.
**Impact:** Rare — every seeded question has a topic. But if a synthetic question misses topic_id assignment (see F30 for the synth commit path), mastery updates go silently missing.
**Fix:** `if tid is None: continue` before the update. Log a warning so seed drift is visible.
**Effort:** minutes

### F16: No rate limiting on `/api/deep-dive` or admin synthesis endpoint
**Severity:** high
**Category:** B
**Location:** `bp_doubt.py:24`, `bp_admin.py:484`
**Evidence:** `/api/doubt/deep-dive` calls Gemini REST directly for every request. A logged-in user (or a compromised session cookie) can loop this endpoint and burn the shared Gemini quota. Cache hit avoids the LLM call, but a distinct `test_id` per request cache-busts trivially. Similarly, `/admin/api/synthesize/preview` calls Claude Opus per request with `max_tokens = 800 * n` — one request costs up to 40 × 800 tokens output. No throttle, no per-user quota, no request cooldown.
**Impact:** Runaway costs on Gemini/Anthropic bills. Solo-user today, but session cookie is JWT — theft = quota burn.
**Fix:** Add flask-limiter with per-user + per-IP token bucket. For `/deep-dive`, 30/hour is generous. For `/admin/api/synthesize/preview`, 5/hour + require re-entering admin password (a "sensitive-action" gate).
**Effort:** hours

### F17: `datetime.utcnow()` is deprecated in Py3.12; timezone confusion
**Severity:** low
**Category:** A
**Location:** widespread — `bp_admin.py:47,97,101,110`, `bp_api.py:47,192`, `bp_diag.py`, etc.
**Evidence:** Mix of `datetime.now().isoformat()` (naive, local time), `datetime.utcnow().isoformat()` (naive, UTC, deprecated), and `datetime.now(datetime.timezone.utc).isoformat()` (proper). `sr.py:144` uses `datetime.now().isoformat()` for `sr_last_reviewed` (local); `bp_tests.py:246-247, 279` uses `datetime.now().isoformat()` for `completed_at` + `error_log.created_at`. Local time. But `date('now')` in SQL evaluates at UTC (SQLite default). So a study session at 11 PM IST logs `2026-07-19` in Python but `date('now')` in the same request returns `2026-07-19` UTC (which is a different Rajasthan day). The consistency chart, streak counter, and "due today" all use `date('now')` — timezone mismatch between write and read.
**Impact:** Off-by-one day on the streak counter and SR "due today" count during evening study sessions (India is +5:30). Study session logged at 11 PM IST 2026-07-19 might show up in the 2026-07-20 UTC bucket. Consistency score drifts by one day per session, but averages out.
**Fix:** Standardize on `datetime.now(datetime.timezone.utc).isoformat()` for writes and `date('now')` reads — both UTC. Or move to a fixed "Asia/Kolkata" for both. Add an `app_tz` config setting.
**Effort:** hours

### F18: `INSERT INTO settings ... INSERT OR REPLACE` overwrites user config on every boot
**Severity:** low
**Category:** D
**Location:** `db.py:84-90`
**Evidence:** The schema uses `INSERT OR IGNORE` for defaults — good, idempotent. But `bp_api.py:169-176` (`/api/settings`) uses `INSERT OR REPLACE` for user-supplied writes. That's fine; but F01 already flagged the endpoint gap. Note: schema `INSERT OR IGNORE` is fine on Turso only because rows are already inserted; if a user later admin-deletes a settings row it will be silently re-seeded on next boot with the original default (their intentional deletion undone). Not a bug per se, but a foot-gun.
**Impact:** Behavior surprise if a user manually deletes a settings key expecting it to stay gone.
**Fix:** Document the behavior in the settings model, or add a `settings_deleted_at` marker to suppress re-seed.
**Effort:** minutes

### F19: `taps` on `error_log` join to `topics` on `el.topic_id` — but `error_log.topic_id` can drift from `questions.topic_id`
**Severity:** medium
**Category:** D
**Location:** `bp_errorlog.py:22-24`, `bp_main.py:234-241`
**Evidence:** `error_log` stores its own copy of `topic_id`, copied from the session snapshot at insert time. If an admin re-classifies the question afterwards (`/admin/questions/<qid>/edit` allows changing `topic_id`), the error_log row keeps the *old* topic. The dashboard's "recent errors" join `error_log el JOIN topics t ON el.topic_id = t.id` and `error_log el JOIN questions q ON el.question_id = q.id` — so the topic name shown for an old error may not match the current question's topic. This is intentional-ish (audit trail) but creates split-brain in the SR review view (`sr.py:65-79`): `JOIN topics t ON t.id = el.topic_id` uses the frozen id, so the review card shows the historic topic while the underlying question may now belong to a different topic.
**Impact:** Confusing SR cards; weakness heatmap counts the error against the old topic while the mastery grid updates the new topic.
**Fix:** Drop `error_log.topic_id` — always join via `questions.topic_id`. One authoritative fact.
**Effort:** hours

### F20: `test_responses` insert does not persist confidence + no per-response mark-for-review update path
**Severity:** low
**Category:** D
**Location:** `bp_tests.py:260-268`
**Evidence:** Schema has `confidence TEXT DEFAULT 'medium'` on `test_responses` but nothing writes it — dead column. `submit_answer` (`bp_api.py:113-144`) accepts no confidence field, and `finish()` inserts with default. Also `marked_for_review` is only written at finish time — the flag can be toggled multiple times mid-test, and only the final state persists. Fine, but the schema hints at a per-response confidence-check that never got implemented.
**Impact:** Dead schema field; documentation debt.
**Fix:** Either remove the column or wire it up via the confidence radio described in Plan A. Same for `error_type` (currently derived from time_spent < 10s — coarse heuristic).
**Effort:** minutes to remove; hours to wire up

### F21: `check_auth` requires session or cookie — but session token can outlive JWT expiry
**Severity:** medium
**Category:** B
**Location:** `auth.py:120-131`, `bp_auth.py:20-35`
**Evidence:** Login sets **both** the cookie AND `session["auth_token"]`. Cookie has `max_age = JWT_EXPIRY_HOURS * 3600`; the JWT payload expires exactly then. But `session["auth_token"]` lives as long as Flask session cookie (which by default has no explicit expiry beyond browser session). At `check_auth`, `token = request.cookies.get("auth_token") or session.get("auth_token")` — session token used as fallback. Since `verify_token` re-checks `exp`, an expired JWT in the session is rejected. So session doesn't actually extend life beyond JWT `exp`. OK — but the design pattern is muddled. On `/logout`, session cookie is popped, but the cookie survives on the client until browser cache-clear. If the JWT is still within its `exp` window, a copy of the cookie value from clipboard/logs will re-auth.
**Impact:** Confused separation of concerns; makes token revocation impossible (no server-side denylist). Solo user, not critical, but multi-user makes this bite.
**Fix:** Skip the `session["auth_token"]` fallback — cookie is the only source of truth. For revocation, add a `token_jti` claim and a `revoked_jtis` table checked on each request.
**Effort:** hours

### F22: Silent lastrowid=None handling in `push_extracted_to_turso`
**Severity:** medium
**Category:** D
**Location:** `push_extracted_to_turso.py:112-114`
**Evidence:**
```python
if res.lastrowid is None:
    print(f"    !! insert failed silently for Q section={section}")
    continue
```
Prints and moves on. If the Turso adapter returns `lastrowid=None` (e.g. because the INSERT hit an unhandled column via schema drift), the script counts a *successful* insert (f_inserted += 1 happens above the print, oh wait — actually it happens at line 115 AFTER the guard: `f_inserted += 1` is outside the `if` block. Reading more carefully: `f_inserted += 1` is at line 115, and the guard `if res.lastrowid is None` at 112-114 does `continue` before reaching 115. So counter is correct.) — but the row wasn't inserted, and no exception, no exit code change. The user's memory MEMORY.md flags exactly this pattern as the reason schema drift went unnoticed.
**Impact:** Batches may claim success while dropping rows. Manual audit needed against source PDFs.
**Fix:** After turso_patch's stricter error handling (already applied per docstring), `lastrowid=None` in an insert should be treated as an error — raise or return non-zero exit. Add a final row-count assertion.
**Effort:** minutes

### F23: `SYNTHESIS_PROMPT` cache cap-calculation math off-by-something
**Severity:** low
**Category:** A
**Location:** `bp_admin.py:509-523`
**Evidence:**
```python
max_new = max(0, int((active + count) * 0.4) - synth)
if count > max_new and active > 0:
    return jsonify({...}), 400
```
`active` includes existing synthetics (both live rows). `(active + count) * 0.4 - synth` — if the user asks for count new synthetics, after commit the total synthetic count would be `synth + count`, but only ~count of the requested batch actually get committed by admin selection (see `/synthesize/<id>/commit` — takes selected checkboxes). Cap enforces against **requested**, not **committed** — so admin can request 40 and only commit 10, but is blocked from requesting 40 in the first place. Additionally, `active` here is the count of active rows *including* pre-existing synthetics; adding synthetics grows both `synth` and `active`, which relaxes the cap over time.
**Impact:** Overly strict on the request path; slightly relaxed after commit. Not exploited today but the arithmetic is muddled.
**Fix:** Cap = `int(active_non_synthetic * 0.4 / 0.6) - synth`, then round. Comment the derivation.
**Effort:** minutes

### F24: `SUBTOPIC_MAP` fallback breaks re-ingestion determinism
**Severity:** low
**Category:** A
**Location:** `content_metadata.py:134-142`, `_normalize_section`
**Evidence:** `_normalize_section` returns the raw section string as-is when it's not in `SUBTOPIC_MAP`. So `"Java"` stays `"Java"` — but `"C"` also stays `"C"` (a single character, poor sub_topic value). More importantly, if a future admin adds `"C"` to `SUBTOPIC_MAP` with a different canonical form (`"Programming C"`), all existing rows keep the old `"C"` while new rows get `"Programming C"` — schema drift within `sub_topic` values that becomes hard to reconcile after the fact.
**Impact:** `sub_topic`-based analytics counts double for renamed entries. Small but nudges the "distinct sub_topic list" toward noise.
**Fix:** Add a smoke test that lists all distinct `sub_topic` values after backfill; document that adding a new key requires backfilling old rows.
**Effort:** hours

### F25: FTS5 rebuild in migration script uses `('rebuild')` which fails on some Turso builds
**Severity:** medium
**Category:** G
**Location:** `scripts/migrate_add_fts5_search.py:67`, `db.py:246-257`
**Evidence:** Migration comments even admit "rebuild fails on some libSQL builds even after triggers work. New questions will still index via triggers, existing rows may be missing." The `init_db()` FTS5 setup in `db.py:246-257` only runs the CREATE VIRTUAL TABLE + triggers, never a rebuild. If FTS5 is created *after* rows exist (which is the case on Render), the FTS index is empty for all pre-existing rows. Search silently degrades to LIKE fallback for them.
**Impact:** 3,712 existing questions are invisible to FTS5 unless the migration was run with rebuild succeeding. Search performance drops to LIKE for the historic content.
**Fix:** After the FTS5 create in init_db, run `INSERT INTO questions_fts(questions_fts) VALUES('rebuild')` in its own try/except with a loud logger.warning on failure. Or run rebuild in a background thread on first boot.
**Effort:** minutes

### F26: `NEG_PRESETS` dictionary defined inside a POST handler — reallocated every request
**Severity:** low
**Category:** C
**Location:** `bp_tests.py:32-37`
**Evidence:** The preset dict is re-constructed on every POST to `/test/setup`. Trivial cost per request but symptomatic of style debt. Same for the `FLAG_CATEGORIES` set in `bp_api.py:10-18` (that one is module-level, correct).
**Impact:** Negligible.
**Fix:** Hoist `NEG_PRESETS` to module level.
**Effort:** minutes

### F27: `mock_tests.status` values inconsistent
**Severity:** low
**Category:** D
**Location:** `db.py:39-48`, `bp_tests.py:117`, `bp_tests.py:246`
**Evidence:** Schema default is `status TEXT DEFAULT 'in_progress'`. Insert uses `"in_progress"`. Update on finish uses `status="completed"`. No `abandoned` state — so a user who starts a test and never finishes leaves the row forever `in_progress`, cluttering `/analytics` counts (though most queries filter `status="completed"`). Consistency query uses `status='completed'`. OK, but no cleanup path for abandoned tests.
**Impact:** Cruft in `mock_tests` table.
**Fix:** Add a nightly job (or on-login sweep) marking `in_progress` older than 24h as `abandoned`. Or reuse the row on next `/test/setup` if user has a `in_progress` row.
**Effort:** hours

### F28: `flask-session` filesystem backend not garbage-collected
**Severity:** low
**Category:** G
**Location:** `config.py:21-22`, `app.py`
**Evidence:** `SESSION_TYPE="filesystem"` + `SESSION_FILE_DIR="data/flask_session"`. Flask-Session does NOT prune expired session files automatically. Every login creates a new one; older files linger indefinitely on the ephemeral Render disk.
**Impact:** Disk creep over months. On Render's ephemeral disk this resets every deploy so it's naturally bounded, but on a persistent disk (Turso-only-DB doesn't help here) it grows.
**Fix:** Wire a small cron (or in-app APScheduler task) that deletes session files older than, say, 30 days. Or move to server-side JWT-only auth and drop Flask-Session entirely.
**Effort:** hours

### F29: `_chat_histories` in-memory dict grows unbounded across worker lifetimes
**Severity:** low
**Category:** C
**Location:** `ai_utils.py:124-135`
**Evidence:** Chat histories are cached in a module-level dict, keyed by `(question_id, test_id)`. Per-entry the last 20 messages are kept. No LRU, no eviction beyond per-key trim. Over a long-running gunicorn worker, the dict grows monotonically. Turnkey solo-user so bounded by ~thousand entries, but no mechanism prevents runaway growth if an attacker (see F16) hits `/api/doubt/chat` with rotating IDs.
**Impact:** Memory creep; Render's 512 MB free-tier gets uncomfortable.
**Fix:** Add an `LRUCache(maxsize=200)` wrapper around `_chat_histories`, or persist to `doubt_cache`-like table.
**Effort:** hours

### F30: `synthesize_commit` doesn't handle "notes" field missing in some rows
**Severity:** low
**Category:** A
**Location:** `bp_admin.py:661-663`
**Evidence:** `explanation = f"{explanation}\n\n[Reviewer note: {q['notes']}]"` runs when `q.get("notes")` is truthy. `q["notes"]` is accessed directly (not `.get`), which is safe because the guard runs first. OK. But directly below: `q.get("notes") or None` for `review_notes` — evaluates empty string to None, correct. The mismatch: in `upload_import` at line 981, same pattern; in `metadata_from_json_question` at line 459, `q.get("notes") or None`. All three consistent — good. **Bigger issue nearby**: the commit path does not compute trigrams for synthetic rows (contrast with `upload_import` at `bp_admin.py:1019-1029` which does). So synthetic rows are invisible to `/admin/duplicates` until a manual trigram rebuild.
**Impact:** Duplicate detection misses synthetic vs synthetic and synthetic vs PYQ collisions until `build_trigram_index --rebuild` runs.
**Fix:** Duplicate the trigram-compute block from `upload_import` into `synthesize_commit`. Even simpler: extract a helper `_index_new_question(db, qid, question_text)`.
**Effort:** minutes

### F31: `/setup/seed/<token>?password=` stores password in Render access logs
**Severity:** critical
**Category:** B
**Location:** `bp_diag.py:70-114`
**Evidence:** Method accepts both GET and POST. Query-string password is a common pattern that leaks into: browser history, HTTP referrer, proxy logs, Render's access log, Turso's request logs (via the diag DB probes), and CDN caches. The commit history reference (b78b8a1) says "Add ?password= override to /setup/seed to bypass env-var corruption" — a workaround that is now a permanent leak surface.
**Impact:** Admin password shows up in Render logs verbatim. Anyone with log-view access owns the account.
**Fix:** As with F06 — remove the endpoint entirely once bootstrap is done. If it must survive, accept password ONLY via POST body (not query string), and log a `Set-Cookie: password_used_at=...` marker so the admin can audit last-use.
**Effort:** minutes

### F32: SQL injection latent risk via `topics_str` split not-really-defended
**Severity:** low
**Category:** B
**Location:** `bp_tests.py:78-82`
**Evidence:**
```python
topic_ids = [x.strip() for x in topics_str.split(",") if x.strip()]
placeholders = ",".join("?" * len(topic_ids))
query += f" AND t.id IN ({placeholders})"
params.extend(topic_ids)
```
Placeholders are correctly parameterized — not injectable. But the sibling path uses raw interpolation:
```python
weak_topic_ids = [str(t["topic_id"]) for t in db.execute(...)]
if weak_topic_ids:
    query += f' AND t.id IN ({",".join(weak_topic_ids)})'
```
Safe today because ids come from DB, but the pattern is a mine for future refactors. Same at `bp_admin.py:339, 353` (IN-clauses built via `",".join("?" * n)`). Those are OK because they use placeholders.
**Impact:** No injection today. But whoever refactors `focus_weak` to accept user-supplied ids may inline the same pattern without noticing.
**Fix:** Use placeholders in `focus_weak` too — cheap style consistency: `placeholders = ",".join("?" * len(weak_topic_ids)); query += f" AND t.id IN ({placeholders})"; params.extend(weak_topic_ids)`.
**Effort:** minutes

### F33: `_find_duplicate_pairs` query is O(trigrams²) if HAVING pre-filter fails
**Severity:** medium
**Category:** C
**Location:** `bp_admin.py:274-317`
**Evidence:** The CTE self-joins `question_trigrams` (indexed on `trigram`, good). `HAVING COUNT(*) >= 15` prunes but only after grouping. On 3,712 questions × avg 100 trigrams each = 371,200 trigram rows. Self-join on trigram groups everything sharing a trigram. Even with the index this materializes a large intermediate. Turso will probably time out on the first click of `/admin/duplicates` after a full data load unless the index is warm.
**Impact:** `/admin/duplicates` can hang or error out. The `try/except` in `_find_duplicate_pairs` returns `[]` — user sees "no duplicates" and moves on.
**Fix:** Precompute Jaccard offline via `scripts/build_trigram_index.py --pairs`, store in a `duplicate_candidates(q1, q2, jaccard)` table refreshed nightly. UI queries a pre-materialized table.
**Effort:** days

### F34: No test coverage on the SR promotion path
**Severity:** medium
**Category:** G
**Location:** `tests/test_sr.py`, `bp_review.py`
**Evidence:** `test_sr.py` covers `next_box`, `next_due`, `days_until_due` — good. But it does NOT cover `record_review` end-to-end (which is where the DB write and box promotion race). Also no test for the `finish()` → `error_log` seeding side effect. If a refactor breaks the JOIN between `record_review` and `error_log`, no red bar.
**Impact:** SR is the flagship v2 feature; regressions would go unnoticed until a real study session.
**Fix:** Add `tests/test_review_flow.py`: seed a test, complete it with 2 wrong answers, assert `error_log` has two box-1 rows, hit `/api/review_answer` with `was_correct=True`, assert the row promotes to box 2 and sr_due_at moves +3 days.
**Effort:** hours

### F35: `/api/mark_for_review` payload accepts arbitrary index without CSRF or origin check
**Severity:** low
**Category:** B
**Location:** `bp_api.py:92-110`
**Evidence:** No CSRF token, no `Origin` header check. Cookies are `SameSite=Lax` which prevents cross-site POST (browser blocks the cookie) — reasonable defense. But a compromised page on the same origin can toggle marks. Solo user, minimal payload — low impact.
**Impact:** Very small — SameSite=Lax covers most vectors. Note the same laxity across `/api/*` and admin POST endpoints. Flask-WTF's CSRFProtect would add belt-and-suspenders.
**Fix:** Add flask-wtf CSRFProtect + inject `csrf_token()` in all forms + require it on state-changing POST endpoints. Or accept the Lax-only posture and document it.
**Effort:** hours

### F36: `bp_admin.uploads_view` doesn't validate MIME type or size before feeding to Anthropic
**Severity:** medium
**Category:** B
**Location:** `bp_admin.py:864-925`
**Evidence:** `f = request.files.get("pdf"); pdf_bytes = f.read()` — no `f.mimetype` check, no `len(pdf_bytes)` check. Anthropic charges per token; a hostile admin (unlikely, single-user) or a stray large file uploads 50 MB of noise and gets billed for tokenization before Claude even rejects.
**Impact:** Bill risk. Also, no defense against a non-PDF slipping through — Anthropic will error, but the pdf_uploads row will show status='error' after the API call, not before.
**Fix:** Validate `f.mimetype in ("application/pdf",)` and `len(pdf_bytes) < 20 * 1024 * 1024` (Anthropic's PDF hard limit is 32 MB). Reject early with 400.
**Effort:** minutes

### F37: Multi-user readiness — 7 tables have no `user_id` column
**Severity:** high
**Category:** I
**Location:** cross-cutting (`db.py:28-172`)
**Evidence:** Tables with per-user semantics but no user_id:
* `mock_tests` — every test row is "the user's"
* `test_responses` — belongs to a mock_test, transitively belongs to a user
* `error_log` — same
* `topic_mastery` — currently one row per topic (global); if multi-user, must become one row per (user, topic)
* `study_sessions` — per-user by intent, no column
* `bookmarks` — per-user by intent, no column
* `doubt_cache` — cache is fine to share, but the chat history within is per-user
Session state (`test_id`, `responses`, etc.) is already per-user via cookie. The moment we onboard a second user, the analytics dashboard mixes their data.
**Impact:** Multi-user launch requires either a full schema migration + data backfill (assign all existing rows to user_id=1) + rewriting every query to include `WHERE user_id=?`. Estimate: 2-3 days of focused work + a redeploy risk window.
**Fix:** Do the migration BEFORE onboarding user #2, not after. Add `user_id INTEGER REFERENCES users(id)` to each table with a `DEFAULT 1` and a migration script that stamps existing rows. Then wrap every query with `WHERE user_id = g.user_id`. Consider a global default-scoping middleware to prevent forgotten filters.
**Effort:** days

### F38: Turso token in `render.yaml` is a static long-lived JWT — no rotation surface
**Severity:** high
**Category:** I
**Location:** `render.yaml`, MEMORY.md deferred item
**Evidence:** MEMORY.md flags: "DEFERRED: rotate leaked Turso token — Live JWT committed in git history at e8907d4". `TURSO_AUTH_TOKEN` is a manual paste into Render env. Rotation blast radius = every request in flight during the swap fails; the app has no retry or credential refresh path.
**Impact:** Rotating the token today = brief outage. Not doing it = leak persists in git history.
**Fix:** (1) Rotate the token via `turso db tokens revoke` + `turso db tokens mint`; (2) Cache the current token in the app and reload from env on `SIGHUP` or via an admin endpoint; (3) Move to short-lived tokens with the Turso platform API. Deferred item; but the review flags it as still open.
**Effort:** hours

### F39: `sr_due_at` inserted as ISO date string, compared with `date('now')`
**Severity:** low
**Category:** A
**Location:** `sr.py:38-41`, `bp_tests.py:280`
**Evidence:** `next_due` returns `date.isoformat()` = `"YYYY-MM-DD"` (no time). `sr.py:74` and `bp_main.py:139-141` compare with `date(el.sr_due_at) <= date('now')`. `date(x)` on a `YYYY-MM-DD` string returns the same string, and on `date('now')` returns UTC today. Works. But if a caller ever writes `datetime.isoformat()` into `sr_due_at` (containing a time component), `date(x)` will still parse the date part correctly — resilient. Slight nit: `sr_last_reviewed` uses `datetime.now().isoformat()` (naive local) — inconsistent with the `date(...)` UTC compare.
**Impact:** No bug, just inconsistency. See F17 for the umbrella tz issue.
**Fix:** Standardize `sr_last_reviewed` to `datetime.now(datetime.timezone.utc).isoformat()`.
**Effort:** minutes

### F40: `_EXTRACTION_CACHE` in-memory dict lost on worker restart
**Severity:** medium
**Category:** D
**Location:** `bp_admin.py:24`
**Evidence:** Extraction preview state stored in a module dict. If gunicorn recycles the worker between `/uploads` and `/uploads/<id>/preview` (Render's default is 30-min timeout), the admin loses the preview and must re-upload the PDF, re-paying the Anthropic bill. Multi-worker deployments (Render default: 1 worker on free tier; but any autoscale adds workers) also mean workers don't share the cache — sticky sessions matter.
**Impact:** Silent data loss on worker recycle. Cost implication (re-billed for the Anthropic call).
**Fix:** Persist the extracted questions JSON to a temp table `pdf_extractions_temp(upload_id, questions_json, created_at)` with a 24h TTL. Read from there in `upload_preview`. Same for synthesis (`synth:<id>` keys).
**Effort:** hours

### F41: `init_db` on fresh Render deploy — Turso not idempotent for FTS5 rebuild
**Severity:** medium
**Category:** G
**Location:** `db.py:234-257`, `app.py:22-25`
**Evidence:** `init_db()` is called from `create_app()` inside a try/except that just logs on failure. On a fresh Turso DB, `SCHEMA` runs the CREATE TABLE IF NOT EXISTS (fine), then `_run_alter_migrations` runs 13 ALTERs (which the F09 too-broad-except swallows), then `_run_fts5_setup` creates the virtual table. But the FTS5 rebuild is NOT called from `init_db` — only from the standalone migration script. So on a truly fresh Turso DB with the app booting for the first time, `questions_fts` is empty until questions are inserted via triggers, and pre-existing questions (post `seed_data`) are indexed via the AFTER INSERT trigger. This is actually fine — but the flow is fragile and depends on order-of-operations across app boot + push_extracted_to_turso.
**Impact:** Search returns fewer hits than expected until a manual rebuild.
**Fix:** After `_run_fts5_setup` in `init_db()`, execute `INSERT INTO questions_fts(questions_fts) VALUES('rebuild')` inside a try/except — cheap on empty DB, correct on populated.
**Effort:** minutes

### F42: `bp_diag` routes registered without url_prefix — global `/diag`, `/setup/seed`
**Severity:** medium
**Category:** B
**Location:** `app.py:55` (`app.register_blueprint(diag_bp)` — no prefix), `bp_diag.py:13, 21, 70`
**Evidence:** Every other blueprint has a semantic prefix. Diag is registered at the root — `/diag/<token>` and `/setup/seed/<token>`. Combined with F06 (public endpoints), the URL is trivially guessable.
**Impact:** Attack surface at well-known URLs. Any recon script hits `/diag`, `/setup`, etc.
**Fix:** Move behind `/admin/diag` (already require_admin) or delete.
**Effort:** minutes

### F43: `check_password_hash` in `probe_pw` runs on every request — no throttle, no lockout
**Severity:** critical
**Category:** B
**Location:** `bp_diag.py:55-66`
**Evidence:** `probe_pw = request.args.get("probe_pw"); ... "matches": bool(stored and check_password_hash(stored, probe_pw))`. No per-IP rate limit. No exponential backoff. `check_password_hash` uses werkzeug's default (pbkdf2:sha256:600000) — slow, but 3-5/sec is achievable. 8-char alphanumeric is 218 trillion combos — infeasible; but a leaked 4-char prefix + dictionary attack against a memorable password lands in hours.
**Impact:** Password oracle. Same URL leak as F06 = same catastrophe.
**Fix:** Delete `probe_pw`. There is never a good reason for the app to confirm a password guess from a URL param.
**Effort:** minutes

### F44: `pdf_uploads` and `synthesis_batches` — no user_id, no cascade on user delete
**Severity:** low
**Category:** D
**Location:** `db.py:121-171`
**Evidence:** `pdf_uploads.uploaded_by` is a text username (not a FK). `synthesis_batches` has no `uploaded_by` at all. On admin delete via `/admin/users/<uid>/update` (which only toggles `is_active`), historical uploads keep pointing at the deleted username string. No cascade because there's no FK.
**Impact:** Orphan pointers; audit trail decays. Also blocks a clean "delete my data" flow if that becomes a requirement.
**Fix:** Add `uploaded_by_id INTEGER REFERENCES users(id)`, backfill from `users.username = pdf_uploads.uploaded_by`. Same for `synthesis_batches`. Consider `ON DELETE SET NULL`.
**Effort:** hours

### F45: `topics` delete cascades to nothing — questions with dangling `topic_id`
**Severity:** medium
**Category:** D
**Location:** `bp_admin.py:799-805`
**Evidence:**
```python
@bp.route("/topics/<int:tid>/delete", methods=["POST"])
def topic_delete(tid):
    db.execute("DELETE FROM topics WHERE id=?", (tid,))
```
Foreign keys are PRAGMA-off on Turso (see `db.py:14` "Turso/Hrana rejects them"). So there's no ON DELETE constraint firing. Deleting a topic leaves `questions.topic_id` pointing at a non-existent row. Every subsequent query joining `questions JOIN topics` drops those questions from the result — they disappear from tests, analytics, everything.
**Impact:** Data ghost. Once a topic is deleted, its questions are effectively hidden until the topic id is re-created or the questions are re-classified.
**Fix:** Before delete, check `SELECT COUNT(*) FROM questions WHERE topic_id=?`; refuse if non-zero. Or: on delete, `UPDATE questions SET topic_id = NULL WHERE topic_id = ?` and add a "no-topic" filter to the setup/analytics queries.
**Effort:** minutes

### F46: `sr_due_at` filter uses `date('now')` — no timezone override
**Severity:** medium
**Category:** A / I
**Location:** `sr.py:73-75`, `bp_main.py:139-141`, `bp_tests.py:279-281`
**Evidence:** SQLite's `date('now')` is UTC. `sr_due_at` written as local-date via Python `date.today()`. At 11 PM IST, `date.today()` = day N, `date('now')` = day N-1 (UTC). Card scheduled for day N is not yet "due" per UTC — user sees an empty queue during evening study. This is a specific symptom of F17.
**Impact:** Evening study sessions in India see an inaccurately empty SR queue. Confusing user experience during peak study hours.
**Fix:** Use `date('now', 'localtime')` (SQLite understands local per the server's tz) — but the server is UTC. Better: write `sr_due_at` in UTC (`(datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()`) so both sides agree.
**Effort:** minutes

### F47: `mock_tests.paper` = "both" invalidates all `paper1` / `paper2` analytics splits
**Severity:** low
**Category:** A
**Location:** `bp_tests.py:75-77`, `bp_analytics.py:185-192`
**Evidence:** `bp_tests.py:75-77` stores `paper` as "II", "I", or "both". Analytics queries at `bp_analytics.py:185-192` filter `WHERE paper="I"` and `WHERE paper="II"` — "both"-mode tests appear in *neither* pane. Recent 5-tests-per-paper counters silently drop them.
**Impact:** Analytics undercounts. A user running mostly "both"-mode tests sees an empty paper-I recent-tests panel.
**Fix:** For "both"-mode, split responses by their question's `topic.paper` at read time. Or store `paper='mixed'` and add a third pane. Or refuse `paper='both'` as too coarse — force the user to pick.
**Effort:** hours

### F48: No test verifying migrations run to completion on fresh Turso
**Severity:** medium
**Category:** G
**Location:** `tests/test_boot_with_turso.py`, `scripts/verify_phase6.py`
**Evidence:** `verify_phase6.py` exists but is one-shot phase-scoped. The user's memory (MEMORY.md) flags exactly this: "Turso schema drift — questions table missing disabled/updated_at". No CI/CD hook that runs `PRAGMA table_info(questions)` against Turso and asserts every expected column. `_run_alter_migrations` runs on each boot, and F09 shows it can silently skip.
**Impact:** Schema drift can persist across many deploys before being noticed via a downstream 500.
**Fix:** Add a `scripts/verify_schema.py` that: runs `PRAGMA table_info` on every table, compares to an in-repo `expected_schema.json`, exit 1 on mismatch. Run in CI + as a Render pre-deploy hook.
**Effort:** hours

### F49: `finish()` allows double-submit — no idempotency key
**Severity:** medium
**Category:** A / D
**Location:** `bp_tests.py:194-198`
**Evidence:** No check that `mock_tests.status = 'in_progress'` before writing. Refreshing `/test/finish` (which is POST — but browsers do sometimes replay) inserts a second batch of `test_responses` rows for the same test_id + question_id (no UNIQUE — F13). Also writes another batch of `error_log` rows. Also runs the topic_mastery EMA update twice — score drifts.
**Impact:** Duplicate rows + drifted mastery on any accidental double-submit. Discovered during a survey of the flow, not observed in prod, but the vulnerability is present.
**Fix:** First line of `finish()`: `row = db.execute("SELECT status FROM mock_tests WHERE id=?", (test_id,)).fetchone(); if row and row["status"] == "completed": return redirect(...)`. Or wrap the entire write path in a SAVEPOINT/transaction.
**Effort:** minutes

### F50: `paper_perf` query on dashboard misses `paper='both'` and `paper=NULL`
**Severity:** low
**Category:** A
**Location:** `bp_main.py:247-250`
**Evidence:** `SELECT paper, COUNT(*), AVG(score) FROM mock_tests WHERE status="completed" GROUP BY paper` — returns rows for I, II, and *both* (if the user ran a mixed test) plus NULL. Template likely renders "both" and NULL as-is. Not a bug per se, but the template needs to guard.
**Impact:** UI oddity, potential empty label.
**Fix:** `GROUP BY paper` → `GROUP BY COALESCE(paper, 'unknown')`.
**Effort:** minutes


**Severity:** high
**Category:** C
**Location:** `db.py:28-172` (schema), cross-cutting queries
**Evidence:** The only indexes created by `init_db()` are `idx_bookmarks_qid` and `idx_trigrams_trigram`. Queries that fire on every dashboard render:
* `questions WHERE (disabled IS NULL OR disabled = 0) AND topic_id = ?` — full-scan on ~3712 rows
* `error_log JOIN questions ON el.question_id = q.id WHERE date(el.sr_due_at) <= date('now')` — full scan of error_log for the SR pill
* `test_responses WHERE test_id = ?` — full scan for `/results/<id>`
* `topic_mastery WHERE topic_id = ?` — reasonable via UNIQUE, but explicit index would help
* `questions WHERE pyq_year BETWEEN ? AND ?` — full scan for the PYQ setup filter
* `error_log JOIN topics ON topic_id = t.id` — full scan
Turso is a network hop per query; each full scan is measurably slower than local SQLite.
**Impact:** Every dashboard render is O(N) across four tables. Adds up on Render's cold start. Palette re-render fetches the full question set every hop.
**Fix:** Add: `CREATE INDEX idx_questions_topic ON questions(topic_id)`, `CREATE INDEX idx_questions_disabled ON questions(disabled)`, `CREATE INDEX idx_questions_pyq_year ON questions(pyq_year)`, `CREATE INDEX idx_error_log_sr_due ON error_log(sr_due_at)`, `CREATE INDEX idx_error_log_question ON error_log(question_id)`, `CREATE INDEX idx_test_responses_test ON test_responses(test_id)`, `CREATE INDEX idx_error_log_resolved ON error_log(resolved, created_at)`. Wrap each in `IF NOT EXISTS` so init_db is idempotent.
**Effort:** hours



