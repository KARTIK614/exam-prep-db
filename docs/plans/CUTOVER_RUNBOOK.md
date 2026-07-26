# v3 Cutover Runbook

Step-by-step guide for deploying the new Rust + React stack alongside the live
Flask app, verifying parity, and flipping traffic. Sandbox blocks any deploy
tooling in the agent env, so every step below is meant to be run on Kartik's
laptop or in a browser tab.

Companion docs:
- Full plan: [`docs/plans/v3-R5-migration-deploy.md`](v3-R5-migration-deploy.md)
- Retirement plan for the Flask service: [`docs/plans/FLASK_RETIREMENT.md`](FLASK_RETIREMENT.md)

---

## 1. Prerequisites

### Accounts / dashboards

| Service   | URL                                           | What lives there                                    |
|-----------|-----------------------------------------------|------------------------------------------------------|
| Render    | https://dashboard.render.com                  | Flask service (current prod) + Rust service (new)   |
| Vercel    | https://vercel.com/dashboard                  | React frontend                                       |
| Turso     | https://app.turso.tech                        | libSQL DB — shared by all three envs                |
| GitHub    | https://github.com/KARTIK614/exam-prep-db     | source of truth; both platforms auto-pull from `main` |

### Local tooling

```bash
# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
rustup toolchain install stable

# Node + pnpm
curl -fsSL https://get.pnpm.io/install.sh | sh -
pnpm env use --global 20

# Optional: Docker for local Dockerfile smoke test
# Optional: Vercel CLI for local preview builds
```

### Local compile check (do this before the first deploy)

```bash
cd backend && cargo check --locked && cargo test --locked
cd ../frontend && pnpm install && pnpm exec tsc --noEmit && pnpm build
```

If either step fails, fix locally and push. Do not deploy a red build.

**Known compile-blocker candidates flagged during Phases 1–9 (verify before deploy):**
- `libsql::params!` with `Option<T>` values in `api/admin/synthesize.rs` (Phase 7)
- `tower_governor` API drift on the pinned version in `api/mod.rs` (Phase 3)
- `Path<(i64, String)>` two-tuple destructuring in `api/admin/flags.rs` (Phase 7)

If the workspace touches Chart.js or another peer dep from the shadcn boilerplate that isn't listed in `package.json`, pnpm will surface it here.

---

## 2. Environment variables

| Var                        | Service     | Source                          | Rotation                          |
|----------------------------|-------------|---------------------------------|-----------------------------------|
| `TURSO_DB_URL`             | Render/back | render.yaml (value shown)       | never — but see Retirement doc    |
| `TURSO_AUTH_TOKEN`         | Render/back | Turso dashboard → DB → Auth      | on secret rotation (see below)    |
| `JWT_SECRET`               | Render/back | `openssl rand -base64 48`       | rotate → nukes active sessions    |
| `JWT_REFRESH_SECRET`       | Render/back | `openssl rand -base64 48`       | rotate → nukes refresh tokens     |
| `GEMINI_API_KEY`           | Render/back | Google AI Studio                | on quota upgrade                  |
| `DEEPSEEK_PRIMARY_KEY`     | Render/back | https://platform.deepseek.com   | on quota exhaustion               |
| `DEEPSEEK_SECONDARY_KEY`   | Render/back | same, second account            | fallback pool                     |
| `GLM_API_KEY`              | Render/back | https://open.bigmodel.cn        | tertiary fallback                 |
| `LOG_LEVEL`                | Render/back | literal `info`                  | `debug` for triage                |
| `CORS_ORIGIN`              | Render/back | Vercel prod URL                 | after custom domain flip          |
| `PORT`                     | Render/back | literal `3000`                  | never                             |
| `VITE_API_URL`             | Vercel      | Render backend URL              | after custom domain flip          |
| `VITE_SENTRY_DSN`          | Vercel      | Sentry project (public key)     | optional                          |

**All secrets in `render.yaml` use `sync: false`** — Render will not populate them from IaC; you must add them manually in the dashboard before the first deploy.

**Related memory:** `~/.claude/projects/.../memory/project_secrets_rotation.md` tracks known-leaked keys that MUST be rotated before opening the repo (or transcripts) publicly.

---

## 3. Backend deploy — Rust to Render

1. Push `main` — the `render.yaml` in the repo now declares both services.
2. Render dashboard → **New +** → **Blueprint** → pick this repo → deploy.
   Render reads `render.yaml`, spawns `exam-prep-backend` as a Docker service
   alongside the existing Flask service.
