# Flask (v2) Retirement Plan

The Rust + React stack goes live per [`CUTOVER_RUNBOOK.md`](CUTOVER_RUNBOOK.md).
The Flask service stays deployed on Render as a rollback safety net for
**14 days**, then gets deleted. This doc captures the timeline + the pre-delete
checklist so nothing gets orphaned.

---

## Timeline

| Day | Action |
|-----|--------|
| **T+0** | Rust + React live. Flask still deployed but no traffic (DNS points to Vercel). |
| **T+1** | Sanity check: Flask logs quiet (only occasional health pings, no real users). |
| **T+7** | Mid-window review. If Rust has surfaced any bugs, keep Flask up longer. |
| **T+14** | Retirement day (see checklist below). |

**Reset the timeline** if any of these happens in the window:
- A P1 bug surfaces on the Rust stack and you have to failover to Flask.
- Data-model incompatibility appears (shouldn't — all schema changes are additive).
- Real user complains about parity.

---

## Pre-delete checklist

Tick each before deleting the Flask service.

- [ ] Rust `/health` has been 200 for ≥14 consecutive days
- [ ] No P1/P2 bugs in the last 7 days
- [ ] All `sync: false` env vars on Rust service are populated
- [ ] Sujit (or another real user) has completed at least one mock test end-to-end on the new stack
- [ ] `docs/plans/CUTOVER_RUNBOOK.md` §6 checklist has been re-run against production URLs
- [ ] Flask logs reviewed for the last 24 h; only automated pings / crawlers
- [ ] DNS has fully propagated (dig from three networks agrees)
- [ ] Custom-domain TLS certs (if applicable) are valid on the new stack for ≥30 more days
- [ ] `git tag v2-final` created at the last Flask commit, and pushed. Recovery path if the delete is ever regretted:
  ```bash
  git checkout v2-final
  # then re-add the Flask service in Render dashboard
  ```

---

## Delete steps

1. **Snapshot Turso**
   Even though the schema is shared, snapshot before major infra changes:
   ```bash
   turso db shell exam-prep-db-pandit ".dump" > pre-retirement-$(date +%Y-%m-%d).sql
   ```
   Store the file locally + in one off-machine location.

2. **Deregister Flask blueprint from `render.yaml`**
   Remove the `- type: web` block for `exam-prep-platform` (the Flask one).
   Leave the Rust `exam-prep-backend` block. Commit + push.

3. **Delete the Render service**
   Dashboard → `exam-prep-platform` → **Settings** → scroll to bottom → **Delete Service**. Requires typing the service name.

4. **Revoke Flask-only secrets**
   The Rust backend does not use these, so they can go:
   - `FLASK_SECRET_KEY`
   - `EXAM_ADMIN_USER` (auth via Rust `/api/v1/auth/*` now)
   - `EXAM_ADMIN_PASS`
   - `COOKIE_SECURE` (Rust handles cookies via its own middleware if any)

   Also remove any deprecated `TURSO_AUTH_TOKEN` if you rotated as part of the [`project_secrets_rotation`](../../.claude/projects/-home-pandit-code-personal-exam-prep-platform/memory/project_secrets_rotation.md) work.

5. **Purge dead code from `main`** (optional; do only if you're sure)
   ```bash
   git rm -r bp_*.py auth.py db.py seed.py turso_patch.py \
     wsgi.py app.py config.py requirements.txt \
     templates/ static/ tests/test_flags.py tests/test_routes.py \
     tests/test_boot_with_turso.py tests/test_sr.py tests/test_turso*.py \
     ai_anthropic.py ai_config.py ai_utils.py content_metadata.py sr.py \
     data/exam_prep.db data/flask_session/
   ```
   Keep `docs/`, `scripts/migrate_*.py`, and the git history. Commit as a
   single "retire Flask" commit.

6. **Update README**
   Point the README at the Rust + React stack. Remove references to Flask,
   `wsgi.py`, `gunicorn`, etc.

7. **Announce**
   If Sujit or any other user is on the platform, message them once the DNS
   flip is done. Include the new signup URL.

---

## What NOT to delete

- **Turso DB** — the Rust backend still uses it. Same DB, additive schema.
- **`data/mcq_pdfs/`** — source PDFs for future admin uploads. Keep gitignored.
- **`data/extracted_questions/*.json`** — provenance for the 3,712 rows. Keep.
- **`docs/plans/*`** — planning history. Keep in-repo indefinitely.
- **Memory files** — under `~/.claude/projects/…/memory/`. Keep.

---

## Emergency: I deleted Flask and immediately need it back

You have three routes:

1. **Vercel / Render rollback UI** — if the Rust build was pushed after the Flask delete, you can revert the commit that removed the Flask block from `render.yaml`, push, and Render will re-provision.
2. **Redeploy from `v2-final` tag** — see the pre-delete checklist step for `git tag v2-final`. Checkout the tag, push a branch, add the service back in Render dashboard pointing at that branch.
3. **Turso is unaffected** — data survives regardless. Even a full replay from `git tag v2-final` will bring you back to a working Flask app pointing at the current DB with all users, questions, etc.

_Written 2026-07-26. Part of v3 Phase 10._
