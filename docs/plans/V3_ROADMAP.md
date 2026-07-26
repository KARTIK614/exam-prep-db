# v3 Replatform — Master Roadmap

Index + sequencing + locked decisions for the five research plans written
2026-07-19. Each plan below is standalone and fully self-contained; this
file is the map, and the doc you read every morning to decide what to
build next.

**Target end-state:** Flask+Jinja retired. Rust axum backend at
`api.exam.<dom>.dev`, React/TS SPA at `exam.<dom>.dev`, Turso unchanged.
Multi-user schema live. Kartik is user 1 (auto-admin); signup open.

---

## 1. Index of the five plans

| # | Plan | File | Lines | One-line summary |
|---|---|---|---|---|
| R1 | Rust backend framework + MVC layout | [`v3-R1-rust-backend.md`](v3-R1-rust-backend.md) | 796 | axum 0.8 + tokio + thiserror + figment + tracing; MVC file tree; feature-parity route table; Cargo pins. |
| R2 | Turso libSQL client + multi-user schema migration | [`v3-R2-turso-schema.md`](v3-R2-turso-schema.md) | 802 | Official `libsql` crate + raw SQL repository pattern; add `user_id` to 7 tables; refinery migrations; embedded replica for reads. |
| R3 | React + TypeScript frontend stack | [`v3-R3-react-frontend.md`](v3-R3-react-frontend.md) | 1071 | Vite + RR6 + TanStack Query + Zustand + Tailwind + shadcn/ui; 25-page inventory; a11y contracts for palette/heatmap. |
| R4 | REST API contract + auth flow | [`v3-R4-api-auth.md`](v3-R4-api-auth.md) | 1852 | `/api/v1/*` REST, `utoipa` OpenAPI, JWT access (15m) + rotating opaque refresh (30d) cookie, argon2id, cursor pagination, tower-governor rate limits. |
| R5 | Migration strategy + deployment / infra | [`v3-R5-migration-deploy.md`](v3-R5-migration-deploy.md) | 1025 | Frontend-first strangler-fig (Option C); Rust on Render Docker, SPA on Vercel; ~$8/mo steady state; per-blueprint cutover checklist. |

**Total research pages:** 5 docs, 5,546 lines.

---

## 2. Cross-plan dependencies

```
                    ┌───────────────────────────────┐
                    │   R1 Rust backend skeleton    │
                    │  (axum, config, error, state) │
                    └───────────────┬───────────────┘
                                    │
                                    │  crate layout, AppState,
                                    │  error envelope defined
                                    ▼
                    ┌───────────────────────────────┐
                    │  R2 Turso schema + libsql     │
                    │   ALTERs, user_id backfill,   │
                    │   refinery migrations         │
                    └───────────────┬───────────────┘
                                    │
                                    │  Rust models + repositories
                                    │  compile against real schema
                                    ▼
                    ┌───────────────────────────────┐
                    │  R4 REST contract + auth      │
                    │  OpenAPI spec generated       │
                    │  from utoipa annotations      │
                    └───────┬───────────────┬───────┘
                            │               │
                            │               │  openapi.json artifact
                            │               │
                            ▼               ▼
              ┌─────────────────┐   ┌─────────────────────┐
              │ R3 React SPA    │   │ R5 Deploy / cutover │
              │ (types from R4  │   │ (Dockerfile, DNS,   │
              │  spec; Zod;     │   │  Vercel, Render,    │
              │  Zustand; RR6)  │   │  strangler routing) │
              └────────┬────────┘   └──────────┬──────────┘
                       │                       │
                       └───────────┬───────────┘
                                   ▼
                    ┌───────────────────────────────┐
                    │ CUTOVER — Flask retired       │
                    │ Post-launch critic pass       │
                    └───────────────────────────────┘
```

**Hard blocks:**
- **R1 blocks R2** — crate layout + `AppState`/`Db` types must exist before
  we can write the Rust migration runner or repository modules.
- **R2 blocks R4** — auth endpoints depend on `refresh_tokens`,
  `password_resets` tables; user-scoped queries need `user_id` columns.
- **R4 blocks R3 codegen** — `openapi.json` is R3's TypeScript source of
  truth; no spec = handwritten Zod schemas + drift risk.
- **R3 + R4 both block R5 cutover** — nothing to point DNS at until both
  services stand up.

**Soft blocks:**
- R5's session-cookie unification (Flask JWT-in-cookie) technically
  precedes R4 in strangler order, but only because Flask stays alive
  during coexistence. If we choose big-bang cutover it disappears.
- R2's embedded-replica optimization is deferred until p95 > 300 ms;
  don't block on it.