3. Before the first build finishes, populate all `sync: false` env vars in
   the dashboard. Miss any → `main.rs::Config::from_env` panics loudly.
4. Wait for `/health` to return `200`. First cold build ≈ 8–12 min. If it
   hangs, tail the build log — most first-time failures are cargo dep
   compile errors (see §1).
5. Smoke test:
   ```bash
   BACKEND=https://exam-prep-backend.onrender.com
   curl "$BACKEND/health"                       # → 200 {"status":"ok","turso":"ok"}
   TOK=$(curl -sX POST "$BACKEND/api/v1/auth/login" \
     -H content-type:application/json \
     -d '{"username_or_email":"kartik","password":"<pw>"}' | jq -r .access_token)
   curl -H "authorization: bearer $TOK" "$BACKEND/api/v1/me"
   ```
6. Rate-limit sanity: hit `/api/v1/auth/login` six times in a minute with
   the same IP → sixth should return `429`. If it doesn't, `tower_governor`
   isn't wired (Phase 3 open item — noted in report).

---

## 4. Frontend deploy — React to Vercel

1. Vercel dashboard → **Add New… → Project** → import GitHub repo.
2. **Root Directory**: `frontend`
3. **Framework Preset**: Vite (auto-detected)
4. Environment Variables:
   - `VITE_API_URL` = leave empty for now (rewrites in `vercel.json` proxy
     `/api/*` to Render). Set explicitly only if the frontend runs on a
     different origin than the backend and you don't want the proxy.
   - `VITE_SENTRY_DSN` = optional
5. Deploy. Vercel builds in ≈ 90 s.
6. Copy the assigned prod URL (e.g. `exam-prep-xxxx.vercel.app`) and set
   `CORS_ORIGIN` on the Render backend to it. Then push a no-op commit to
   trigger a backend redeploy so the CORS layer picks up the new value.
7. Smoke test in a browser:
   - Open `https://<vercel-url>/` → landing page renders.
   - `/signup` → create test user.
   - `/dashboard` → renders (empty state for a new user).
   - `/test/new` → preset picker shows the 7 bundles.
   - Start a 10-Q warmup → palette + shortcuts work → finish → results.

---

## 5. DNS / custom domain (optional)

Only needed if you want `exam.example.com` instead of `*.vercel.app`.

- **Frontend**: Vercel → Project → Domains → add `exam.example.com`.
  Add the CNAME they show at your registrar.
- **Backend**: Render → Service → Settings → Custom Domain → add
  `api.exam.example.com`. Add CNAME. Wait for TLS provisioning.
- Update on Vercel: `vercel.json` `rewrites[0].destination` →
  `https://api.exam.example.com/api/:path*`. Redeploy.
- Update on Render: `CORS_ORIGIN` → `https://exam.example.com`. Redeploy.
- CSP header in `vercel.json` includes `connect-src` with the current
  Render URL — update that to `api.exam.example.com` when the domain lands.

---

## 6. Cutover checklist

Do all of these against the new Vercel URL **before** flipping DNS off Flask.
Tick as you go.

- [ ] `/` (landing) renders unauth; CTA to `/signup` works
- [ ] `/signup` creates a new user → auto-login → `/dashboard`
- [ ] `/login` with existing user → `/dashboard`
- [ ] `/forgot-password` submits (email will log-only until Resend integration)
- [ ] `/dashboard` shows consistency card, mastery grid (18 tiles), next-weak-topic
- [ ] `/test/new` — preset picker card shows 7 bundles
- [ ] Preset click auto-fills form; custom form still expandable
- [ ] Start a 10-Q warmup → palette renders → keyboard A/B/C/D advances
- [ ] `?` opens help modal; `F` opens flag modal; `M` toggles mark-for-review
- [ ] Refresh mid-test → answers persist (resume-after-refresh)
- [ ] `/test/:id/finish` computes score; results page renders
- [ ] Neg-marking breakdown visible on exam-mode results
- [ ] Print preview looks clean (Ctrl-P on results)
- [ ] `/analytics` — mastery grid + heatmap + pacing chart render
- [ ] `/review` — SR queue loads; Missed / Got-it work
- [ ] `/bookmarks` — star a question from test flow, appears here
- [ ] `/search` (or Cmd-K) — full-text hits with snippet
- [ ] `/admin/*` — admin-only user only; regular user gets 403
- [ ] Dark mode toggle persists across refresh
- [ ] iPhone SE (375px) — landing, dashboard, take-test all usable
- [ ] `/health` returns 200 from the Rust service

