# R5 — Migration Strategy & Deployment / Infra Plan

Companion to the v3 replatform series. **Planning only** — no code changes here.
Cross-refs (written or forthcoming):

- **R1** `v3-R1-rust-backend.md` — Axum / SQLx / libSQL backend architecture, module layout, error model
- **R2** `v3-R2-multi-user-schema.md` — Signup, `users` table extension, `user_id` backfill on every scoped table
- **R3** `v3-R3-react-frontend.md` — Vite + React + TS + TanStack Router/Query SPA structure
- **R4** `v3-R4-auth-and-security.md` — Access + refresh JWT, CSRF, rate-limit, password reset, session model

R5 (this doc) owns: **how to get from the running Flask app to the new stack without a downtime window, and where the new stack lives.**

---

## 0. TL;DR — what to do

1. **Migration shape: Frontend-first replace (Option C), with a short strangler-fig tail.**
   Ship React SPA against the *existing Flask API* first (thin JSON shim on top of current Flask), then swap the API host from Flask → Rust one blueprint at a time behind a reverse proxy. DNS never flips; the proxy is the seam.
2. **Deploy shape:** Rust API on Render (Docker, $7/mo), React SPA on Vercel Hobby (free), Turso stays, custom domain `exam.<yourname>.dev` with `api.exam.<yourname>.dev` for the backend.
3. **Cutover:** parallel run 2 weeks, then delete Flask service. Flask stays deployable-from-git for 30 days after cutover in case rollback is needed.
4. **Total monthly cost target: ~$8-10/mo** (Render $7 + domain $10/yr + everything else free tier).
5. **Defer email verification** — solo-dev use case + 1-2 users you personally know = friction not worth it. Ship password reset via magic-link *only if/when* you actually forget a password. See §11.

Total effort estimate for R5-specific work (excluding R1-R4 build effort): **~14h**
(Dockerfile, GH Actions, DNS, Vercel setup, one-shot migration script, cutover checklist run.)

---

## 1. Migration strategy — pick one

### Option A. Big-bang cutover
Build Rust+React entirely on the side against a **cloned** Turso DB (`exam-prep-db-pandit-staging`), test end-to-end for a week, then DNS-flip on a chosen weekend.

- **Pro:** clean cut, no interleaved code, no proxy config to reason about.
- **Con:** 4-8 weeks of no shipped changes to prod. You'll be tempted to sneak Flask fixes in, which then need porting. Cutover moment is high-stakes — if it fails, DNS-back is 5min but Turso schema may already be forward-migrated in ways Flask doesn't understand.
- **Risk:** single point of failure on cutover day. If the Rust build has a bug you didn't hit in staging, you have no Flask fallback because Turso has been dual-writing for a week and schema drifted.

### Option B. Strangler fig (reverse proxy)
Put nginx/Caddy in front. Route each endpoint to Flask or Rust individually. Retire Flask routes one blueprint at a time.

- **Pro:** true incremental. Every merged Rust route ships immediately. Rollback = flip one line in Caddyfile.
- **Con:** you're running two backend processes for ~6-8 weeks, both talking to the same Turso. Session/cookie compatibility becomes a real problem (Flask signs sessions with `FLASK_SECRET_KEY`, Rust with a different scheme). You have to standardize on JWT-in-cookie *before* the first strangled route, so the strangler prep itself is a small migration.
- **Con:** Render doesn't natively support "route these paths to service A, those to service B" on a single web service — you'd need a Caddy container running on Render as the front door, adding a second $7/mo service or a shared free-tier proxy.

### Option C. Frontend-first replace ← **recommended**
Order of operations:

1. **Phase F1 — Add JSON to existing Flask.** Take the ~10-15 read endpoints and 5-8 write endpoints the React SPA actually needs, and add `application/json` variants (or `Accept:` negotiation) to the *existing Flask routes*. No new tech — just Jinja routes learn to return JSON when asked. **~8h.**
2. **Phase F2 — Build React SPA against Flask JSON.** SPA runs on Vercel, calls `api.exam.<dom>.dev` which is *still Flask*. Flask is now headless. Verify feature parity in staging with the SPA. **~40-60h — this is R3.**
3. **Phase F3 — Point SPA at Rust for one endpoint.** Deploy Rust service to Render at `api2.exam.<dom>.dev` (or on a path prefix). Update SPA's API client to route `/api/v1/questions/*` → Rust, everything else → Flask. **~12h just for the swap plumbing; R1 owns the Rust routes themselves.**
4. **Phase F4 — Migrate blueprints.** Move `/api/v1/tests/*`, then `/api/v1/analytics/*`, then `/api/v1/auth/*`, then `/api/v1/admin/*` to Rust one at a time. After each, run the cutover checklist for that surface. **~4-6 weeks calendar time.**
5. **Phase F5 — Delete Flask.** Once no SPA calls hit Flask for 7 days (verified via Flask access logs), turn off the Render Flask service. Keep the git branch for 30 days.

**Why C over A and B:**

- **vs A:** you don't stop shipping. Every week you have working software; each week's demo is "SPA + more of it is Rust now."
- **vs B:** the "seam" is the *SPA's API client*, not a reverse proxy. That means no extra infra process, no Caddy container to babysit. The SPA already needs a runtime-configured `VITE_API_URL`; you make it a map instead of a string.
- **Solo dev + no user pressure**: C's slower calendar is fine because there's no one to disappoint. A's risk concentration on cutover day is the thing you can't afford — if a bug bites during a 4-hour cutover window at 11pm on a Sunday, you're the entire on-call.

**Recommendation: C. The rest of this doc assumes C.**

---

## 2. The API-client seam (how "SPA picks Flask or Rust per route" works)

Concrete pattern for phase F3-F4:

```ts
// frontend/src/api/client.ts
const FLASK = import.meta.env.VITE_API_URL_FLASK;   // https://api-legacy.exam.<dom>.dev
const RUST  = import.meta.env.VITE_API_URL_RUST;    // https://api.exam.<dom>.dev

// The routing table. Move entries from FLASK → RUST as each Rust route ships.
const ROUTES: Record<string, "flask" | "rust"> = {
  "/api/v1/auth/login":       "rust",
  "/api/v1/auth/logout":      "rust",
  "/api/v1/auth/signup":      "rust",
  "/api/v1/questions":        "rust",
  "/api/v1/tests":            "flask",   // not migrated yet
  "/api/v1/tests/submit":     "flask",
  "/api/v1/analytics":        "flask",
  "/api/v1/admin":            "flask",
};

export function apiUrl(path: string): string {
  // Longest-prefix match
  const match = Object.keys(ROUTES)
    .filter(p => path.startsWith(p))
    .sort((a, b) => b.length - a.length)[0];
  const host = match ? (ROUTES[match] === "rust" ? RUST : FLASK) : FLASK;
  return `${host}${path}`;
}
```

Rollback for any single endpoint = one-line change to `ROUTES`, redeploy Vercel (~30s). No DB changes, no Render config, no DNS.

---

## 3. Coexistence period — schema & session compatibility

During phase F3-F4, both Flask and Rust are reading/writing the same Turso DB. Two rules keep it safe:

### 3.1 Schema changes are **additive-only** until Flask is deleted

Allowed:
- `ALTER TABLE users ADD COLUMN email TEXT` (Flask ignores it — no code reads it)
- `ALTER TABLE users ADD COLUMN email_verified_at INTEGER` (with `DEFAULT NULL`)
- New tables (`refresh_tokens`, `password_resets`, `email_verifications`)
- New indices