---

## 3. Total effort estimate + calendar

Summed from each plan (the numbers each plan states, not this file's
reinterpretation).

| Plan | Build effort |
|---|---|
| R1 Rust backend architecture + skeleton + parity endpoints | ~120 h |
| R2 libSQL client wire-up + schema migrations + backfill | ~15 h |
| R3 React SPA (F0-F5 milestones) | ~44 h nominal / ~85 h realistic |
| R4 Auth + API contract implementation (folded into R1 per-blueprint) | ~25 h |
| R5 Deploy infra + cutover + email + observability | ~24 h |
| Critic/vuln pass on shipped v3 (Phase 11) | ~8 h |
| **Total nominal** | **~236 h** |
| **Total realistic (with context-switch overhead)** | **~275 h** |

**Calendar for a solo dev at 2-3 hrs/night, 5 nights/week (~12-15 h/wk):**

- Nominal 236 h ÷ 13 h/wk ≈ **18 weeks (~4.5 months)**
- Realistic 275 h ÷ 13 h/wk ≈ **21 weeks (~5-6 months)**
- R5's own estimate: **17-24 weeks / 4-6 months** — matches.

Landmarks assuming a start date of 2026-07-20:

| Milestone | Elapsed weeks | Wall-clock date |
|---|---|---|
| Phase 1 complete (Rust skeleton on Render) | 2 | 2026-08-03 |
| Phase 2 complete (schema migrated, models compile) | 3 | 2026-08-10 |
| Phase 3 complete (auth API live) | 5 | 2026-08-24 |
| Phase 5 complete (test-taking API live) | 9 | 2026-09-21 |
| Phase 8 complete (React scaffold + auth pages) | 12 | 2026-10-12 |
| Phase 10 complete (cutover done, Flask retired) | 19 | 2026-11-30 |
| Phase 11 complete (critic/vuln pass) | 21 | 2026-12-14 |

Buffer weeks (holidays, day-job crunch): assume 2-3 more, target
**live in ~January 2027**.

---

## 4. Locked design decisions

Every "recommended" from the five research files, consolidated. Format:
category → decision → source doc §. If two plans disagree, the conflict
is flagged with a resolution.

### 4.1 Backend runtime

| Concern | Decision | Source |
|---|---|---|
| Language | Rust (2024 edition) | R1 §0 |
| MSRV | 1.83 | R1 §12 |
| Web framework | **axum 0.8** (rejected: actix-web, rocket, poem, warp, salvo) | R1 §1 |
| Async runtime | **tokio 1.40+**, `rt-multi-thread` (no thread pinning) | R1 §2.1 |
| HTTP client (outbound) | **reqwest 0.12** with `rustls-tls` (no OpenSSL) | R1 §11 |
| Middleware stack | tower + tower-http (`trace`, `cors`, `compression-gzip`, `catch-panic`, `request-id`) + tower_governor | R1 §11, R4 §6 |
| Panic policy | `CatchPanicLayer` → 500 with request_id; do not fatal the server | R1 §4.5 |
| Config | **figment** + typed `Settings` struct, layered default → toml → env → CLI; `.env` in dev via dotenvy | R1 §5 |
| Secrets wrapper | **`secrecy::SecretString`** — every API key, JWT secret, DB token | R1 §5.3 |
| Errors | **`thiserror` in libraries, `anyhow` in main.rs only**; single `AppError` enum with `IntoResponse` | R1 §4 |
| Composition root | `AppState { db, config, http, llm, jwt_keys }`, all `Arc`-cheap-clone | R1 §3.3 |
| CPU-bound work | `tokio::task::spawn_blocking` for PDF extract, dedupe trigrams | R1 §2.2 |
| MVC layout | `src/{api,services,models,db,schemas,middleware,config,error,state,telemetry}.rs` | R1 §3 |
| LLM clients | Behind `trait LlmClient` in `services/llm/`; mock impl for tests | R1 §3.2 |

### 4.2 Database