Any failure = fix before cutover; do NOT proceed to §7.

---

## 7. Rollback plan

If a hard blocker surfaces post-cutover:

1. **Fastest revert (frontend)**: Vercel dashboard → Deployments → pick
   the last-known-good deployment → Promote to Production. Instant.
2. **Backend revert**: Render → Deploys → Rollback to previous. ≈ 60 s.
3. **DNS revert** (only if you flipped custom domains): change the CNAME
   back to the Flask service. Propagation ≈ 60 s if TTL is low; up to an
   hour if you didn't lower TTL beforehand.
4. **DB rollback**: not needed. All v3 schema changes are additive
   (`ALTER TABLE ADD COLUMN`, new tables, new indexes). Flask still reads
   the same DB and ignores columns it doesn't know about.

Coexistence is safe indefinitely — Flask and Rust can both hit the same
Turso instance. Retire Flask only after 14 days of clean Rust logs (see
`FLASK_RETIREMENT.md`).

---

## 8. Cost sanity check

| Line item          | Provider  | Plan       | Monthly |
|--------------------|-----------|------------|---------|
| Flask (retiring)   | Render    | Starter    | $7      |
| Rust backend       | Render    | Starter    | $7      |
| React frontend     | Vercel    | Hobby      | $0      |
| Turso DB           | Turso     | Free       | $0      |
| Domain (optional)  | Registrar | .com       | ~$1     |
| Email (Resend)     | Resend    | Free       | $0      |

- **Coexistence peak**: $15/mo (2× Render services)
- **Steady state after Flask retirement**: $8/mo
- **Annualised**: ~$96/yr

If backend Docker cold-starts feel slow on Starter, upgrade to Standard
($25/mo) — the biggest visible perf win is avoiding cold-start on the
free-tier idle timeout. Not worth it for <10 daily users.

---

## 9. Deploy gotchas noticed

1. **Render Docker + Turso libsql TLS**: libsql calls Turso over HTTPS.
   The distroless `cc-debian12` image ships CA certs by default, but if
   you switch to a bare `scratch` runtime you'll get opaque TLS handshake
   failures — keep distroless.
2. **Render + IPv6**: Render's Docker runners default to IPv6 for
   outbound; some libsql endpoints only advertise IPv4. If you see
   sporadic 502s from Turso, force IPv4 by exporting
   `RUST_LIBSQL_PREFER_IPV4=1` (custom, wire in `main.rs` if needed).
   Not observed today but flag it.
3. **Vercel + Vite + SPA fallback**: without the second rewrite in
   `vercel.json` (`/((?!api/|assets/|favicon).*)` → `/index.html`),
   deep-linking to `/dashboard` gives 404 on hard refresh. Rewrite is
   already in place — do not remove it.
4. **`vercel.json` rewrites vs CORS**: because we rewrite `/api/*` to
   the Render backend, same-origin cookies work. If you later split
   frontend + backend onto different apex domains, you'll need to switch
   to bearer-token-only auth (already the case here) and set the CORS
   origin explicitly.
5. **`tower_governor` behind Render's proxy**: Render terminates TLS and
   forwards `X-Forwarded-For`. The default `PeerIpKeyExtractor` will
   rate-limit by Render's proxy IP (i.e., globally) instead of client IP.
   Swap to `SmartIpKeyExtractor` before public launch — one-line change
   in `backend/src/api/mod.rs` `ip_rl!`.
6. **Turso free-tier row limit**: 500M rows across all DBs on free plan.
   We're at ~4k rows — safe for years. Storage limit is 8 GB per DB.
7. **GitHub Actions deploy hook**: both workflows use
   `secrets.RENDER_DEPLOY_HOOK_BACKEND` and
   `secrets.VERCEL_DEPLOY_HOOK_FRONTEND`. Add these under GitHub repo
   settings → Secrets and variables → Actions. Without them, CI still
   runs but does not trigger deploys.

---

## 10. Post-cutover follow-ups

Track in the task queue, not this doc:

- Wire Resend (or SMTP) for the password-reset email — Phase 3 currently
  logs the reset URL to stdout.
- Port `bp_admin.upload_import` (PDF → Claude vision extraction) to Rust
  — Phase 7 stubbed the endpoint.
- Rotate the ~6 known-leaked secrets tracked in
  `memory/project_secrets_rotation.md`.
- Add Sentry to both services once the free-tier signup is done.
- Run Phase 11 critic + fix pass — before opening signup to real users.

_Written 2026-07-26 as part of v3 Phase 10._
