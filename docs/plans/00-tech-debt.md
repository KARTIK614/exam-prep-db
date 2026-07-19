# 00 — Tech Debt Remediation Plan

**Scope:** Three carry-over items from the 2026-07-14/15 extraction-push session. Planning only — no implementation in this document.

**Target reader:** Kartik executing solo, one item at a time, verifying before moving to the next.

**Related memory:**
- `project_turso_schema_drift.md` — schema mismatch context
- `project_turso_token_rotation.md` — leaked-token history

---

## Contents

1. [Item #1 — Silent Hrana error swallowing in `turso_patch`](#item-1--silent-hrana-error-swallowing-in-turso_patch)
2. [Item #2 — Schema drift on Turso `questions` table](#item-2--schema-drift-on-turso-questions-table)
3. [Item #3 — Two leaked Turso auth tokens](#item-3--two-leaked-turso-auth-tokens)
4. [Verification & smoke tests](#verification--smoke-tests)
5. [Execution checklist](#execution-checklist)

---

## Item #1 — Silent Hrana error swallowing in `turso_patch`

**Severity:** HIGH
**Effort:** 1.5–2.5 hours
**Blocks:** #2 verification, all future admin PDF uploads, all future bulk imports.

### Root cause

`turso_patch.py:_post` (lines 79-88) posts a Hrana v2 pipeline request and only raises on non-2xx HTTP responses. Hrana's actual failure mode is a 200 OK with a per-request error inside `results[i]` — the shape looks like:

```
{"results": [
  {"type": "error", "error": {"message": "no column named disabled", "code": "SQLITE_UNKNOWN"}}
]}
```

Meanwhile `turso_patch.py:TC.__init__` (line 104) only raises when `resp.get("type") == "" AND "error" in result_envelope` — that check inspects the *envelope* not the *response*, and expects a top-level `error` key that Hrana does not emit at that level. The result: `TC` builds an empty cursor with `lastrowid = None` and no exception. Caller assumes success.

Session evidence: `push_extracted_to_turso.py` first run reported "inserted 2433 questions" while `SELECT COUNT(*)` delta was 0. Fixed only by removing unknown columns (`disabled`, `updated_at`) from the INSERT list. The same bug lives in `bp_admin.py:396-413` (upload_import route) which still writes those columns.

### Fix approach

Replace both check-locations in `turso_patch.py` with a single response-shape inspector that handles the three real Hrana outcomes:

```
outcome A: results[i]["type"] == "ok" and "response" in results[i]
outcome B: results[i]["type"] == "error" and "error" in results[i]        ← current gap
outcome C: HTTP non-2xx                                                    ← already handled
```

**File `turso_patch.py`:**

- `_post` (line 79): after `r.raise_for_status()`, iterate `results = payload.get("results", [])` and for any entry where `entry.get("type") == "error"`, raise `sqlite3.OperationalError(f"Turso: {entry.get('error', {}).get('message', 'unknown')}")`. Include the SQL that failed if we can capture it (pass `requests_list` in for context). Return payload only if every entry is OK.
- `TC.__init__` (line 104): drop the current `resp.get("type") == "" and "error" in result_envelope` branch — it's dead code once `_post` raises early. Leaves TC as a pure response parser.
- `TR.execute` (line 157): no changes needed; the raise now propagates naturally.
- `TR.executemany` (line 162) and `TR.executescript` (line 172): they call `_post` in a loop of chunks. Each chunk that fails now raises. That's the right behavior — but they currently return `TC({})` on the empty-rows path (line 165) and don't return a cursor after a successful `_post`. Fix `executemany` to return the *last* chunk's parsed cursor (or a sentinel `TC` with `lastrowid` set from the last successful `last_insert_rowid`).

**Alternative (defense in depth):** even after fixing `_post`, add a caller-side guard in scripts that do bulk inserts:

```python
if res.lastrowid is None and sql.strip().upper().startswith("INSERT"):
    raise RuntimeError("silent INSERT failure")
```

`push_extracted_to_turso.py` already has this (line 112-114). Port the same pattern to `bp_admin.py:upload_import`.

### Migration sequence

```
1. Local: edit turso_patch.py per above
2. Local: run tests/test_turso_patch.py (see Verification section)
3. Local: run `python3 push_extracted_to_turso.py --dry-run` against a scratch
   Turso branch — expect exceptions on any bad column (there shouldn't be
   any after Item #2, but confirm behavior)
4. Deploy to Render (staging if you have one, else main). Watch logs.
5. Admin panel: upload a small test PDF (5-10 pages). Verify the imported row
   count matches num_extracted in the pdf_uploads row.
6. Production monitor for 24h: check pdf_uploads.num_imported vs
   num_extracted parity daily. Old uploads with divergent counts are
   evidence of pre-fix silent losses.
```

### Rollback plan

- Fix is local to `turso_patch.py`. Revert the file and redeploy.
- No data migration involved; no schema changes.
- If the new raise turns out to be too aggressive (some Hrana error we should tolerate), narrow the raise to specific `code` values and log the rest.

### Risk

**Medium.** Correctness upgrade, but throws exceptions where before things silently no-op'd. Any code path that was relying on "silent failure = keep going" will now blow up. Audit before deploying:

```
$ grep -rn 'try:.*execute\|.commit()\|sqlite3.OperationalError' *.py bp_*.py
```

Known callers that need to keep working:
- `db.py:_run_alter_migrations` (lines 124-134) — already has a broad `except Exception: pass`. Will keep working, but *the exception it's swallowing was masking Item #2*. Once #1 is fixed, its exceptions become visible via logging (add a `print(f"[migration skip] {sql}: {e}")` inside the except).
- `db.py:_seed_default_prompt` (lines 177-188) — same broad except. Add logging.
- `bp_admin.py` flag/edit routes — small INSERTs. Should work fine.

---

## Item #2 — Schema drift on Turso `questions` table

**Severity:** HIGH (currently, latently — all inserts route to Turso; local sqlite is bypassed)
**Effort:** 30 minutes if remote ALTER TABLE works; 2-3 hours if it doesn't and requires table rebuild.

### Root cause

`db.py:22-32` (`SCHEMA` string) declares `questions` with `id, topic_id, question_text, option_a-d, correct_option, explanation, difficulty, source, language`. `db.py:126-129` adds two additional columns via `ALTER TABLE`:

```
ALTER TABLE questions ADD COLUMN disabled INTEGER DEFAULT 0
ALTER TABLE questions ADD COLUMN updated_at TEXT
```

Turso's current `questions` table has neither. Cause chain:

```
db.py:init_db(app)
    └─ sqlite3.connect(DB_PATH)         ← DB_PATH contains "exam_prep"
         └─ turso_patch._patched_connect
             └─ returns TR(...)          ← Turso HTTP connection
    └─ db.executescript(SCHEMA)          ← CREATE TABLE IF NOT EXISTS — no-op on
                                            existing table, cannot add columns
    └─ _run_alter_migrations(db)         ← ALTER TABLE ADD COLUMN
         └─ db.execute("ALTER TABLE...")
             └─ TR.execute → _post → Hrana returns error → SILENT (Item #1)
             └─ Python side sees no exception
         └─ except Exception: pass       ← never actually triggered because
                                            no exception was raised
```

So the migration silently no-op'd, both columns are missing on Turso, but every startup logs no error and `_run_alter_migrations` believes it succeeded.

Local sqlite file at `data/exam_prep.db` doesn't get the columns either, because turso_patch intercepts the "exam_prep" path — the local file is effectively dead code when TURSO_DB_URL is set.

### Fix approach

Two options — pick based on data safety:

**Option A (recommended — low risk):** run the two ALTER TABLEs manually against Turso once, then let the existing `_run_alter_migrations` no-op on future boots. Turso does support `ALTER TABLE ADD COLUMN` for both INTEGER and TEXT with defaults.

  ```
  ALTER TABLE questions ADD COLUMN disabled INTEGER DEFAULT 0;
  ALTER TABLE questions ADD COLUMN updated_at TEXT;
  UPDATE questions SET disabled = 0 WHERE disabled IS NULL;
  ```

**Option B (heavier — if ALTER fails):** create `questions_new` with the full column set, copy rows, drop old, rename. Standard SQLite migration pattern. Only needed if Option A errors — SQLite/libSQL supports ALTER ADD COLUMN just fine so this is unlikely.

Execute via a one-shot script `scripts/migrate_questions_schema.py`:

```
1. connect via turso_patch
2. PRAGMA table_info('questions') — list existing columns
3. If 'disabled' not present:  ALTER TABLE questions ADD COLUMN disabled INTEGER DEFAULT 0
4. If 'updated_at' not present: ALTER TABLE questions ADD COLUMN updated_at TEXT
5. Print row count before/after (must be equal)
6. Print PRAGMA table_info after (assert both columns now visible)
```

Note: run this AFTER Item #1 is deployed so any hidden failure surfaces as an exception rather than a silent no-op. Otherwise you'll write a script that reports success and Turso is still unchanged.

**Optional but nice-to-have:** also add `language` if it's missing (the SCHEMA declares it, but same drift risk applies), and `confidence` as a new column so the JSON extractions can preserve their `confidence` field instead of losing it.

### Migration sequence

```
1. Deploy Item #1 first (turso_patch fix). Verify. Do NOT skip.
2. Locally run scripts/migrate_questions_schema.py --dry-run (prints intended ALTERs)
3. Take a Turso snapshot/backup:
     turso db shell exam-prep-db-pandit ".dump" > backups/pre-schema-fix.sql
   (or use Turso dashboard's point-in-time restore feature)
4. Run scripts/migrate_questions_schema.py (real)
5. Verify:
     - SELECT COUNT(*) matches pre-migration count
     - PRAGMA table_info shows disabled + updated_at
     - SELECT COUNT(*) FROM questions WHERE disabled IS NULL == 0
6. Test admin flow: upload a small PDF, confirm import, check the new
   row has disabled=0 and a non-null updated_at
7. Test user flow: take a mini test, confirm questions still load
```

### Rollback plan

- Turso: point-in-time restore to the snapshot from step 3, OR:
    - `ALTER TABLE questions DROP COLUMN disabled;` (Turso supports this)
    - `ALTER TABLE questions DROP COLUMN updated_at;`
- No app code needs reverting because the columns are optional in queries.

### Risk

**Low** — pure additive schema change with a DEFAULT for `disabled` (existing rows fill to 0). `updated_at` is NULL for old rows, which is fine because all reads treat it as optional.

Only elevated risk: if Turso's Hrana adapter has an obscure behavior on ADD COLUMN mid-flight (unlikely — libSQL is a fork of SQLite). Snapshot before running mitigates this.

---

## Item #3 — Two leaked Turso auth tokens

**Severity:** MEDIUM (both tokens are still live)
**Effort:** 45 minutes (rotation + verification), + 1-2 hours if git history purge is chosen

### Root cause

**Leak #1:** Commit `e8907d4` on `main` — `migrate_to_turso.py:9` had the token hardcoded. File was later removed from the working tree but the commit is still reachable in history via `git log --all -p`.

**Leak #2:** This session's transcript (`~/.claude/projects/-home-pandit-code-personal-exam-prep-platform/*.jsonl`) contains a *different* live JWT that was pasted into chat during the extraction-push step. `iat=1783838836`, `rid=d0f15699-2cb2-4769-bd94-5b0b89a694b3`. Not in git, but sits in the local session store.

Both tokens grant read/write to the `exam-prep-db-pandit` database. Turso JWTs do not have automatic short expiry — they remain valid until revoked via the Turso dashboard or CLI.

### Fix approach

Three sub-steps: rotate → propagate → optionally purge.

**Step 3a — Rotate at source.** Turso dashboard → Databases → `exam-prep-db-pandit` → Tokens → issue new full-access token → revoke both old tokens by ID:

```
turso db tokens revoke <old-token-1-id>  # from leak #1
turso db tokens revoke <old-token-2-id>  # rid d0f15699-2cb2-4769-bd94-5b0b89a694b3
turso db tokens create exam-prep-db-pandit --expiration 90d
```

Prefer a token with a bounded lifetime (90d) going forward — forces you to see it periodically instead of pretending forever.

**Step 3b — Propagate the new token.** Update every place that stores it:

```
- Render dashboard → env vars → TURSO_AUTH_TOKEN = <new>
- Local .env: currently only has GEMINI_API_KEY. Add TURSO_DB_URL and
  TURSO_AUTH_TOKEN so future local scripts don't need env exports.
  .env is gitignored — safe.
- Any dev machine you use — shell exports, tmux env, etc.
```

Trigger a Render redeploy after the env var change. Verify by hitting `/diag/<token>` and confirming the endpoint reports the new token's prefix (bp_diag.py already exposes `probe_env` for the admin password — extend if needed for Turso).

**Step 3c (optional) — Purge git history.** The old token at `e8907d4` is now revoked, so purging is defensive not urgent. If desired:

```
git filter-repo --path migrate_to_turso.py --invert-paths
git push --force origin main
```

**Warnings:**
- Force-push rewrites history. Any collaborators / other checkouts must re-clone.
- GitHub caches PR diffs — the token is still viewable in the PR/commit UI for a while after force-push. Contact GitHub Support to purge if you need it gone from the UI. Since the token is already revoked this is aesthetic.
- Solo user, so no collaborator concern. Only concern is your own other machines.

**Step 3d (bonus — prevent regression).** Add a pre-commit hook that scans staged files for the JWT header pattern:

```bash
# .git/hooks/pre-commit
if git diff --cached | grep -E 'eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.'; then
  echo "possible JWT in staged content"
  exit 1
fi
```

Not bulletproof, but catches the obvious case. `detect-secrets` or `gitleaks` are more thorough if you want tooling.

### Migration sequence

```
1. Turso dashboard: create new token, note the ID
2. Render dashboard: update TURSO_AUTH_TOKEN env var
3. Local .env: add TURSO_DB_URL and TURSO_AUTH_TOKEN
4. Trigger Render redeploy
5. Verify Render logs show successful DB connect
6. Verify /diag/<token> reports OK
7. Turso dashboard: revoke the two old token IDs
8. Verify: run a script with the OLD token — expect 401 Unauthorized
9. Optional: git filter-repo + force-push
10. Update memory files:
    - project_turso_token_rotation.md → mark rotation complete, note new
      token ID, remove the "deferred" language
    - Update MEMORY.md index line to remove "DEFERRED" prefix
```

### Rollback plan

- Rotation itself is not reversible (revoked tokens stay revoked). If the new token has a problem, issue *another* new token and update env vars.
- Git filter-repo is reversible only if you kept the pre-rewrite refs. Before force-pushing: `git branch backup-pre-rewrite HEAD` and keep it locally for 30 days.

### Risk

**Medium during the window between step 2 (Render updated) and step 7 (old revoked).** Old scripts / cached deployments may briefly fail. Do this during a low-usage window. Solo user, so likely doesn't matter.

**Elevated if git filter-repo is done wrong** — can lose commits. Skip step 9 unless you have a specific reason to erase history (e.g. taking the repo public later).

---

## Verification & smoke tests

The core insight from this session: **silent failures cost hours of debugging**. Every Turso-touching code path needs a way to fail loud. Two lightweight tests, both in a new `tests/test_turso_adapter.py`:

### Test 1 — Adapter raises on schema errors

```python
# tests/test_turso_adapter.py
import os, pytest, sqlite3
os.environ["TURSO_DB_URL"]    = os.environ["TURSO_TEST_URL"]
os.environ["TURSO_AUTH_TOKEN"] = os.environ["TURSO_TEST_TOKEN"]
import turso_patch  # noqa

def test_insert_to_nonexistent_column_raises():
    con = sqlite3.connect("test_exam_prep.db")
    # Create ephemeral table
    con.execute("CREATE TABLE IF NOT EXISTS _probe (id INTEGER PRIMARY KEY, a TEXT)")
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO _probe (id, a, bogus_col) VALUES (1, 'x', 'y')")
    con.execute("DROP TABLE _probe")

def test_insert_returns_lastrowid():
    con = sqlite3.connect("test_exam_prep.db")
    con.execute("CREATE TABLE IF NOT EXISTS _probe (id INTEGER PRIMARY KEY, a TEXT)")
    res = con.execute("INSERT INTO _probe (a) VALUES (?)", ("v",))
    assert res.lastrowid is not None and res.lastrowid > 0
    con.execute("DROP TABLE _probe")

def test_missing_table_raises():
    con = sqlite3.connect("test_exam_prep.db")
    with pytest.raises(sqlite3.OperationalError):
        con.execute("SELECT * FROM _definitely_not_a_table")
```

Set `TURSO_TEST_URL` / `TURSO_TEST_TOKEN` to a separate branch/database from prod. Turso supports branching cheaply — use `turso db create exam-prep-test --from-db exam-prep-db-pandit` once, then reuse.

### Test 2 — Bulk-insert smoke against real schema

```python
def test_bulk_insert_persists_rows():
    con = sqlite3.connect("test_exam_prep.db")
    before = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    for i in range(5):
        res = con.execute(
            "INSERT INTO questions (topic_id, question_text, option_a, option_b, "
            "option_c, option_d, correct_option, explanation, difficulty, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (25, f"smoke {i}", "a", "b", "c", "d", "A", "", "medium", "smoke_test")
        )
        assert res.lastrowid is not None
    after = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    assert after == before + 5
    # cleanup
    con.execute("DELETE FROM questions WHERE source = 'smoke_test'")
```

This test catches Item #1 regressions AND Item #2 regressions (missing columns would raise now).

### CI hook

Add to `render.yaml` predeploy or a GitHub Action:

```
python3 -m pytest tests/test_turso_adapter.py -x -v
```

Only run against the test Turso branch, never prod. If the tests fail, block the deploy.

### Runtime guard (belt-and-braces)

In every write path — admin uploads, seed scripts, one-shot migrations — assert `res.lastrowid is not None` after each `INSERT` and raise with the SQL + params if not. Even after Item #1 is fixed, this is a cheap sanity check that would have caught the extraction-push failure in seconds.

---

## Execution checklist

Do these in strict order. Do not batch.

### Phase A — Fix the silent-failure blocker

- [ ] Read this document top-to-bottom
- [ ] `git checkout -b tech-debt/turso-error-surfacing`
- [ ] Edit `turso_patch.py:_post` to raise on `results[i]["type"] == "error"`
- [ ] Edit `turso_patch.py:TC.__init__` to drop the dead-code error branch
- [ ] Add logging inside `db.py:_run_alter_migrations` except block
- [ ] Add logging inside `db.py:_seed_default_prompt` except block
- [ ] Write `tests/test_turso_adapter.py` per Verification section
- [ ] Create Turso test branch: `turso db create exam-prep-test --from-db exam-prep-db-pandit`
- [ ] Set TURSO_TEST_URL / TURSO_TEST_TOKEN locally
- [ ] Run `pytest tests/test_turso_adapter.py -v` — all pass
- [ ] Commit + push branch
- [ ] Deploy to Render (or promote from a Render preview if configured)
- [ ] Watch Render logs on next boot — `_run_alter_migrations` now logs any ALTER errors
- [ ] Verify existing user flows still work (take a test, view analytics)

### Phase B — Fix the schema

- [ ] Snapshot Turso: `turso db shell exam-prep-db-pandit ".dump" > backups/pre-schema-fix-$(date +%Y%m%d).sql`
- [ ] Write `scripts/migrate_questions_schema.py`
- [ ] Run `--dry-run`, review output
- [ ] Run for real
- [ ] PRAGMA table_info shows disabled + updated_at
- [ ] SELECT COUNT(*) unchanged pre vs post
- [ ] Take a small admin test-upload — new row has disabled=0
- [ ] User take-test still works

### Phase C — Rotate secrets

- [ ] Turso dashboard: create new token `exam-prep-pandit-v3` with 90d expiry
- [ ] Render env: update TURSO_AUTH_TOKEN
- [ ] Local .env: add TURSO_DB_URL + TURSO_AUTH_TOKEN
- [ ] Render redeploy triggered and healthy
- [ ] `/diag/<token>` shows OK
- [ ] Turso dashboard: revoke old token from git leak (leak #1)
- [ ] Turso dashboard: revoke token with rid `d0f15699-2cb2-4769-bd94-5b0b89a694b3` (leak #2)
- [ ] Attempt to use the revoked token from a script — 401 Unauthorized confirmed
- [ ] Update memory: `project_turso_token_rotation.md` — mark rotated, delete DEFERRED prefix in MEMORY.md index
- [ ] (Optional) `git filter-repo --path migrate_to_turso.py --invert-paths`
- [ ] (Optional) Force-push
- [ ] (Optional) Add pre-commit JWT scanner

### Phase D — Bonus hardening

- [ ] Add `res.lastrowid is not None` guard to `bp_admin.py:upload_import` (mirror the pattern from `push_extracted_to_turso.py:112-114`)
- [ ] Wire `tests/test_turso_adapter.py` into pre-deploy hook or GitHub Action
- [ ] Audit existing pdf_uploads for divergent num_extracted vs num_imported: `SELECT id, filename, num_extracted, num_imported FROM pdf_uploads WHERE num_extracted != num_imported` — any hits are evidence of past silent losses. Consider re-running those uploads.

---

## Effort summary

| Phase | Effort | Risk | Blocking |
|-------|--------|------|----------|
| A — Silent-failure fix | 2h | Medium | Everything downstream |
| B — Schema migration | 45min | Low | Full admin flow correctness |
| C — Token rotation | 1h + optional 1-2h | Medium (window) | Long-term security posture |
| D — Bonus | 1h | Low | — |
| **Total (mandatory)** | **~4h** | | |

Do all three in one focused session if possible — they build on each other and the verification for #2 depends on #1 being deployed.

---

## Out of scope (noted but not addressed here)

- Rich metadata rescue: the extraction JSONs contained `section`, `sub_topics`, `confidence`, PYQ year, etc. that got flattened into `source` at push time. Restoring that structure is a schema-evolution question, not a tech-debt one — belongs in the content-quality plan (D-content-quality.md).
- Topic distribution imbalance (Algorithms=4, Python=9). Content problem, not tech debt.
- Frontend responsiveness / accessibility. Belongs in the polish plan.