| Concern | Decision | Source |
|---|---|---|
| DB | **Turso libSQL** (unchanged from v2) | R2 §0, R5 §4.2 |
| Rust client | **`libsql` official crate 0.6+** (rejected: libsql-client-rs, raw HTTP) | R2 §1 |
| Query builder | **None — raw SQL + repository pattern**; SQLx/Diesel/sea-query rejected (SQLx driver mismatch, FTS5 not modeled) | R2 §2 |
| Connection pool | Single `Arc<libsql::Connection>` + `tokio::sync::Semaphore(32)` fanout cap; no bb8 | R2 §1.4 |
| Migration tool | **`refinery`** + a hand-rolled ~40-line libsql adapter; `V001..VNNN__name.sql` files | R2 §7 |
| Read acceleration | **Deferred**: embedded replica via `new_remote_replica` only when p95 > 300 ms | R2 §8.2 |
| Multi-user pattern | `UserDb` wrapper for user-scoped repos; `AdminDb` for cross-user queries; CI grep-lint enforces `WHERE user_id` | R2 §4 |
| `user_id` type | `i64` on Rust side, nullable in schema during coexistence (do NOT add `NOT NULL` until Flask is off) | R2 §12 |
| `topic_mastery` migration | **CTAS rebuild** to drop old `UNIQUE(topic_id)` and add `UNIQUE(user_id, topic_id)` | R2 §3.3 |
| `bookmarks` migration | Drop `UNIQUE(question_id)`, add `UNIQUE(user_id, question_id)` | R2 §3.3 |
| `test_responses.user_id` | **Denormalize** (add even though derivable via `test_id`); saves join on hot analytics paths | R2 §3.6 |
| FTS5 | Unchanged; already works over Hrana | R2 §6 |

### 4.3 Auth

| Concern | Decision | Source |
|---|---|---|
| Model | **Access + refresh split** (rejected: single long-lived JWT) | R4 §2.1 |
| Access token | JWT HS256, **15 min TTL**, `Authorization: Bearer` header, in-memory only on SPA | R4 §2.1 |
| Refresh token | **Opaque 256-bit random**, 30-day sliding, httpOnly Secure SameSite=Lax cookie, `Path=/api/v1/auth`, SHA-256 stored server-side, rotated on every use | R4 §2.1, §7.3 |
| Reuse detection | Refresh chain revocation on second-use of a rotated token | R4 §2.4 |
| Password hashing | **argon2id** (`m=19456, t=2, p=1`); supports both `$argon2id$` and legacy `pbkdf2:sha256$` prefixes; upgrade in place on login | R4 §2.5 |
| RBAC | Single `role` claim in JWT (`user`/`admin`); `AuthUser` + `AuthAdmin` extractors; 403 on non-admin | R4 §2.3 |
| Email verification | **Deferred** — `email_verified_at` column reserved; no send on signup | R4 §2.6, R5 §11.2 |
| Password reset | **Ship** — magic-link email, one-shot token, 15-min TTL | R5 §11.2 |
| Signup | **Open, no invite**; first registrant gets auto-admin promotion | R5 §11.2, R4 §11 |
| CSRF | SameSite=Lax + Path-scoped refresh cookie; no double-submit token needed | R4 §7.3 |
| Session state | **Zero** server-side sessions (Flask sessions killed); in-progress test state lives on `mock_tests`+`test_responses` rows | R4 §2.7 |

### 4.4 API contract

| Concern | Decision | Source |
|---|---|---|
| Style | **REST over JSON** (rejected: GraphQL, tRPC) | R4 §1.1 |
| Versioning | **Path-based `/api/v1/*`**, one active version at a time, additive-only within v1 | R4 §1.2 |
| Spec toolchain | **`utoipa`** derive macros → OpenAPI 3.0.3 → `openapi.json` artifact; `utoipa-swagger-ui` at `/api/v1/docs` (admin-gated in prod) | R4 §1.3 |
| Client codegen | **`openapi-typescript`** (types only) + **`openapi-fetch`** thin wrapper (rejected: orval full codegen) | R3 §8.2, R4 §1.3 |
| Content type | `application/json; charset=utf-8`; timestamps RFC3339 UTC; ids `i64`; enums snake_case | R4 §1.4 |
| Error envelope | `{ error: { code, message, request_id, details? } }` on every non-2xx | R4 §4 |
| Pagination | **Cursor-based**, opaque base64url JSON payload; no `?page=` (rejected offset) | R4 §5 |
| Rate limiting | **tower-governor**, in-memory dashmap backend; per-class limits (auth-write 5/min, deep-dive 20/hr, general write 120/min, general read 300/min, admin 600/min) | R4 §6 |
| CORS | Env-driven origin allowlist, `allow_credentials: true`, no wildcard, 600 s preflight cache | R4 §7 |
| Request ID | ULID via `tower-http::request_id::SetRequestIdLayer`; echoed in every response + log | R4 §8.1 |
| Logging | **`tracing` + `tracing-subscriber`** JSON in prod, pretty in dev; skiplist for `password`, `token`, `secret`, `api_key`, `authorization` | R1 §7, R4 §8 |
| Metrics | Deferred to post-launch; `axum-prometheus` if/when needed | R4 §8.4, R1 §7.5 |