Forbidden until Flask is off:
- Renaming columns (`username` → `handle`) — do a two-step: add new, dual-write, drop later
- Dropping columns Flask still references
- Adding `NOT NULL` without a default (Flask INSERTs won't include the column)
- Changing types (SQLite is loose but libSQL enforces more)

**One-time exception:** R2's `user_id` backfill on `mock_tests`, `test_responses`, `error_log`, `sr_cards`, `bookmarks`, `study_sessions`. That must happen **before** signup ships, because until then every row implicitly belongs to admin user 1. R2 owns this. R5 just notes: **run the backfill as part of phase F2's staging cutover, not phase F5.**

### 3.2 Session compatibility — the one thing that has to change **first**

Flask today uses signed session cookies (`Flask-Session` via `FLASK_SECRET_KEY`). Rust will use JWT (per R4). If both are live, the SPA needs one auth token both understand — otherwise "logged in on Flask but not on Rust" is a real bug.

**Fix:** during phase F1 (JSON-ifying Flask), also **replace Flask's session cookie with JWT-in-cookie**. Both services then read the same cookie, using a shared `JWT_SECRET`. This is a 4-6h refactor of `auth.py` and every `@login_required` decorator.

After this lands, Rust can be added with zero cookie migration.

**Details in R4 §Session model.**

### 3.3 Timeline sketch

```
Week 0        F1: Flask returns JSON on Accept: application/json          [8h]
Week 0        F1: Flask session cookie → JWT cookie                       [6h]
Week 1        R2 schema migrations (add columns, backfill user_id)        [R2]
Week 1-6      F2: React SPA build against Flask-JSON                      [R3, ~50h]
Week 6        F3: Deploy Rust skeleton to Render (health check only)      [R1 setup]
Week 6-10     F4: Migrate blueprints one at a time (see §7 order)         [R1]
Week 10       F5: Verify Flask access logs quiet 7 days
Week 11       F5: Turn off Flask Render service. Keep branch 30 days.
Week 15       F5: Delete Flask branch and code.
```

Calendar: ~10 weeks part-time (5 evenings/week, 3h each = 15h/week).

---

## 4. Deployment infrastructure

### 4.1 Text-art diagram

```
                                Internet
                                    │
                                    ▼
                     ┌──────────────────────────────┐
                     │       Cloudflare DNS         │
                     │  exam.<dom>.dev (CNAME →     │
                     │  Vercel), api.exam.<dom>.dev │
                     │  (CNAME → Render)            │
                     └──────────┬───────────────────┘
                                │
                ┌───────────────┼────────────────────┐
                │               │                    │
                ▼               ▼                    ▼
       ┌───────────────┐  ┌─────────────┐   ┌─────────────────┐
       │  Vercel Edge  │  │Render Web   │   │Render Web       │
       │  (SPA CDN)    │  │(Rust Axum   │   │(Flask, legacy   │
       │  React SPA    │  │Docker $7/mo)│   │$7/mo, phase-out)│
       │  exam.<dom>   │  │api.exam.<d> │   │api-legacy...    │
       └───────────────┘  └──────┬──────┘   └────────┬────────┘
                                 │                   │
                                 └─────────┬─────────┘
                                           │
                                           ▼
                                  ┌────────────────┐
                                  │     Turso      │
                                  │  libSQL (free  │
                                  │  tier, single  │
                                  │  db, ap-south) │
                                  └────────────────┘

    Observability:
       Vercel → Sentry (frontend errors), Vercel Analytics (RUM)
       Render → structured JSON logs → Better Stack free tier (14-day retain)
       Uptime → UptimeRobot free (5-min check on exam.<dom>.dev)
```

### 4.2 Component picks and rationale

| Layer | Choice | Alt considered | Why |
|---|---|---|---|
| Rust host | Render Web (Docker) | Fly.io, Railway, self-hosted | Already using Render; single dashboard; $7 starter enough for solo. Fly is a rewrite of DNS + secrets store. |
| SPA host | Vercel Hobby | Render Static, Cloudflare Pages, Netlify | Best DX for Vite React (zero config), preview URLs per PR, generous free bandwidth (100GB/mo). |
| DB | Turso (existing) | Neon, Supabase, PlanetScale | Already there, already has data, libSQL matches Rust ecosystem via `libsql` crate. No migration. |
| DNS | Cloudflare | Route53, Namecheap DNS | Free, fast propagation, page rules if ever needed, easy proxy toggle. |
| Domain registrar | Cloudflare or Porkbun | Namecheap, GoDaddy | ~$10/yr for `.dev` TLD. Cloudflare charges wholesale, no upcharge. |
| TLS | Auto (Render + Vercel) | Let's Encrypt manual | Both platforms handle renewal; zero-touch. |
| CDN | Vercel Edge (SPA), Render's basic (API) | Cloudflare in front | Bundled with hosts. Only bolt Cloudflare on if bandwidth or attack becomes a real concern. |
| Email | Resend | Postmark, SES, SendGrid | 3000/mo free, cleanest DX, first-party React Email components. |
| Errors | Sentry | Rollbar, Bugsnag | Free tier (5k events/mo) covers hobby; SDK maturity best-in-class. |
| Logs | Better Stack (Logtail) | Grafana Cloud, Axiom | 1GB/mo free, good search, Render's built-in shipping works. |
| Uptime | UptimeRobot | Better Stack Uptime, Cronitor | Free 50 monitors, 5-min interval; separate from log vendor. |

### 4.3 Domain structure

Recommendation:

- Buy `<yourname>.dev` (Cloudflare Registrar, ~$10/yr). Or `<yourname>.in` if you prefer local TLD (~$8-15/yr).
- Subdomain layout:
  - `exam.<dom>.dev` — React SPA (Vercel)
  - `api.exam.<dom>.dev` — Rust backend (Render)
  - `api-legacy.exam.<dom>.dev` — Flask backend during phase F3-F4 (Render, same service as today, just renamed via custom domain)
  - `docs.exam.<dom>.dev` — future (mdBook / VitePress / whatever, deferred)

DNS records (Cloudflare):

```
exam.<dom>.dev            CNAME  cname.vercel-dns.com          Proxy: DNS only
api.exam.<dom>.dev        CNAME  <rust-service>.onrender.com   Proxy: DNS only
api-legacy.exam.<dom>.dev CNAME  <flask-service>.onrender.com  Proxy: DNS only
```

**"DNS only" not "Proxied"** — Render's TLS termination expects direct connections; putting Cloudflare's orange-cloud in the middle breaks their auto-cert issuance until you configure origin certs. Not worth the pain at this scale.

---

## 5. Rust backend — Dockerfile pattern

Multi-stage, static musl binary, ~40MB final image. Fast Render deploys (~2-3min cold build, 40s with cache).

```dockerfile
# ---- Stage 1: cargo-chef prep (dependency caching) ----
FROM rust:1.83-slim-bookworm AS chef
RUN cargo install cargo-chef --locked
WORKDIR /app

FROM chef AS planner
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
RUN cargo chef prepare --recipe-path recipe.json

# ---- Stage 2: build deps (cached layer) ----
FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

# ---- Stage 3: build app ----
COPY . .
RUN cargo build --release --bin exam-prep-api

# ---- Stage 4: runtime ----
FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 1001 --home /app appuser
WORKDIR /app
COPY --from=builder /app/target/release/exam-prep-api /usr/local/bin/exam-prep-api

USER appuser
ENV RUST_LOG=info \
    PORT=10000
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:${PORT}/healthz || exit 1

CMD ["exam-prep-api"]
```

Notes:

- `cargo-chef` gives you Docker layer caching for deps — critical because Render rebuilds on every push, and without chef your ~200-dep Rust project is 5-10min cold builds.
- Not using `distroless` or `scratch` because `libsql` + Turso may need `ca-certificates` for TLS; `debian:bookworm-slim` is 74MB base and worth the sanity.
- Not static-linking with musl by default — `libsql-client` has issues with musl in some versions; stick with glibc unless you specifically need to target Alpine.
- `HEALTHCHECK` matches Render's expectation for `GET /healthz` returning 200.

Companion `render.yaml` for the Rust service (to add alongside the Flask one, then replace):

```yaml
services:
  - type: web
    name: exam-prep-api
    env: docker
    dockerfilePath: ./Dockerfile
    plan: starter
    healthCheckPath: /healthz
    envVars:
      - key: TURSO_DB_URL
        value: libsql://exam-prep-db-pandit.aws-ap-south-1.turso.io
      - key: TURSO_AUTH_TOKEN
        sync: false
      - key: JWT_SECRET
        sync: false
      - key: JWT_REFRESH_SECRET
        sync: false
      - key: GEMINI_API_KEY
        sync: false
      - key: DEEPSEEK_PRIMARY_KEY
        sync: false
      - key: DEEPSEEK_SECONDARY_KEY
        sync: false
      - key: GLM_API_KEY
        sync: false
      - key: RESEND_API_KEY
        sync: false
      - key: SENTRY_DSN
        sync: false
      - key: RUST_LOG
        value: exam_prep_api=info,tower_http=info
      - key: CORS_ORIGIN
        value: https://exam.<dom>.dev
      - key: COOKIE_DOMAIN
        value: .exam.<dom>.dev
```

---

## 6. Frontend — Vercel config

`vercel.json` at repo root of the frontend package:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": "vite",
  "buildCommand": "pnpm build",
  "installCommand": "pnpm install --frozen-lockfile",
  "outputDirectory": "dist",
  "devCommand": "pnpm dev",
  "cleanUrls": true,
  "trailingSlash": false,
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ],
  "headers": [
    {
      "source": "/assets/(.*)",
      "headers": [
        { "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }
      ]
    },
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Frame-Options", "value": "DENY" },
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" },
        { "key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()" },
        {
          "key": "Content-Security-Policy",
          "value": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https://api.exam.<dom>.dev https://api-legacy.exam.<dom>.dev https://sentry.io; font-src 'self' data:; frame-ancestors 'none';"
        }
      ]
    }
  ]
}
```

- SPA rewrite makes deep-links (`/analytics`, `/test/take`) work — Vercel serves `index.html`, React Router takes over.
- Long-cache for `/assets/*` because Vite hashes filenames; `index.html` stays default (short cache).
- CSP `connect-src` allow-lists both API hosts during coexistence.
- Env vars set in Vercel dashboard: `VITE_API_URL_RUST`, `VITE_API_URL_FLASK`, `VITE_SENTRY_DSN` (public DSN), `VITE_POSTHOG_KEY` (optional).

---

## 7. Blueprint migration order (phase F4)

Ordered by risk × leverage. Migrate top-down; run cutover checklist §12 for each blueprint after it ships.

| Order | Blueprint | Rust module | Why this order |
|---|---|---|---|
| 1 | `bp_auth` (`/login`, `/logout`, `+signup`) | `auth` | Everything downstream needs auth. Also smallest surface (~3 routes). Prove the plumbing here. |
| 2 | `bp_api` — question read + submit | `api::questions`, `api::submit` | Hottest path (every test hits this). Ship it early so real-world load exercises the Rust runtime. |
| 3 | `bp_tests` — setup, take, finish, results | `tests` | Complex but self-contained. After this, "taking a test" runs entirely on Rust. |
| 4 | `bp_analytics` | `analytics` | Read-only queries, low risk. Good bake time before touching admin. |
| 5 | `bp_review`, `bp_errorlog` | `review` | Small; batches with 4 for calendar convenience. |
| 6 | `bp_main` (`/`, `/bookmarks`, `/search`) | `pages` (or fold into SPA + `api::search`) | Most of `bp_main` becomes SPA routes; only `/api/search` needs a Rust handler. |
| 7 | `bp_doubt` (`/deep-dive`, `/chat`) | `ai::doubt` | AI proxying — needs `reqwest` + streaming. Last non-admin thing because streaming SSE takes more care. |
| 8 | `bp_admin` (all admin routes) | `admin` | Largest surface (~20 routes). Do last — admin is only used by you, and Flask can serve it indefinitely if needed. |
| 9 | `bp_diag` | `diag` | Trivial, do last or drop entirely. |

**Do NOT migrate `ingest_pipeline.py`, `push_extracted_to_turso.py`, `build_batch3.py`, `seed.py`** — these are offline scripts. Leave them as Python. R1 explicitly scopes to the web-serving layer; admin data ingestion stays Python because it uses `pdfplumber`, `pypdf`, Gemini SDK, etc., which have no Rust equivalents worth writing.

**Estimated per-blueprint effort (Rust side, from R1):** ~4-8h each × 9 = **~50h.** R5's contribution per blueprint is the cutover step: ~30min each.

---

## 8. CI/CD — GitHub Actions

### 8.1 Backend workflow

`.github/workflows/backend.yml`:

```yaml
name: backend

on:
  push:
    branches: [main]
    paths: ['backend/**', '.github/workflows/backend.yml']
  pull_request:
    paths: ['backend/**']

jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: rustfmt, clippy
      - uses: Swatinem/rust-cache@v2
        with:
          workspaces: backend
      - name: fmt
        run: cargo fmt --check
      - name: clippy
        run: cargo clippy --all-targets --all-features -- -D warnings
      - name: test
        run: cargo test --all-features
        env:
          TURSO_DB_URL: file:./test.db
          JWT_SECRET: test-secret-do-not-use
          JWT_REFRESH_SECRET: test-refresh-do-not-use

  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: rustsec/audit-check@v1
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

  # Render auto-deploys from main. No explicit push step needed.
  # Just gate merges on this workflow being green.
```

### 8.2 Frontend workflow

`.github/workflows/frontend.yml`:

```yaml
name: frontend

on:
  push:
    branches: [main]
    paths: ['frontend/**', '.github/workflows/frontend.yml']
  pull_request:
    paths: ['frontend/**']

jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v3
        with:
          version: 9
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm typecheck
      - run: pnpm lint
      - run: pnpm test -- --run
      - run: pnpm build
      - uses: actions/upload-artifact@v4
        if: github.event_name == 'pull_request'
        with:
          name: build-${{ github.sha }}
          path: frontend/dist
          retention-days: 7

  # Vercel deploys via GitHub integration (PR previews + main).
  # This job just validates; Vercel handles the deploy.
```

### 8.3 E2E workflow

`.github/workflows/e2e.yml`:

```yaml
name: e2e

on:
  deployment_status:

jobs:
  playwright:
    if: github.event.deployment_status.state == 'success' &&
        contains(github.event.deployment_status.environment_url, 'vercel.app')
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v3
        with:
          version: 9
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm exec playwright install --with-deps chromium
      - name: run e2e against Vercel preview
        run: pnpm exec playwright test
        env:
          PLAYWRIGHT_BASE_URL: ${{ github.event.deployment_status.environment_url }}
          E2E_USER: ${{ secrets.E2E_USER }}
          E2E_PASS: ${{ secrets.E2E_PASS }}
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: frontend/playwright-report
```

**Test scope for E2E (keep small):** login → take a 5-question mock → see results → dashboard shows +1 test. 3-4 tests total. Don't try to E2E every screen — unit + component tests carry more of the load; E2E just catches "broken deploy" not "broken logic."

---

## 9. Env var management

### 9.1 Rust backend (Render dashboard)

| Var | Purpose | Sensitive? |
|---|---|---|
| `TURSO_DB_URL` | libsql://... | No (URL only) |
| `TURSO_AUTH_TOKEN` | JWT for Turso | **Yes** |
| `JWT_SECRET` | Access token sign key (>=64B random) | **Yes** |
| `JWT_REFRESH_SECRET` | Refresh token sign key (separate) | **Yes** |
| `GEMINI_API_KEY` | Google AI (bp_doubt) | **Yes** |
| `DEEPSEEK_PRIMARY_KEY` | DeepSeek (fallback) | **Yes** |
| `DEEPSEEK_SECONDARY_KEY` | DeepSeek (2nd fallback) | **Yes** |
| `GLM_API_KEY` | Zhipu GLM (3rd fallback) | **Yes** |
| `RESEND_API_KEY` | Email sending | **Yes** |
| `SMTP_*` | Only if you switch off Resend | **Yes** |
| `SENTRY_DSN` | Server-side error tracking | Low (semi-public) |
| `RUST_LOG` | e.g., `exam_prep_api=info,tower_http=info` | No |
| `CORS_ORIGIN` | e.g., `https://exam.<dom>.dev` | No |
| `COOKIE_DOMAIN` | e.g., `.exam.<dom>.dev` | No |
| `PORT` | Render provides; default 10000 | No |

### 9.2 Frontend (Vercel dashboard)

Only `VITE_*` prefixed vars are exposed to the client — never put secrets here.

| Var | Purpose |
|---|---|
| `VITE_API_URL_RUST` | `https://api.exam.<dom>.dev` |
| `VITE_API_URL_FLASK` | `https://api-legacy.exam.<dom>.dev` (empty after F5) |
| `VITE_SENTRY_DSN` | Public DSN — Sentry designs these to be exposed |
| `VITE_POSTHOG_KEY` | Public key — optional analytics |
| `VITE_ENV` | `production` / `preview` / `development` |

### 9.3 Local dev (`.env.local`, git-ignored)

Both backend and frontend get a `.env.example` in git. The real `.env.local` never commits. Enforce with `.gitignore` + a pre-commit hook that greps for known secret prefixes (`libsql://.*:eyJ`, `sk_live_`, etc.).

### 9.4 Secrets manager — later

For 1-2 services, Render + Vercel dashboards are fine. Reach for **Doppler** or **Infisical** only when:

- You have 3+ services sharing secrets and drift becomes real, or
- You need audit logs on secret access, or
- You start rotating on a schedule and want automation.

At current scale (1 user, 2 services), this is over-engineering. Note it in the plan but **do not** set it up.

Cost when you do: Doppler free up to 5 users; Infisical free self-hosted or $9/mo cloud.

---

## 10. Observability

### 10.1 Rust backend

- **Tracing:** `tracing` + `tracing-subscriber` with `tracing-subscriber::fmt().json()` in production. Every request gets a `request_id` in a middleware layer.
- **Log shipping:** Render's log stream → Better Stack (Logtail) source. Free tier is 1GB/mo — for solo use that's ~100M log lines/mo, plenty. Set retention to 14 days.
- **Errors:** `sentry-tower` layer catches panics + `Result::Err` returns tagged with `tracing::error!`. Sample rate 1.0 in prod (low volume; you want everything).
- **Metrics:** skip Prometheus. At this scale, `tracing` events + Better Stack aggregations answer "how many 500s in the last hour" fine. Reach for metrics when you need percentile latency or SLOs.
- **Tracing / spans → OpenTelemetry:** later. Not needed at v1.

### 10.2 Frontend

- **Errors:** `@sentry/react` with `browserTracingIntegration` off (perf tracing costs event budget; skip).
- **Behavior analytics:** **defer PostHog.** Solo user = you know what you did. Add when you have >5 users or want funnel data.
- **Web vitals:** Vercel Analytics is free on Hobby and auto-collects CLS/LCP/INP. Turn it on, glance monthly.

### 10.3 Uptime

- UptimeRobot free plan: 5-min interval, 3 monitors:
  1. `https://exam.<dom>.dev/` — 200 OK, contains `<title>Exam Prep`
  2. `https://api.exam.<dom>.dev/healthz` — 200 OK, body `ok`
  3. `https://api-legacy.exam.<dom>.dev/healthz` — during coexistence only
- Alerts → email + Telegram webhook (or Slack, whichever you actually check).
- Render also does its own health checks on `/healthz` and restarts on failure. UptimeRobot is the external witness.

### 10.4 Cost of observability

| Item | Free tier | If you outgrow |
|---|---|---|
| Sentry | 5k events/mo | $26/mo team |
| Better Stack | 1GB/mo, 14-day | $10/mo |
| UptimeRobot | 50 monitors, 5-min | $8/mo Pro (1-min) |
| Vercel Analytics | Included Hobby | $10/mo Pro |
| PostHog | Deferred | 1M events free anyway |

**Total obs cost at hobby scale: $0.** At small paid scale: ~$40-55/mo. You are years away from that.

---

## 11. Emails — signup verification + password reset

### 11.1 Provider pick: **Resend**

Rationale:
- Free tier: 3,000/mo, 100/day. Solo dev = maybe 5 emails/mo. Free forever at this scale.
- Rust SDK: no official crate, but a thin `reqwest` wrapper against their REST API is 40 lines. Fine.
- React Email components — nice for building the two templates you'll need (verification + reset), but Jinja/HTML string templates are also fine.
- Alternative: **Postmark** — better transactional deliverability rep, $15/mo minimum. Overkill.
- Alternative: **SES** — $0.10 per 1000, cheapest at scale, brutal DX. Not worth it here.
- Alternative: **SMTP via Gmail** — 500/day free but flagged as consumer, bad reputation for prod signups. Avoid.

Setup:
1. Verify sending domain `<dom>.dev` (DKIM + SPF DNS records in Cloudflare).
2. From address: `noreply@exam.<dom>.dev`.
3. Reply-to: your personal email so bounces reach you.

### 11.2 Should we ship email verification at all? — **No, defer.**

Arguments for shipping now:
- "Real" signup flow, ready for growth.
- Prevents typo emails from locking users out (can't reset password on typo'd address).

Arguments against, given solo-dev / handful-of-users context:
- **Friction:** every signup interrupts the user for 30s-2min hunting an inbox. For 1-3 known users, this is annoyance-for-no-gain.
- **Extra failure surface:** verification email lands in spam → user thinks signup broke → messages you. Now you're on-call for email deliverability.
- **Nothing depends on it yet:** no public payments, no PII beyond a study log, no shared content where impersonation matters.
- **YAGNI:** if a friend or two joins, you can DM them their credentials on the way in. When the user list crosses ~10 or you want a public signup form on the marketing site, revisit.

**Ship instead:**
- Signup with email + password + display name. No verification.
- Password reset via magic-link email — this one is worth building because password loss is the only realistic account-recovery scenario. Send link, 15-min expiry, single-use token. R4 owns the token model.
- Add a `email_verified_at INTEGER NULL` column now anyway (so future flip is a code change, not a schema change). See §3.1.

**Signup flow sketch (post-defer decision):**

```
User submits { email, password, display_name }
  ↓
POST /api/v1/auth/signup
  ↓
Rust: validate → argon2 hash → INSERT users → issue JWT pair
  ↓
Set-Cookie: access + refresh (httpOnly, secure, SameSite=Lax)
  ↓
Return { user: { id, email, display_name } }
  ↓
SPA: redirect to /dashboard
  ↓
(No email sent. email_verified_at stays NULL.)
```

**Password reset flow sketch:**

```
User clicks "Forgot password?" → enters email
  ↓
POST /api/v1/auth/password-reset/request { email }
  ↓
Rust: look up user (always 200 OK to avoid enumeration)
       if found: generate token, INSERT password_resets (token_hash, user_id, expires_at=now+15min)
                 Resend: send email with https://exam.<dom>.dev/reset?token=<token>
  ↓
User clicks link → SPA loads /reset → POST /api/v1/auth/password-reset/confirm { token, new_password }
  ↓
Rust: validate token, argon2 rehash, UPDATE users, DELETE password_resets row
  ↓
Return { ok: true }, SPA redirects to /login
```

---

## 12. One-shot data migration script

Runs at phase F2 end (right before signup ships). Python, kept in the existing Flask repo under `scripts/migrate_r2.py`.

```python
"""
One-shot migration for R2 (multi-user). Idempotent — safe to re-run.

Steps:
  1. Snapshot Turso via `turso db dump > backup-<ts>.sql`.
  2. Verify baseline counts against a known-good manifest.
  3. Add columns / tables (backward-compatible — Flask still works).
  4. Backfill user_id = 1 on all scoped tables where NULL.
  5. Verify no NULLs remain in user_id columns.
  6. Print summary, wait for 'YES' confirmation before finalizing.
"""

import os, sys, time, subprocess, hashlib
from libsql_client import create_client_sync

EXPECTED = {
    "questions":       3712,
    "mock_tests":        33,
    "sr_cards":         302,   # approx — accept +/- 5
    "users":              1,
}

def snapshot():
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = f"backup-{ts}.sql"
    subprocess.check_call(
        ["turso", "db", "dump", "exam-prep-db-pandit", "--output", path],
        env={**os.environ},
    )
    size = os.path.getsize(path)
    sha  = hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]
    print(f"[1/6] snapshot: {path} ({size:,} bytes, sha256:{sha})")
    return path

def verify_baseline(client):
    print("[2/6] verifying baseline counts...")
    for table, expected in EXPECTED.items():
        got = client.execute(f"SELECT COUNT(*) FROM {table}").rows[0][0]
        # sr_cards is fuzzy; others must be exact
        ok = (abs(got - expected) <= 5) if table == "sr_cards" else (got == expected)
        marker = "OK" if ok else "FAIL"
        print(f"      {marker:4}  {table}: expected {expected}, got {got}")
        if not ok:
            sys.exit(f"baseline mismatch on {table} — aborting")

def apply_ddl(client):
    print("[3/6] applying additive DDL...")
    stmts = [
        # R2 additions on users
        "ALTER TABLE users ADD COLUMN email TEXT",
        "ALTER TABLE users ADD COLUMN email_verified_at INTEGER",
        "ALTER TABLE users ADD COLUMN display_name TEXT",
        "ALTER TABLE users ADD COLUMN created_at INTEGER DEFAULT (unixepoch())",
        # user_id on scoped tables
        "ALTER TABLE mock_tests      ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE test_responses  ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE error_log       ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE sr_cards        ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE bookmarks       ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE study_sessions  ADD COLUMN user_id INTEGER REFERENCES users(id)",
        # Auth tables
        """CREATE TABLE IF NOT EXISTS refresh_tokens (
             id INTEGER PRIMARY KEY,
             user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
             token_hash TEXT NOT NULL UNIQUE,
             expires_at INTEGER NOT NULL,
             created_at INTEGER NOT NULL DEFAULT (unixepoch()),
             revoked_at INTEGER
           )""",
        """CREATE TABLE IF NOT EXISTS password_resets (
             id INTEGER PRIMARY KEY,
             user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
             token_hash TEXT NOT NULL UNIQUE,
             expires_at INTEGER NOT NULL,
             used_at INTEGER
           )""",
        # Indices
        "CREATE INDEX IF NOT EXISTS idx_mock_tests_user      ON mock_tests(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_test_responses_user  ON test_responses(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_error_log_user       ON error_log(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sr_cards_user        ON sr_cards(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_users_email          ON users(email) WHERE email IS NOT NULL",
    ]
    for s in stmts:
        try:
            client.execute(s)
            print(f"      OK   {s[:60]}...")
        except Exception as e:
            # ALTER ADD COLUMN is not idempotent — catch "duplicate column" and continue
            msg = str(e).lower()
            if "duplicate" in msg or "already exists" in msg:
                print(f"      SKIP {s[:60]}...  (already applied)")
            else:
                raise

def backfill(client):
    print("[4/6] backfilling user_id = 1 on scoped tables...")
    for table in ["mock_tests", "test_responses", "error_log", "sr_cards", "bookmarks", "study_sessions"]:
        r = client.execute(f"UPDATE {table} SET user_id = 1 WHERE user_id IS NULL")
        print(f"      OK  {table}: updated {r.rows_affected} rows")

def verify_no_nulls(client):
    print("[5/6] verifying no NULLs remain in user_id...")
    for table in ["mock_tests", "test_responses", "error_log", "sr_cards", "bookmarks", "study_sessions"]:
        n = client.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL").rows[0][0]
        marker = "OK" if n == 0 else "FAIL"
        print(f"      {marker:4}  {table}: {n} nulls")
        if n:
            sys.exit(f"post-backfill nulls in {table} — aborting")

def confirm():
    print("[6/6] SUMMARY:")
    print("      - Snapshot written")
    print("      - Schema forward-migrated (backward-compatible)")
    print("      - All user-scoped rows attributed to user_id=1")
    print("")
    ans = input("Proceed with 'go live' (mark migration done)?  type YES: ")
    if ans.strip() != "YES":
        sys.exit("aborted by operator")
    print("migration finalized. now safe to deploy R2-aware code.")

def main():
    snapshot()
    client = create_client_sync(
        url=os.environ["TURSO_DB_URL"],
        auth_token=os.environ["TURSO_AUTH_TOKEN"],
    )
    verify_baseline(client)
    apply_ddl(client)
    backfill(client)
    verify_no_nulls(client)
    confirm()

if __name__ == "__main__":
    main()
```

Run against staging DB first (`exam-prep-db-pandit-staging`, forked via `turso db fork`). If it prints green all the way through, then run against prod during a maintenance window.

---

## 13. Cutover checklist (per-blueprint, phase F4)

For each blueprint you migrate from Flask → Rust, before flipping the client routing map:

**Functional parity (must pass):**
- [ ] Rust route responds 200 for the happy path (curl or Bruno)
- [ ] Response JSON shape matches Flask's `application/json` output field-for-field
- [ ] Auth cookie is honored (JWT decode succeeds)
- [ ] All error responses use the shared error envelope from R1 (`{"error": {"code", "message"}}`)
- [ ] For each Flask route: search SPA source for its path — replace with Rust path or drop if unused

**Data safety:**
- [ ] Rust queries scope by `user_id = current_user()` on every table where R2 added `user_id`
- [ ] No hardcoded `user_id = 1` outside of test fixtures

**Performance:**
- [ ] p50 latency ≤ 1.5× Flask baseline (spot-check via Render metrics)
- [ ] No new N+1: use a Rust-side query counter middleware for smoke tests

**Rollback readiness:**
- [ ] Flask route still deployed and reachable at `api-legacy.exam.<dom>.dev`
- [ ] `ROUTES` map change is a single-line commit (easy to revert)

**Final cutover (once ALL blueprints migrated):**
- [ ] All 51 (currently 50) Flask routes have Rust equivalents *or* have been intentionally dropped (list the dropped ones in a `dropped-routes.md`)
- [ ] `SELECT COUNT(*) FROM questions` returns 3712 (or your then-current count)
- [ ] Login works for admin user (curl `POST /api/v1/auth/login` with your creds)
- [ ] Take one full mock test end-to-end via the SPA — submit, land on results, see it in analytics
- [ ] Analytics page renders: mastery grid, weakness heatmap, pacing chart, consistency score
- [ ] Deep-Dive returns text for one question (verify AI proxy works, all three keys tried on primary failure)
- [ ] Admin panel: flags list loads, review queue loads, duplicates page loads, upload+import a small test PDF
- [ ] Dark mode toggles without flash on every page (spot-check 6 pages)
- [ ] Mobile: iPhone SE 375px — home, test/setup, test/take, results, analytics, errorlog. No horizontal scroll, no clipped controls.
- [ ] Search from Cmd-K finds a known question in <500ms
- [ ] SPA CSP has no console errors (network tab shows no blocked requests)
- [ ] Sentry receives a test error from both frontend and backend
- [ ] Uptime monitors green for 24h
- [ ] Cost: Render usage report shows only the Rust service billed, Flask spun down

---

## 14. Rollback plan

### 14.1 Per-blueprint rollback (during F4)

**Detection:** SPA errors spike in Sentry, or 5xx rate on `api.exam.<dom>.dev` > 1% for 5 min.

**Steps (2 minutes):**
1. In `frontend/src/api/client.ts`, change the affected prefix in `ROUTES` from `"rust"` back to `"flask"`.
2. Push to main; Vercel auto-deploys in ~30s.
3. Sentry rate returns to baseline within 5min. Investigate offline.

Since Flask is still running at `api-legacy.exam.<dom>.dev`, this is a zero-downtime revert. **This is why C is safer than A.**

### 14.2 Full rollback (post-F5, "we shouldn't have deleted Flask yet")

If a critical bug surfaces after Flask is turned off:

1. Redeploy Flask branch (`git checkout flask-legacy` — kept for 30 days per §3.3). Render service still exists but is suspended; unsuspend and deploy.
2. If schema drifted forward with columns/tables Flask doesn't know about, that's fine — Flask ignores unknown columns. It only fails if a column it DOES know about was renamed or dropped. Per §3.1, we don't rename/drop until Flask is deleted, so this shouldn't happen.
3. Flip SPA `VITE_API_URL_RUST` to `api-legacy...` domain temporarily.
4. Post-mortem, fix, retry.

**Window:** Flask branch + Render service preserved 30 days after F5 completes. Then delete.

### 14.3 Turso rollback (data corruption)

- Every deploy runs `turso db dump` first via a pre-deploy hook (add to Rust `render.yaml` as a `preDeployCommand`? Render doesn't support that; do it in CI instead — see §8.1, add a step before deploying that dumps and uploads to S3 or Backblaze B2).
- Retention: 7 rolling daily dumps + 4 weekly + 3 monthly, stored on B2 free tier (10GB).
- Restore path: `turso db shell < backup.sql` on a fresh DB, re-point `TURSO_DB_URL`.

---

## 15. Domain / DNS setup steps

Assuming registrar = Cloudflare, DNS = Cloudflare, TLDs = `.dev`:

1. Buy `<yourname>.dev` at Cloudflare Registrar (~$10/yr, wholesale).
2. Cloudflare auto-configures nameservers; no glue needed.
3. Add records in Cloudflare DNS:
   - `A` @ pointing to `1.1.1.1` (placeholder — you can drop a landing page here later)
   - `CNAME exam` → `cname.vercel-dns.com` (Vercel gives you the target after adding the domain in their dashboard)
   - `CNAME api.exam` → `<rust-service>.onrender.com`
   - `CNAME api-legacy.exam` → `<flask-service>.onrender.com`
4. In Vercel dashboard: **Settings → Domains → Add** `exam.<dom>.dev`. Vercel issues cert via ACME within ~30s.
5. In Render dashboard for the Rust service: **Settings → Custom Domains → Add** `api.exam.<dom>.dev`. Same for Flask service with `api-legacy.exam...`.
6. Wait for TLS to go green on all three (~1-5min).
7. Test: `curl -I https://exam.<dom>.dev/` returns 200 from Vercel, `curl https://api.exam.<dom>.dev/healthz` returns `ok`.

### Edge caching
- Vercel Edge Cache serves the SPA globally. `index.html` no-cache, `/assets/*.{js,css,woff2}` cached 1 year (immutable hashes handle busting).
- Render has no meaningful edge cache; API responses are dynamic anyway. If you ever add public read-only endpoints (unlikely for this app), consider Cloudflare in front then. Not now.

---

## 16. Cost estimate

| Line item | Amount / mo | Notes |
|---|---|---|
| Render Rust Web (Starter) | $7.00 | 512MB RAM, 0.5 CPU — plenty for 1-5 users |
| Render Flask Web (Starter) | $7.00 | Only during F3-F5 coexistence (~4-6 weeks) |
| Vercel Hobby | $0.00 | Free — well under 100GB bandwidth |
| Turso | $0.00 | Free tier: 500 DBs, 9GB storage, 500M rows read/mo |
| Cloudflare DNS | $0.00 | Free |
| Cloudflare Registrar | ~$0.83 | `.dev` at ~$10/yr |
| Resend | $0.00 | 3k/mo free, you'll use <50 |
| Sentry | $0.00 | 5k events/mo free |
| Better Stack | $0.00 | 1GB logs/mo free |
| UptimeRobot | $0.00 | 50 monitors free |
| Backblaze B2 backups | ~$0.05 | 10GB free; overage $0.005/GB — a year of daily dumps is ~2GB |
| **Steady-state total** | **~$8/mo** | |
| **During coexistence** | **~$15/mo** | Extra $7 for Flask, for 4-6 weeks |

**Annual: ~$100/yr.** Deleting Flask brings it to ~$96/yr.

If you never buy a domain and stick with `*.onrender.com` + `*.vercel.app`: ~$84/yr.

---

## 17. Effort summary (R5-specific)

| Section | Task | Hours |
|---|---|---|
| §5 | Write Dockerfile + verify local build | 2 |
| §5 | Add `render.yaml` for Rust service, verify deploy pipeline works with a hello-world | 1.5 |
| §6 | Vercel setup: link repo, `vercel.json`, first deploy | 1 |
| §8 | Backend GH Actions workflow | 1.5 |
| §8 | Frontend GH Actions workflow | 1 |
| §8 | E2E workflow + 3 Playwright specs | 3 |
| §12 | Data migration script (in this doc — port to `scripts/migrate_r2.py`) | 2 |
| §15 | Domain purchase + DNS + TLS wiring | 1 |
| §13 | Cutover checklist execution (per blueprint × 9, ~30min each) | 4.5 |
| §14 | Rollback rehearsal (once, in staging) | 1 |
| §11 | Resend account + DKIM/SPF + first email template | 1.5 |
| §10 | Sentry projects (2) + Better Stack source + UptimeRobot monitors | 1 |
| — | Buffer / debugging | 3 |
| **Total** | | **~24h** |

(Higher than the TL;DR estimate of ~14h — that number covered "the migration/deploy work" narrowly; adding observability + email + rollback rehearsal + buffer honestly lands closer to 24h.)

**This is separate from R1 (Rust build, ~120h), R3 (React build, ~80h), R2 (multi-user schema, ~15h), and R4 (auth/security, ~25h).** Total v3 replatform: ~260h calendar-effort. At 15h/week solo evenings = ~17 weeks / ~4 months. Realistic given day job and holidays: 5-6 months.

---

## 18. Explicit non-goals of R5

Called out so they don't scope-creep in mid-execution:

- Blue/green or canary deploys — Render's rolling deploy is enough at this scale.
- Multi-region: single region (`aws-ap-south-1` Turso + Render Oregon or Singapore) is fine. Latency across regions is not a UX blocker for a study app.
- Infrastructure-as-code (Terraform/Pulumi) — 2 services + DNS is faster clicked once than templated. Revisit if you spin up staging + dev + prod.
- Kubernetes / Nomad / any orchestrator — pure Render + Vercel until you have real reason.
- On-call / paging — UptimeRobot email is enough; you'd read email before a PagerDuty page anyway.
- Feature flags — solo user, no A/B. `if env == "prod"` covers you.
- WAF / DDoS mitigation — Render and Vercel provide baseline. Add Cloudflare-in-front only if attacked.

---

## 19. Open questions / decisions to lock before starting

1. **Registrar / TLD** — confirm you want `.dev`; alternative is `.in` (~$8) or `.app` (~$14) or `.study` (~$40, don't). Recommendation: `.dev` for the tooling reputation.
2. **Rust host region** — Render Singapore is closer to Turso `aws-ap-south-1` (Mumbai) than Oregon. **Pick Singapore.** ~50ms saved on every DB round trip.
3. **Email verification defer?** — R5 argues defer (§11.2). Confirm.
4. **Delete Flask branch after 30 days?** — or preserve indefinitely as a museum piece? Recommend delete + rely on git tag `v2-final-flask` for archaeology.
5. **Backup destination** — Backblaze B2 (recommended) vs. Cloudflare R2 (cheaper egress, similar tier) vs. skip external backups and rely on Turso's built-in point-in-time restore (Turso Pro $29/mo — too pricey, but they may offer daily-snapshot on free by the time you need it). **Recommend B2** for the free 10GB.
6. **Migrate Python offline scripts (`ingest_pipeline.py`, `bp_admin.py` upload/import) to Rust?** — R5 says **no** (§7 bottom). Confirm.

---

## 20. Cross-references

- **R1** `v3-R1-rust-backend.md` — Rust module layout, error envelope, `AppState`, DB layer
- **R2** `v3-R2-multi-user-schema.md` — `users` extensions, `user_id` on all scoped tables, backfill SQL
- **R3** `v3-R3-react-frontend.md` — SPA structure, routing, TanStack Query patterns, design tokens
- **R4** `v3-R4-auth-and-security.md` — JWT access/refresh, argon2, CSRF strategy, rate limits
- `docs/plans/00-tech-debt.md` — schema-drift lessons learned; forward-migrations must run through R2 not `turso_patch`
- `docs/plans/README.md` — v2 phase roadmap; v3 does not invalidate v2 features, only re-hosts them
- `render.yaml` (current) — Python service definition to replace with Rust variant in §5

---

_Written 2026-07-19. Companion to R1-R4. Planning-only; no code shipped from this doc directly._