### 4.5 Frontend

| Concern | Decision | Source |
|---|---|---|
| Build tool | **Vite 5** (rejected: Next.js, Remix, CRA) | R3 §1 |
| Router | **React Router v6 (data APIs)** (rejected: TanStack Router — churn) | R3 §2 |
| Server state | **TanStack Query v5** | R3 §3.2 |
| Client state | **Zustand** (rejected: Redux Toolkit, Jotai) | R3 §3.3 |
| Styling | **Tailwind CSS 3** + CSS variables (`data-theme` dark mode, matches v2 tokens 1:1) | R3 §4 |
| Component library | **shadcn/ui** (Radix + Tailwind, copy-paste, owned) + Radix directly for gaps | R3 §6 |
| Forms | **react-hook-form + Zod** (rejected: Formik) | R3 §5 |
| Charts | **recharts** (route-split ~90 KB), replaces v2 Chart.js | R3 §6.3 |
| Math rendering | **KaTeX via `react-markdown` + `remark-math` + `rehype-katex`** pipeline | R3 §6.4 |
| Testing (unit) | **Vitest + React Testing Library + jest-axe** | R3 §12 |
| Testing (E2E) | **Playwright** (rejected: Cypress) | R3 §12.4 |
| Auth on client | **httpOnly cookie for refresh; access token in memory only** (rejected: localStorage) | R3 §7.2, R4 §2.1 |
| Package manager | pnpm (`pnpm-lock.yaml` in CI) | R5 §8.2 |
| Bundle target | 180 KB gzipped initial route (dashboard); recharts + KaTeX in separate chunks | R3 §0, §14 |

### 4.6 Deployment + infra

| Concern | Decision | Source |
|---|---|---|
| Migration shape | **Frontend-first strangler-fig (Option C)** — SPA seam via `ROUTES` map, per-blueprint cutover (rejected: big-bang) | R5 §1 |
| Rust host | **Render Web (Docker), Starter $7/mo, Singapore region** (Turso is ap-south-1) | R5 §4.2, §19 |
| SPA host | **Vercel Hobby (free)** — preview per PR, SPA rewrite, edge CDN | R5 §4.2 |
| DNS | **Cloudflare** — `exam.<dom>.dev` (SPA), `api.exam.<dom>.dev` (Rust), `api-legacy.exam.<dom>.dev` (Flask during coexistence) | R5 §4.3 |
| Registrar | Cloudflare Registrar, `.dev` TLD (~$10/yr) | R5 §4.2, §19 |
| Container image | Multi-stage Dockerfile with `cargo-chef`, `debian:bookworm-slim` runtime, `nonroot` user, `HEALTHCHECK` on `/healthz` | R5 §5, R1 §8.2 |
| Email | **Resend** (3k/mo free, thin reqwest wrapper) | R5 §11.1 |
| Error tracking | **Sentry** (5k events/mo free); `sentry-tower` on backend, `@sentry/react` on frontend | R5 §10 |
| Logs | **Better Stack (Logtail)** free 1 GB/mo, 14-day retention; ships from Render | R5 §10 |
| Uptime | **UptimeRobot** free 50 monitors, 5-min interval | R5 §10.3 |
| Backups | `turso db dump` daily, uploaded to **Backblaze B2** (10 GB free); 7 daily + 4 weekly + 3 monthly | R5 §14.3 |
| Coexistence rule | **Additive-only schema changes** until Flask is deleted; no renames/drops, no new NOT NULLs without defaults | R5 §3.1 |
| Rollback | Per-blueprint: flip `ROUTES` map in `frontend/src/api/client.ts`, redeploy Vercel (~30 s) | R5 §14.1 |
| CI | GitHub Actions: `backend.yml` (fmt/clippy/test/audit), `frontend.yml` (typecheck/lint/test/build), `e2e.yml` (Playwright on Vercel deploy_status) | R5 §8 |

### 4.7 Contradictions between plans

Two mild disagreements found; both resolved in favor of the more recent/specific plan.

- **Migration shape.** R1 §13 sketches a "cutover per route with a reverse proxy" (Option B in R5's taxonomy). R5 §1 chooses Option C (frontend-first replace, SPA-side routing). **Resolution: follow R5 (Option C)** — same incremental spirit, no extra Caddy container to babysit. R1's §13 is informational and predates R5.
- **Migration tool.** R2 §7 recommends **`refinery`** with a bespoke libsql adapter. R5 §12 ships a **one-shot Python migration script** (`scripts/migrate_r2.py`) for the initial multi-user backfill. **Resolution: use both** — the Python script runs once during coexistence (Flask still owns writes), then refinery takes over from V001 for every subsequent migration inside the Rust binary. Explicitly documented in Phase 2's exit criteria.
- **Cost of coexistence.** R5 §16 assumes an extra $7/mo for Flask during 4-6 weeks of coexistence. R1 §13 implies Flask disappears earlier. **Resolution: budget $15/mo peak for weeks 6-10, drop to $8/mo after F5.** Matches R5's calendar.

---

## 5. Recommended 11-phase execution order

Matches task-queue slots #49-#59. For each phase: what it delivers, effort
hours (from the source plans), exit criterion (verifiable in a single
command or check), and what it unblocks next.

### Phase 1 — Rust backend skeleton *(task #49)*

- **Delivers:** `backend/` crate compiles and boots on Render. `cargo new`, `Cargo.toml` pinned per R1 §11, `main.rs` + `lib.rs` + `config.rs` + `error.rs` + `state.rs` + `telemetry.rs` + `shutdown.rs`. Empty `api/health.rs` with `GET /healthz` returning `{status:"ok"}`. Multi-stage Dockerfile + `render.yaml` for the new service. Tracing subscriber + request-id middleware wired.
- **Effort:** ~15 h (R1 skeleton subset; not the full 120 h).
- **Exit criterion:** `curl https://api.exam.<dom>.dev/healthz` returns `200 {"status":"ok","version":"3.0.0"}` from Render.
- **Blocks:** Phase 2 (needs `AppState`+`Db` types to hang the migration runner off).

### Phase 2 — Schema migration + Rust models *(task #50)*

- **Delivers:** `user_id` column on `mock_tests`, `test_responses`, `error_log`, `topic_mastery` (via CTAS), `study_sessions`, `bookmarks`, `question_flags`. Backfill all to `user_id=1`. Indexes per R2 §3.3. `refinery_libsql` adapter (~40 lines) + `migrations/V001__baseline.sql` through `V005__backfill_question_flags.sql`. Rust models in `src/models/` compile against the new schema. `UserDb` + `AdminDb` wrappers in `src/db/`.
- **Effort:** ~15 h (R2 total).
- **Exit criterion:** `SELECT COUNT(*), COUNT(user_id) FROM mock_tests` returns matching numbers (33/33), and same for every scoped table; `SELECT COUNT(*) FROM questions` still returns 3712; `topic_mastery` unique-per-user check returns zero duplicates.
- **Blocks:** Phase 3 (auth needs `refresh_tokens` + `password_resets` tables from V001 baseline).

### Phase 3 — Auth API *(task #51)*

- **Delivers:** `POST /api/v1/auth/register`, `/login`, `/refresh`, `/logout`, `/logout-all`, `/forgot-password`, `/reset-password`, `/change-password`; `GET /me`, `PATCH /me`, `GET/PATCH /me/settings`. `AuthUser` + `AuthAdmin` extractors. argon2id password hasher + Werkzeug pbkdf2 legacy support. Rate-limit middleware on auth-write class (5/min per IP). Resend integration for reset emails. First-registrant → auto-admin promotion.
- **Effort:** ~25 h (R4 auth surface).
- **Exit criterion:** end-to-end curl script: register → login → refresh → hit `/me` → logout, all 200s; second-use of a rotated refresh returns 401 `refresh_reused_detected`; argon2id hash present in `users.password_hash` after registration.
- **Blocks:** Phase 4-7 (all downstream user routes need the extractor).

### Phase 4 — Content APIs *(task #52)*

- **Delivers:** `GET /topics`, `GET /questions` (with filters: topic_id, paper, difficulty, pyq_only, pyq_exam, pyq_year), `GET /questions/{id}?expand=...`, `GET /search` (FTS5 + LIKE fallback), cursor pagination on all collections. `services/search.rs`. Read-only; no mutations.
- **Effort:** ~15 h.
- **Exit criterion:** `GET /api/v1/search?q=constitution&limit=20` returns 20 results ranked by bm25 with `backend:"fts5"`; `GET /api/v1/questions?pyq_only=true` returns only rows where `pyq_exam IS NOT NULL`; pagination cursor round-trips correctly.
- **Blocks:** Phase 5 (test creation reads from `/questions`), Phase 9 (Search page).

### Phase 5 — Test-taking APIs *(task #53)*

- **Delivers:** `POST /tests` (create), `GET /tests/{id}` (hydrate palette + responses for resume), `GET /tests` (history list), `PUT /tests/{tid}/answers/{qid}` (idempotent upsert), `DELETE .../answers/{qid}` (clear), `POST /tests/{id}/finish`, `GET /tests/{id}/results`, `DELETE /tests/{id}`. `services/tests.rs` composes `build_test_question_set` + `finalize_test_score`. Scoring math with neg-marking in `models/scoring.rs`.
- **Effort:** ~25 h.
- **Exit criterion:** integration test walks the full flow — create 5-question test → PUT 5 answers → finish → GET results with `avg_time_sec`, `topic_breakdown`, `error_types`, `phases` populated; PUT twice with same body is a no-op (idempotent); question outside the test returns 404.
- **Blocks:** Phase 6 (analytics reads `test_responses`), Phase 9 (Test page).

### Phase 6 — Analytics + SRS APIs *(task #54)*

- **Delivers:** `GET /analytics/overview`, `/mastery`, `/next-topics`, `/heatmap?dim=difficulty|recency`, `/pacing`, `/consistency`, `/error-distribution`, `/paper-performance`. `GET /review/queue`, `POST /review/answers/{error_id}` (Leitner-5 box math). `GET /errors`, `POST /errors/{id}/resolve`, `POST /errors/{id}/redo`. `POST /study-sessions` + `GET /study-sessions`. All queries `WHERE user_id = ?`.
- **Effort:** ~20 h.
- **Exit criterion:** `GET /api/v1/analytics/mastery` returns tiles for all topics with `tier` in {`weak`,`on_track`,`untested`,`mastered`}; `GET /review/queue` returns due cards with `if_ok_box`/`if_no_box` populated; `POST /review/answers/{id} {was_correct:true}` moves the row up one box and pushes `sr_due_at` forward per the Leitner interval table.
- **Blocks:** Phase 9 (Dashboard, Analytics, Review, ErrorLog pages).

### Phase 7 — Bookmarks + flags + Deep Dive + admin APIs *(task #55)*

- **Delivers:** `POST /questions/{id}/bookmark` + `DELETE` + `GET /bookmarks`; `POST /questions/{id}/flag` (7-category whitelist); `POST /questions/{id}/deep-dive` + `POST /questions/{id}/chat` (LLM trait, Gemini primary, Anthropic + DeepSeek + GLM fallbacks, doubt cache unchanged). All 30+ `/admin/*` endpoints: stats, flags, review queue, duplicates, questions CRUD, topics CRUD, users CRUD, pdf-uploads (async), synthesize, prompts. Admin PDF upload switches to fire-and-forget background task.
- **Effort:** ~30 h.
- **Exit criterion:** `POST /api/v1/questions/1/flag {category:"wrong_answer"}` creates a `question_flags` row visible in `GET /api/v1/admin/flags`; `POST /api/v1/questions/1/deep-dive` returns cached response on second call within 24 h; admin upload finishes async — `GET /admin/pdf-uploads/{id}` transitions `processing → extracted` without blocking the POST.
- **Blocks:** Phase 9 (all admin pages), Phase 10 (cutover checklist needs full API surface).

### Phase 8 — React scaffold + auth pages *(task #56)*

- **Delivers:** `frontend/` Vite + TS project. Router (RR6) with public routes only. `useAuth` Zustand store + `RequireAuth` guard. Tailwind config mapping v2 tokens; `data-theme` flash-prevention inline script. shadcn/ui init + `Button`/`Input`/`Dialog`/`Toast`/`Command` primitives. `openapi-fetch` client + generated types from R4's `openapi.json`. Pages: Login, Signup, ForgotPassword, ResetPassword, Profile. Deploy to Vercel Hobby with preview per PR. `vercel.json` with CSP + rewrites.
- **Effort:** ~10 h (R3 milestone F0 + auth pages).
- **Exit criterion:** Vercel preview URL loads `/login`; submitting valid creds sets the refresh cookie + stores user in `useAuth`, redirects to `/dashboard` (empty shell); typing a bad password shows an inline error toast; theme toggle flips light/dark with no flash on reload.
- **Blocks:** Phase 9 (feature pages depend on shell + auth).

### Phase 9 — React feature pages *(task #57)*

- **Delivers:** Dashboard (mastery grid + consistency + SRS due pill + next-weak-topic), TestSetup, TakeTest (palette, timer, keyboard shortcuts, flag dialog, bookmark star — Zustand `useTestSession` store owns state), TestResults, Analytics (recharts: mastery bars, progress line, difficulty pie, pacing, heatmap, error breakdown), ErrorLog, Review (Leitner queue), Bookmarks, Search (Cmd-K palette). All 12 admin pages.
- **Effort:** ~34 h (R3 milestones F1-F4).
- **Exit criterion:** end-to-end manual smoke: log in → dashboard shows correct counts → new test (10 Qs) → answer 10 via keyboard only → finish → results → analytics reflects the new test → logout. iPhone SE (375px) portrait works without horizontal scroll.
- **Blocks:** Phase 10 cutover.

### Phase 10 — Deploy + cutover *(task #58)*

- **Delivers:** DNS in Cloudflare (`exam`, `api.exam`, `api-legacy.exam`). Rust service live on Render Singapore with custom domain + TLS. Vercel prod deploy on `exam.<dom>.dev`. `ROUTES` map in `frontend/src/api/client.ts` populated. Blueprint-by-blueprint cutover per R5 §7 (order: auth → questions/submit → tests → analytics → review/errorlog → search → doubt → admin → diag). Cutover checklist run for each. Flask access logs verified quiet for 7 days. Flask Render service turned off (branch kept for 30 days). Sentry + Better Stack + UptimeRobot monitors green. Turso backups running to B2.
- **Effort:** ~24 h (R5 total).
- **Exit criterion:** for 7 consecutive days, Flask access logs show zero SPA-origin requests; UptimeRobot p50 < 500 ms on `exam.<dom>.dev`; monthly cost report shows Render Flask $0; the 10-item post-cutover checklist in R5 §13 all ticked.
- **Blocks:** Phase 11.

### Phase 11 — Critic + vulnerability fix pass *(task #59)*

- **Delivers:** Run `code-review` and `security-review` skills against the shipped v3 diff (both `backend/` and `frontend/`). Address critical findings; log medium-severity in `docs/plans/v3-followups.md`. `cargo audit` clean. `pnpm audit` clean. axe-playwright zero violations on the six main pages. Load test: 200 concurrent `GET /api/v1/questions/search` with `Semaphore(32)` cap; p95 < 300 ms. Sentry has received one test error from each stack. `openapi.json` in the frontend repo matches the running backend.
- **Effort:** ~8 h.
- **Exit criterion:** zero `cargo audit` HIGHs; zero `pnpm audit` HIGHs in production deps; every critical finding from the two review runs has a commit hash resolving it; `docs/plans/v3-followups.md` exists with the medium/low queue.
- **Blocks:** nothing — this closes v3.

---

## 6. Coexistence + migration strategy

**Chosen approach: Frontend-first strangler-fig (R5 Option C).** See R5 §1
for the full comparison against big-bang (A) and reverse-proxy (B).

The seam is the SPA's API client (`frontend/src/api/client.ts`), which
maintains a `ROUTES` map of prefix → `"flask" | "rust"`. Migrating a route
means:
1. Ship the Rust handler + tests (Phase 3-7 above).
2. Add the prefix to `ROUTES` pointing to `"rust"`.
3. Deploy the SPA (Vercel auto-deploy on merge).
4. Run the per-blueprint cutover checklist (R5 §13).
5. Rollback if needed: revert the one-line `ROUTES` change (~30 s).

**Coexistence rules (R5 §3):**
- Schema changes are additive-only until Flask is off (no renames, no
  drops, no new `NOT NULL` without defaults).
- The one exception is R2's `user_id` backfill — must run *before* signup
  ships, via the one-shot Python script `scripts/migrate_r2.py`.
- Flask's session cookie is replaced with a JWT-in-cookie during Phase 1
  prep so both services can read the same auth token. This is a 4-6 h
  Flask refactor that must land before Phase 3.

**Retirement timeline for Flask:**

| Week | Flask status |
|---|---|
| 1-5 | Serving 100 % of SPA traffic. JWT-in-cookie refactor lands. |
| 6-10 | Coexistence — some prefixes routed to Rust, others to Flask. Both services live at `api.exam...` and `api-legacy.exam...`. |
| 10 | Last blueprint migrated. SPA sends zero traffic to Flask. |
| 11 | Flask Render service *suspended* (not deleted). Branch `flask-legacy` tagged. |
| 15 | Flask branch deleted. Tag `v2-final-flask` retained for archaeology. |

Rollback windows:
- Per-blueprint: instant, entire Flask stack is 30 s away via a one-line
  frontend commit.
- Post-suspend: ~10 min to unsuspend Render service + flip
  `VITE_API_URL_RUST` to the legacy domain.
- Post-branch-delete: recover from git history + Turso B2 backups.

---

## 7. Cost estimate

Per R5 §16, all currencies USD/month.

| Item | Steady state | During coexistence (weeks 6-10) |
|---|---:|---:|
| Render Rust Web (Starter) | $7.00 | $7.00 |
| Render Flask Web (Starter) | $0.00 | $7.00 |
| Vercel Hobby | $0.00 | $0.00 |
| Turso free tier | $0.00 | $0.00 |
| Cloudflare DNS | $0.00 | $0.00 |
| Domain (`.dev`, amortized) | $0.83 | $0.83 |
| Resend (transactional email) | $0.00 | $0.00 |
| Sentry (5k events/mo) | $0.00 | $0.00 |
| Better Stack (1 GB logs/mo) | $0.00 | $0.00 |
| UptimeRobot | $0.00 | $0.00 |
| Backblaze B2 backups | ~$0.05 | ~$0.05 |
| **Monthly total** | **~$8** | **~$15** |

**Annual steady-state: ~$96/year.**

If we drop the custom domain and accept `*.onrender.com` +
`*.vercel.app`: **~$84/year**.

Growth thresholds (when things stop being free):
- Sentry beyond 5 k events/mo → $26/mo (Team).
- Better Stack beyond 1 GB → $10/mo.
- Vercel beyond 100 GB/mo bandwidth → $20/mo (Pro).
- Turso beyond 500 M row reads/mo → $29/mo (Scaler).
- Render CPU/RAM upgrade (Standard) → $25/mo.

At paid scale (~500 daily users) total lands around **$55/mo**.

---

## 8. Not-in-scope

**In scope:**
- Multi-user (signup, per-user data isolation, RBAC).
- All v2 features (SRS, palette, analytics, bookmarks, flags, admin,
  Deep Dive, dedupe, dark mode, mobile) carried forward under the new
  stack.
- Password reset via magic-link email.
- OpenAPI spec + TypeScript codegen.

**Explicitly out of scope for v3 (may become v4 plans):**
- Payment tiers / subscriptions / anything commercial.
- Native mobile app (iOS/Android). Responsive web only.
- Offline mode / service worker / PWA install prompt (R3 §15 open
  question; deferred).
- Teams, study groups, leaderboards, social features.
- Bilingual (Hindi/English) content — extraction is English-only.
- LLM-generated question explanations for empty `explanation` fields.
- Audio playback of questions.
- Bulk import of questions via CSV (admin flow stays PDF-upload only).
- Email verification on signup (R4 §2.6 defers; column reserved).
- Feature flags / A/B testing.
- CI/CD blue-green or canary — Render rolling deploys suffice.
- Multi-region deploy — single region ap-south / Singapore.
- Infrastructure-as-code (Terraform/Pulumi).
- On-call paging / PagerDuty.
- WAF / DDoS mitigation beyond Vercel + Render baselines.
- Migrating offline Python scripts (`ingest_pipeline.py`,
  `push_extracted_to_turso.py`, `build_batch3.py`, `seed.py`) to Rust —
  they stay Python.

---

## 9. Open questions to lock before or during Phase 1

Pick answers before Phase 3 (email transport) and Phase 10 (domain).

1. **Custom domain choice.** R5 recommends `.dev` (~$10/yr, Cloudflare
   Registrar). Alternatives: `.in` (~$8), `.app` (~$14). If the answer is
   "no custom domain, use free Render/Vercel subdomains for v3", cost
   drops by $1/mo and Phase 10 skips DNS steps. **Decision needed by
   Phase 10 start.**

2. **Email provider.** R5 §11.1 recommends Resend (3k/mo free, thin
   reqwest wrapper). Alternatives: Postmark ($15/mo min), SES (cheapest
   at scale, ugly DX). If we defer email entirely (accept "no password
   reset in v3"), Phase 3's scope shrinks by ~3 h. **Decision needed
   before Phase 3.**

3. **Sentry vs plain tracing logs.** R5 §10 assumes Sentry (5k events/mo
   free). Alternative: stick with `tracing` → Better Stack logs only, no
   crash-grouping, no user context. Sentry costs zero at solo scale but
   is one more account/DSN to manage. **Decision needed by Phase 10.**

4. **Render region.** R5 §19 recommends **Singapore** (closer to Turso
   `aws-ap-south-1`, ~50 ms saved per DB round trip vs Oregon). Confirm
   Render Starter is available in Singapore on Kartik's plan. **Decision
   needed by Phase 1 (render.yaml).**

5. **First-registrant auto-admin.** R4 §11 and R5 §11.2 both assume the
   migration script promotes the first-registered user to `admin`.
   Confirm this over shipping a `POST /admin/promote/{uid}` bootstrap
   endpoint gated by a one-time env-var token. **Decision needed by
   Phase 3.**

---

_Written 2026-07-19. Five research docs total 5,546 lines; this roadmap
is the sixth and shortest. Update this file whenever a phase closes or a
decision changes; do not let stale entries drift._
