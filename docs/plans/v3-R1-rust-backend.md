# v3 R1 — Rust Backend Framework + MVC Layout

**Status:** planning only, no code.
**Author:** research agent, 2026-07-19.
**Scope:** pick the Rust web framework, sketch the project layout, wire runtime + error + config + observability + deploy, and produce a route-parity checklist for the R4 API design pass to consume.
**Explicitly out of scope:** the choice of Rust vs Go/Node (settled), the choice of React/TS on the frontend (settled), the specific REST/GraphQL/tRPC contract (R4 owns that), auth-token format details (R2 owns that), migration strategy from Turso (R3 owns that).

---

## 0. TL;DR

- **Framework:** `axum` 0.8. Best fit for solo-dev priorities: type-safe extractors, first-class Tokio, ecosystem depth from the tower/hyper stack, and a hiring pool that already knows it.
- **Runtime:** `tokio` 1.x, multi-threaded scheduler, no work-stealing tuning needed. Turso is remote HTTP so every request is I/O-bound — the default runtime handles it.
- **Errors:** `thiserror` for library-style typed errors inside `models/`, `services/`, `db/`; a single top-level `AppError` enum implementing `axum::response::IntoResponse`. Only `main.rs` may use `anyhow` (for startup).
- **Config:** `figment` with a Serde-typed `Settings` struct, layered `default → env → file → CLI`. Secrets never touch disk.
- **Layout:** MVC-ish, `src/{api,services,models,db,middleware,schemas,config,error}.rs` with `main.rs` as the composition root.
- **Observability:** `tracing` + `tracing-subscriber` with a JSON layer in prod, pretty layer in dev. Every request wrapped in a span via `tower-http::trace::TraceLayer`.
- **Deploy:** Render "web service" with a multi-stage Dockerfile (cargo-chef base → build → distroless-cc runtime). Health check on `/healthz`.
- **Cargo:** ~30 crates pinned; full list in §11.

The single strong opinion in this document is *axum over the alternatives*. The single strong opinion on style is *typed errors flow up, IntoResponse is defined once*. Everything else is a defensible default with reasoning attached.

---

## 1. Framework choice

### 1.1 Candidates evaluated

| Framework | Version | Foundation | Extractor style | Governance | Ecosystem depth | Cold-start LOC |
|---|---|---|---|---|---|---|
| `axum` | 0.8 | tokio + hyper + tower | typed function args | tokio-rs (Amp/Fasterthanlime cohort) | very deep (any tower middleware) | ~15 |
| `actix-web` | 4.x | actix actors + tokio | typed function args | Rust Foundation adoption after 2020 governance episode | deep, own middleware world | ~15 |
| `rocket` | 0.5.1 | tokio (since 0.5) | attribute macros | community, sporadic release cadence | shallow (own guards/fairings) | ~20 |
| `poem` | 3.x | tokio + hyper | typed | small maintainer team | modest | ~15 |

I also considered `warp`, `salvo`, `viz`, `ntex`. Rejected as either abandoned trajectory (`warp` — filter combinators great, but the crate is essentially in maintenance) or too new for a solo dev who can't afford ecosystem gaps (`salvo`, `viz`).

### 1.2 Scoring against the five stated priorities

I score each 1-5 on each priority, then weight the priorities equally. There is no clever weighting scheme; equal weights are honest about the fact that the priorities were listed without a tiebreak rank.

| Priority | axum | actix-web | rocket | poem |
|---|---|---|---|---|
| **1. Low ops burden** — easy to debug in prod, small dep footprint, doesn't panic on weird inputs | 4 (hyper 1.x, tower stack, `IntoResponse` diagnostics are OK, some type-error walls on extractors) | 4 (mature, occasional actor-system corner cases) | 3 (macro-heavy compile errors, longer builds) | 3 (smaller community = more debugging alone) |
| **2. Type safety** — extractors, response codecs, compile-time route checking | 5 (typed extractors, `#[debug_handler]`, State pattern, everything is a `Result`) | 4 (typed, but request data is often accessed by `.into_inner()`) | 4 (macros infer types, but the sugar hides errors) | 5 (matches axum for extractor typing) |
| **3. Speed** — for our workload (Turso HTTP round-trips dominate; framework overhead is noise) | 5 (top of most benches; but we don't care past ~10K rps) | 5 (typically slightly faster than axum on TFB benches) | 3 (slower, but again we don't care) | 4 |
| **4. Ecosystem maturity** — middleware, integrations, book/docs, StackOverflow answers | 5 (any `tower::Service` middleware works; `tower-http` is huge; `axum::extract::State` is well-documented) | 4 (its own middleware world; some crates are actix-only) | 3 (fewer integrations, own async ecosystem) | 3 |
| **5. Ease of hiring/collab later** — how many Rust devs already know it | 5 (axum is the default recommendation in most 2025+ tutorials, YouTube, blog posts) | 4 (older devs know actix; newer devs less so) | 3 (few new projects pick Rocket) | 2 |
| **Total /25** | **24** | 21 | 16 | 17 |

### 1.3 Recommendation: **axum 0.8**

Reasoning beyond the scorecard:

1. **The tower ecosystem is the moat.** `axum` is thin — it's really "hyper + tower + a nice extractor DSL." Every `tower::Service<Request>` middleware works: `tower-http::trace::TraceLayer`, `tower-http::cors::CorsLayer`, `tower-http::compression::CompressionLayer`, `tower::limit::RateLimitLayer`, `tower_governor` for per-IP throttling, `tower-sessions` for optional session cookies. This means when we hit a wall (say, wanting `Retry-After` on 429), the fix is a 5-line middleware, not a fork.
2. **State pattern beats globals.** `axum::extract::State<AppState>` is a typed handle to shared state (DB pool, config, HTTP client). Cleaner than actix's `web::Data<T>` or global `once_cell` cells because it participates in the type system — a handler that forgets to declare `State<Db>` fails at compile time.
3. **Solo-dev cost of switching later is low.** `axum` handlers are `async fn` returning `impl IntoResponse`. Migrating a handler to `actix` later means renaming the extractor imports; the domain logic in `services/` doesn't move. This is not true of Rocket (macro-first) or actor-based systems.
4. **Actix's 2020 governance incident is genuinely in the past** but a solo dev with limited attention should not have to re-litigate that context every time a new contributor asks. Axum has none of that history.

### 1.4 Version pin

`axum = "0.8"`. Pin the minor version in `Cargo.toml`; take patch upgrades on `cargo update`. 0.8 is the latest stable line, has stable `matchit` routing, and its breaking-change velocity has slowed since 0.7.

---

## 2. Async runtime

### 2.1 Tokio version + features

```
tokio = { version = "1.40", features = ["macros", "rt-multi-thread", "signal", "time", "sync", "fs"] }
```

- `rt-multi-thread` — default work-stealing scheduler. On a Render standard instance we have 0.5 vCPU baseline / 2 vCPU burst; the multi-thread scheduler saturates that better than `current-thread`. We do *not* pin thread count; `TOKIO_WORKER_THREADS` env var can override later if we ever move to a small VM.
- `macros` — `#[tokio::main]` in `main.rs`.
- `signal` — graceful shutdown on SIGTERM (Render sends SIGTERM before killing the container; we want inflight requests to drain).
- `time` — timeouts on HTTP calls to Turso, Gemini, Anthropic.
- `sync` — `tokio::sync::{Mutex, RwLock, mpsc}` when we need cross-task state (e.g. rate-limit token buckets).
- `fs` — reading study-notes markdown at boot.

Do **not** enable `net` and `io-util` explicitly — `rt-multi-thread` pulls them in.

### 2.2 Threading model

- Handlers are `async fn`. All I/O (Turso HTTP calls, LLM HTTP calls, filesystem) uses `.await`.
- CPU-bound work (PDF parsing, dedupe trigrams over 3,712 rows, FTS5 reindex if we ever recompute) goes through `tokio::task::spawn_blocking`. As a rule: any function that takes >5 ms of CPU without `.await` should be moved. In our current Flask code the offenders are `_find_duplicate_pairs` (nested loop over trigrams) and PDF text extraction — port them under `spawn_blocking`.
- Never `std::thread::sleep` inside an async context. Use `tokio::time::sleep`. Enforced by `clippy::disallowed_methods` in `clippy.toml`.

### 2.3 Task budget for Turso HTTP

Turso's `libsql` Rust client (or the raw `hrana` HTTP protocol) is entirely I/O. A typical request-serving flow issues 3-8 SQL statements. Two implications:

1. **Connection pooling.** libSQL's HTTP transport is stateless from the client's perspective — there's no persistent socket like Postgres. We keep a single `reqwest::Client` behind an `Arc` in `AppState`; `reqwest`'s built-in pool handles keep-alive. No `deadpool`/`bb8` needed.
2. **Timeouts.** Every outbound HTTP call gets a `tokio::time::timeout(Duration::from_secs(10), ...)`. Turso's typical latency from India to `aws-ap-south-1` is 20-80 ms; 10 s is a safety net, not a target.
3. **Concurrency ceiling.** No hard limit initially — Turso free tier caps at 500 req/s and Render's free instance can't drive that. If we ever add multi-user, revisit with `tower::limit::ConcurrencyLimitLayer` on the *outbound* HTTP client.

### 2.4 Cancellation

Every request has a cancellation token via axum's request extensions. If the client disconnects mid-flight (mobile user backs out of a Deep Dive query), the Gemini call must be cancellable. `reqwest` supports this out of the box when the future is dropped. Verify by writing an integration test that drops a handler mid-request and asserts the outbound call's socket is torn down.

---

## 3. MVC project layout

```
backend/
├── Cargo.toml
├── Cargo.lock
├── clippy.toml            # lint config: warn on TODO, deny disallowed_methods
├── rustfmt.toml           # imports_granularity=crate, group_imports=StdExternalCrate
├── Dockerfile             # multi-stage, distroless
├── .dockerignore
├── .env.example           # every env var listed in §5.2 with a comment
├── migrations/            # SQL migrations (see R3 for full plan)
│   └── 20260720_0001_baseline.sql
└── src/
    ├── main.rs            # composition root: parse config, build router, run
    ├── lib.rs             # re-exports for integration tests
    ├── config.rs          # figment + Settings struct
    ├── error.rs           # AppError enum + IntoResponse
    ├── state.rs           # AppState (holds Db, Config, Http client, LLM clients)
    ├── telemetry.rs       # tracing subscriber setup, JSON in prod, pretty in dev
    ├── shutdown.rs        # SIGTERM + Ctrl-C signal handling
    │
    ├── db/                # M — Turso client, migrations, connection helpers
    │   ├── mod.rs         # Db newtype wrapping libsql::Connection
    │   ├── migrate.rs     # run migrations at startup
    │   ├── questions.rs   # question queries (fetch, filter, disable, FTS5 search)
    │   ├── tests.rs       # mock_tests + test_responses queries
    │   ├── error_log.rs   # error_log queries incl. SRS due
    │   ├── mastery.rs     # topic_mastery queries
    │   ├── bookmarks.rs
    │   ├── flags.rs
    │   ├── users.rs
    │   ├── pdf_uploads.rs
    │   └── settings.rs
    │
    ├── models/            # M — pure Rust structs mirroring schema + domain logic
    │   ├── mod.rs
    │   ├── question.rs    # struct Question { id, topic_id, question_text, ... }
    │   ├── test.rs        # MockTest, TestResponse, TestMode enum (Practice|Exam)
    │   ├── error_log.rs   # ErrorLogEntry
    │   ├── topic.rs
    │   ├── mastery.rs
    │   ├── bookmark.rs
    │   ├── flag.rs        # FlagCategory enum (7 variants matching current whitelist)
    │   ├── user.rs        # User, Role (User|Admin)
    │   ├── sr.rs          # Leitner-5 logic: next_box, next_due, box intervals
    │   ├── scoring.rs     # score computation with neg_marking
    │   ├── consistency.rs # 28-day rolling window
    │   └── dedupe.rs      # trigram similarity
    │
    ├── schemas/           # request/response DTOs, all `#[derive(Serialize/Deserialize)]`
    │   ├── mod.rs
    │   ├── auth.rs        # LoginRequest, LoginResponse, SignupRequest
    │   ├── tests.rs       # StartTestRequest, SubmitAnswerRequest, TestResultResponse
    │   ├── analytics.rs   # MasteryTile, HeatmapCell, PacingRow
    │   ├── review.rs      # ReviewCard, ReviewAnswerRequest
    │   ├── flags.rs
    │   ├── bookmarks.rs
    │   ├── admin.rs       # QuestionCreate, QuestionUpdate, TopicCreate, UserUpdate
    │   ├── doubt.rs       # DeepDiveRequest, DeepDiveResponse, ChatRequest
    │   ├── search.rs
    │   └── common.rs      # Pagination, ApiError shape
    │
    ├── api/               # C — HTTP handlers grouped by resource
    │   ├── mod.rs         # `pub fn router() -> Router<AppState>` — composes all sub-routers
    │   ├── auth.rs        # POST /auth/login, POST /auth/signup, POST /auth/logout
    │   ├── health.rs      # GET /healthz, GET /readyz
    │   ├── tests.rs       # POST /tests, GET /tests/:id, POST /tests/:id/answer, POST /tests/:id/finish
    │   ├── questions.rs   # GET /questions, GET /questions/:id
    │   ├── analytics.rs   # GET /analytics, GET /analytics/mastery, GET /analytics/heatmap
    │   ├── errorlog.rs    # GET /errorlog
    │   ├── review.rs      # GET /review, POST /review/:error_id/answer
    │   ├── bookmarks.rs   # GET /bookmarks, POST /bookmarks/:qid, DELETE /bookmarks/:qid
    │   ├── flags.rs       # POST /flags
    │   ├── search.rs      # GET /search
    │   ├── doubt.rs       # POST /doubt/deep-dive, POST /doubt/chat
    │   └── admin/         # C — admin surface, mounted at /admin/api
    │       ├── mod.rs
    │       ├── dashboard.rs
    │       ├── questions.rs   # CRUD + toggle_disabled + delete
    │       ├── topics.rs
    │       ├── users.rs
    │       ├── flags.rs
    │       ├── review.rs      # confidence-review queue
    │       ├── duplicates.rs
    │       ├── synthesize.rs
    │       ├── uploads.rs     # PDF upload + Claude extraction
    │       └── prompts.rs
    │
    ├── services/          # business logic between C and M
    │   ├── mod.rs
    │   ├── auth.rs        # sign token, verify token, hash pw, verify pw
    │   ├── tests.rs       # build_test_question_set, finalize_test_score
    │   ├── sr.rs          # record_review wrapper (calls models::sr + db::error_log)
    │   ├── analytics.rs   # composes mastery tiles + heatmap + consistency
    │   ├── dedupe.rs      # runs trigram scan in spawn_blocking
    │   ├── search.rs      # FTS5 query builder + LIKE fallback
    │   ├── llm/           # LLM provider clients
    │   │   ├── mod.rs     # trait LlmClient { async fn complete(&self, prompt) -> Result<String> }
    │   │   ├── gemini.rs  # REST implementation of LlmClient
    │   │   ├── anthropic.rs
    │   │   └── mock.rs    # for tests
    │   ├── pdf.rs         # PDF → text (spawn_blocking around pdf-extract crate)
    │   └── doubt.rs       # deep-dive orchestration: notes lookup + prompt + LLM + parse
    │
    ├── middleware/        # cross-cutting concerns as tower layers
    │   ├── mod.rs
    │   ├── auth.rs        # extract Bearer/cookie JWT, populate `AuthUser` extension
    │   ├── require_admin.rs
    │   ├── request_id.rs  # X-Request-Id in + out, into tracing span
    │   ├── rate_limit.rs  # tower_governor per-IP for /auth/*
    │   └── errors.rs      # convert panics → 500 via CatchPanicLayer
    │
    └── util/              # tiny helpers with no HTTP dependencies
        ├── mod.rs
        ├── time.rs        # ISO-8601 helpers, "days since"
        └── ids.rs         # short uuid for error_id in doubt handler
```

### 3.1 Layer responsibilities in one line each

- **`api/`** — parse the HTTP request into a schema DTO, call one service function, format the response. **No SQL. No business logic.** If a handler has more than ~30 lines, the logic belongs in `services/`.
- **`services/`** — orchestrate models + db. Cross-table logic. LLM calls. Anything that would end up as an integration test.
- **`models/`** — pure structs + pure functions. Testable with zero dependencies. `sr.rs`'s Leitner math lives here. `scoring.rs`'s neg-marking math lives here.
- **`db/`** — every SQL statement. Nothing else. Functions take `&Db` (or `&mut Tx`) and typed args, return typed rows.
- **`schemas/`** — DTOs for the wire format only. Never used as domain types — they exist so we can change the wire format without touching `models/`.
- **`middleware/`** — Tower layers that touch every request or a whole subrouter.

### 3.2 Why MVC, not hexagonal / clean-architecture

For a solo dev with 3-4h evenings, MVC is legible: "if I want to know how login works, I open `api/auth.rs` and follow the imports." Hexagonal architecture with ports/adapters/domain layers doubles the file count for the same behaviour, which pays off only when a team is scaling handlers concurrently. Not our situation.

We do borrow one hexagonal idea: **LLM clients behind a trait (`LlmClient`) in `services/llm/`**, so tests can swap in `services/llm/mock.rs`. This isolation is the only place the abstraction earns its cost.

### 3.3 Cross-cutting: `AppState`

```
pub struct AppState {
    pub db: Db,                    // libsql::Connection wrapper
    pub config: Arc<Settings>,     // parsed at boot, immutable
    pub http: reqwest::Client,     // one shared connection pool
    pub llm: Arc<dyn LlmClient>,   // trait object for testability
    pub jwt_keys: JwtKeys,         // encoding + decoding keys, prebuilt
}
```

Injected into handlers via `State(state): State<AppState>`. Cloning `AppState` is cheap (all fields are `Arc`).

---

## 4. Error handling

### 4.1 Strong opinion

**`thiserror` in libraries, `anyhow` only in `main.rs`, one `AppError` at the top.**

- `thiserror` gives us typed errors that carry enough structure to map cleanly to HTTP responses. It's a proc-macro, zero runtime cost.
- `anyhow` is for prototyping and one-shot binaries; it erases type information. We tolerate it exactly in `main.rs` where we do "load config or die."
- Never `unwrap()` outside tests. Configured via `#![warn(clippy::unwrap_used, clippy::expect_used)]` at the crate root.

### 4.2 Error variant hierarchy

Sub-crates or modules define their own `thiserror` enums when it's useful (e.g. `db::DbError`, `services::llm::LlmError`), and `AppError` has `#[from]` conversions from each.

```
// error.rs
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    // 400 — client sent something we can't parse or that violates a constraint
    #[error("bad request: {0}")]
    BadRequest(String),
    #[error(transparent)]
    Validation(#[from] validator::ValidationErrors),

    // 401 / 403 — auth
    #[error("unauthorized")]
    Unauthorized,
    #[error("forbidden")]
    Forbidden,

    // 404
    #[error("not found: {0}")]
    NotFound(&'static str),

    // 409 — conflict, e.g. username taken, duplicate flag
    #[error("conflict: {0}")]
    Conflict(String),

    // 429 — rate limit (from tower_governor)
    #[error("too many requests")]
    RateLimited,

    // 500 — internal, wrapping db / io / json / anyhow
    #[error(transparent)]
    Db(#[from] crate::db::DbError),
    #[error(transparent)]
    Llm(#[from] crate::services::llm::LlmError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("internal: {0}")]
    Internal(String),

    // 502 — upstream (LLM providers, Turso if we surface it distinct from Db)
    #[error("upstream unavailable: {0}")]
    Upstream(String),
}
```

### 4.3 `IntoResponse` mapping

Implemented once in `error.rs`. Rough shape:

- `BadRequest`, `Validation` → **400** with `{ error: "...", details: [...] }`.
- `Unauthorized` → **401** with `WWW-Authenticate: Bearer`, body `{ error: "unauthorized" }`.
- `Forbidden` → **403**.
- `NotFound(what)` → **404** with `{ error: "not found", resource: what }`.
- `Conflict` → **409**.
- `RateLimited` → **429** with `Retry-After` (populated by the layer).
- `Db`, `Io`, `Internal`, `Json` → **500**. Logged with full backtrace at `tracing::error` **before** the body is written. Body reveals only `{ error: "internal", request_id: "..." }` — never the exception detail (mirrors the Flask `_friendly_ai_error` pattern in `bp_doubt.py`).
- `Llm`, `Upstream` → **502** with `{ error: "upstream unavailable", request_id: "..." }`.

### 4.4 Handler ergonomics

Every handler signature: `async fn foo(...) -> Result<Json<T>, AppError>`. `?` propagates freely. We rarely write manual conversions — `#[from]` does it.

### 4.5 Panic policy

`tower_http::catch_panic::CatchPanicLayer` catches panics, logs them, returns 500 with a fresh request_id. We do not fatal the server on a handler panic. Panics anywhere else in the code (task spawns, background jobs) *should* be fatal — surface them at boot rather than silently.

---

## 5. Config management

### 5.1 Library choice: `figment`

Considered `envy` (env-only), `config` (layered but Serde-clunky), `figment` (multiple sources, typed).

Recommendation: **`figment`** with a `Serialize + Deserialize` `Settings` struct. Reasons:

- Serde-first — the config type is just a Rust struct, tests are easy.
- Sources compose: default in code → `config.toml` (dev only) → env vars → CLI flags (via `clap`).
- Well-maintained by the Rocket authors, but no Rocket dependency.

If a solo dev pushes back on figment's slightly heavier API, the second choice is `envy` + a hand-written `merge`. But figment pays for itself once you have >6 knobs, and we have >12.

### 5.2 The `Settings` struct

Every env var used by the current Flask app, translated:

```
pub struct Settings {
    pub environment: Environment,           // Dev | Prod, from RENDER
    pub bind_addr: SocketAddr,              // BIND_ADDR default 0.0.0.0:10000
    pub public_base_url: Url,               // PUBLIC_BASE_URL for magic-link tokens later

    pub database: DatabaseSettings,
    pub auth: AuthSettings,
    pub llm: LlmSettings,
    pub logging: LoggingSettings,
    pub admin_seed: Option<AdminSeed>,      // EXAM_ADMIN_USER + EXAM_ADMIN_PASS
}

pub struct DatabaseSettings {
    pub url: Url,                           // TURSO_DB_URL
    pub auth_token: SecretString,           // TURSO_AUTH_TOKEN (redacted in Debug)
    pub timeout_secs: u64,                  // TURSO_TIMEOUT_SECS default 10
}

pub struct AuthSettings {
    pub jwt_secret: SecretString,           // JWT_SECRET
    pub jwt_expiry_hours: u32,              // JWT_EXPIRY_HOURS default 24
    pub cookie_secure: bool,                // COOKIE_SECURE default true in prod
    pub cookie_name: String,                // "auth_token"
}

pub struct LlmSettings {
    pub gemini_api_key: Option<SecretString>,     // GEMINI_API_KEY
    pub gemini_model: String,                     // GEMINI_MODEL default gemini-2.5-flash
    pub anthropic_api_key: Option<SecretString>,  // ANTHROPIC_API_KEY
    pub anthropic_model: String,                  // default claude-sonnet-4-6
    pub deepseek_api_key: Option<SecretString>,   // DEEPSEEK_API_KEY (reserved, unused today)
    pub deepseek_base_url: Option<Url>,           // DEEPSEEK_BASE_URL (reserved)
    pub glm_api_key: Option<SecretString>,        // GLM_API_KEY (reserved)
    pub request_timeout_secs: u64,                // LLM_TIMEOUT_SECS default 45
}

pub struct LoggingSettings {
    pub level: String,                      // RUST_LOG / LOG_LEVEL, default "info,exam=debug"
    pub format: LogFormat,                  // Json | Pretty. Json in prod, Pretty in dev.
}

pub struct AdminSeed {
    pub username: String,
    pub password: SecretString,
}
```

### 5.3 Secrets

- Wrap every secret in `secrecy::SecretString`. `Debug` and `Display` return `[REDACTED]`. Only `.expose_secret()` returns the raw value.
- The tracing subscriber redacts any span field named `password`, `token`, `secret`, `api_key` via a custom `Filter` layer.
- `Settings::default()` **must not** compile without `SecretString`s — that's how we make sure a stray `println!(settings)` never leaks.

### 5.4 Layering + precedence

```
default (compile-time)  <   config.toml (dev only)  <   environment vars   <   CLI flags
```

Prod on Render sets env vars; there is no `config.toml` in the container. Dev on laptop uses `.env` (via `dotenvy`) so `cargo run` picks up `TURSO_AUTH_TOKEN=...`. `.env` is gitignored; `.env.example` is checked in.

### 5.5 Fail-fast

`Settings::load()` returns `Result<Settings, ConfigError>`. `main.rs` bubbles that up with `anyhow` and prints a human error before exiting with code 2 when required prod fields are missing (mirrors `_fill_secret_fallbacks` in the current `app.py`).

---

## 6. Testing strategy

### 6.1 Unit tests (models/, services/)

- Colocated in `#[cfg(test)] mod tests { ... }` blocks.
- Pure-Rust, no DB. Every function in `models/sr.rs`, `models/scoring.rs`, `models/consistency.rs`, `models/dedupe.rs` gets tests for happy path + edge cases (already documented in the plan A/B/C/D critic reports — we mine those for test cases).
- Target: **100 % coverage for `models/`.**

### 6.2 Integration tests (`tests/`)

- Live in `tests/` at the crate root, one file per feature slice: `tests/auth.rs`, `tests/tests_flow.rs`, `tests/review.rs`, `tests/admin.rs`.
- Boot an in-memory DB (`sqlite::memory:` via the libsql crate's local mode) and a Router, drive HTTP with `axum::body::Body` + `tower::ServiceExt::oneshot`.
- Do **not** boot a real Turso instance in unit CI. That is R3's problem (schema parity between local sqlite and Turso).
- LLM calls go through `services::llm::mock::MockLlm` — configurable canned responses.

### 6.3 Ephemeral Turso in staging tests (optional, later)

Turso has a "dev DB" you can spin up in seconds via `turso db create`. A separate `cargo test --features turso-live` target could point at that, guarded so it never runs in CI without a token. **Not required for R1.** Flag as future work.

### 6.4 Test framework choice

**Default: built-in `#[test]` + `#[tokio::test]`.** No `rstest` or `test-context` unless we outgrow the built-ins.

- **Assertions:** `assert_eq!` and `assert!` are fine. Add `pretty_assertions` as a dev-dep if diffs get unreadable for larger structs.
- **HTTP asserts:** hand-rolled helpers in `tests/support/` — a `TestApp` builder that gives back `(router, state)` and a `post_json` / `get` helper. Don't pull in `axum-test` yet; it moves fast and adds a dependency for saving ~10 lines.

### 6.5 CI (GitHub Actions)

`.github/workflows/ci.yaml`, three jobs, each with `Swatinem/rust-cache`:

1. **fmt + clippy** — `cargo fmt --check` and `cargo clippy --all-targets -- -D warnings`. Fastest, fails first.
2. **unit + integration** — `cargo test --all-features` on `ubuntu-latest`, `stable`. Add `1.83` (MSRV) later if we care.
3. **docker build** — verify the multi-stage Dockerfile still builds, push image on `main` (see §8.3).

Add `cargo audit` on a nightly schedule (not per-commit — noisy).

---

## 7. Logging + observability

### 7.1 Crate: `tracing` + `tracing-subscriber`

Reasoning: `tracing` is the de-facto async-aware logging in Rust 2024+. `log` still exists as the lowest common denominator; `tracing` bridges it via `tracing-log`. Anything more (OpenTelemetry, Honeycomb) is future work.

### 7.2 Setup

`telemetry.rs::init(settings: &LoggingSettings)` builds a subscriber:

- **Env filter** — reads `RUST_LOG` and falls back to `settings.level`. Default `info,exam_prep=debug,tower_http=info,sqlx=warn`.
- **Format layer** — `tracing_subscriber::fmt`:
  - Pretty (ANSI, single line per event) in dev.
  - JSON (`.json().flatten_event(true)`) in prod. One JSON object per line so Render's log viewer parses it. Timestamps are RFC 3339 UTC.
- **Span layer** — `.with_current_span(true).with_span_list(true)` so nested spans (request → handler → db call) survive to the output.

### 7.3 Per-request span

`tower_http::trace::TraceLayer::new_for_http()` with a custom `make_span_with`. Every request opens a span named `http_request` with fields:
- `request_id` (from `X-Request-Id` header if present, else generated)
- `method`
- `uri`
- `user` (populated by the auth middleware after JWT verify)
- `status` (populated when the response finishes)
- `latency_ms`

Every log line inside the handler inherits those fields — no need to pass them explicitly.

### 7.4 Sensitive-field policy

Do not log request bodies. Do not log JWTs. Do not log Turso auth tokens. Enforced by:
- `SecretString::Debug` returning `[REDACTED]`.
- A skiplist in the JSON formatter for keys `password`, `token`, `secret`, `api_key`, `authorization`.

### 7.5 Metrics (future work, mention only)

Add `metrics` + `metrics-exporter-prometheus` and expose `/metrics` when we outgrow tracing-only observability. Not needed for MVP.

---

## 8. Deployment on Render

### 8.1 Service type

Render calls this a **"Web Service"**, environment = `docker`. We ship a Dockerfile from the repo; Render builds and deploys it.

### 8.2 Dockerfile pattern (multi-stage, ~35 lines)

```
# ---- Stage 1: recipe (dependency-only) ----
FROM lukemathwalker/cargo-chef:0.1-rust-1.83-slim AS chef
WORKDIR /app

FROM chef AS planner
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo chef prepare --recipe-path recipe.json

# ---- Stage 2: build ----
FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY migrations ./migrations
RUN cargo build --release --locked --bin exam-prep-backend

# ---- Stage 3: runtime (distroless-cc for openssl / reqwest) ----
FROM gcr.io/distroless/cc-debian12:nonroot
WORKDIR /app
COPY --from=builder /app/target/release/exam-prep-backend /app/exam-prep-backend
COPY --from=builder /app/migrations /app/migrations
USER nonroot
EXPOSE 10000
ENV RUST_LOG=info,exam_prep=debug
ENV BIND_ADDR=0.0.0.0:10000
ENTRYPOINT ["/app/exam-prep-backend"]
```

Notes:

- **`cargo-chef`** — caches dependency compilation. Rebuilding after a source-only change should take <60 s; today's Flask deploy on Render finishes in ~90 s so this is comparable.
- **`distroless/cc`**, not `distroless/static`, because `reqwest` needs libc + OpenSSL. If we swap `reqwest` to `rustls`-only (`reqwest = { default-features = false, features = ["rustls-tls", "json"] }`) we can move to `distroless/static` and save ~50 MB. Do this optimization only after the first prod deploy is green.
- **`nonroot`** user is built-in to distroless.
- **`--locked`** so Cargo refuses to update deps at build time.

### 8.3 `render.yaml` update (sketch, not code)

Same `envVars` list as today, with `env: docker` and `dockerfilePath: ./Dockerfile`. Health check is `path: /healthz`, interval 30 s. The `startCommand`/`buildCommand` fields go away.

### 8.4 Graceful shutdown

`axum::serve(...).with_graceful_shutdown(shutdown_signal)` where `shutdown_signal` awaits either SIGTERM or Ctrl-C. On signal, the server stops accepting new connections and waits up to 25 s for in-flight requests. Render's default kill timeout is 30 s, so 25 s leaves a safety margin.

### 8.5 Migrations at boot

`main.rs` calls `db::migrate::run_migrations(&db)` before `axum::serve`. Migrations are numbered SQL files in `migrations/`, applied in filename order, tracked in a `_migrations` table. First migration is the current schema materialized from `db.py` SCHEMA + all `_run_alter_migrations`. See R3 for the migration strategy in full.

---

## 9. Feature parity checklist

Every route in the current Flask app, with a "Included in v3?" flag and a note. This is the input to R4 (API design). Grouping matches the Rust `api/` module layout above so R4 can copy-paste this table into the API doc.

Legend: **Y** = ship in v3 MVP. **Y*** = ship, but shape changes (see note). **N** = drop, note reason.

### 9.1 Auth (`bp_auth.py`, `auth.py`)

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/login` (GET) | GET | — | N | React app handles the form; only the API endpoint remains. |
| `/login` (POST) | POST | `POST /auth/login` | Y* | Returns JWT in body + as `HttpOnly` cookie. Signup route is new. |
| `/logout` | GET | `POST /auth/logout` | Y* | Was GET; becomes POST for CSRF hygiene. Clears cookie. |
| — | — | `POST /auth/signup` | Y (new) | Multi-user requirement. |
| — | — | `GET /auth/me` | Y (new) | Returns current user for the SPA. |
| `before_request check_auth` | — | `middleware/auth.rs` | Y | Same intent, now a tower layer. |

### 9.2 Main / dashboard (`bp_main.py`)

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/` (dashboard) | GET | `GET /analytics/dashboard` | Y* | Splits into JSON endpoints consumed by SPA home. |
| `/bookmarks` | GET | `GET /bookmarks` | Y | Returns paginated list. |
| `/search` | GET | — | N | Server-rendered page; SPA owns rendering. |
| `/api/search` | GET | `GET /search?q=...` | Y | FTS5 + LIKE fallback. |

### 9.3 Tests (`bp_tests.py`)

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/test/setup` (GET) | GET | `GET /tests/setup-options` | Y* | Returns topics, papers, defaults for the setup form. |
| `/test/setup` (POST) | POST | `POST /tests` | Y* | Creates a `mock_tests` row, returns test id + question set. |
| `/test/take` | GET | `GET /tests/:id` | Y* | Returns the test config + question ids (question payload fetched by `/questions/:id`). |
| `/test/finish` | POST | `POST /tests/:id/finish` | Y | Same behaviour, JSON response now. |
| `/results/:test_id` | GET | `GET /tests/:id/results` | Y | |

### 9.4 API (`bp_api.py`)

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/api/flag_question` | POST | `POST /flags` | Y | Same 7-category whitelist. |
| `/api/question/:idx` | GET | `GET /tests/:id/questions/:idx` | Y* | Was session-based; now takes test id explicitly (SPA is stateless). |
| `/api/mark_for_review` | POST | `POST /tests/:id/mark-review` | Y | |
| `/api/submit_answer` | POST | `POST /tests/:id/answer` | Y | Body `{question_id, selected, time_spent_sec, confidence, marked_for_review}` |
| `/api/resolve_error` | POST | `POST /errorlog/:id/resolve` | Y | |
| `/api/redo_error` | POST | `POST /errorlog/:id/redo` | Y | |
| `/api/settings` | POST | `PATCH /settings` | Y* | RESTful verb. |
| `/api/bookmark/:qid` | POST | `POST /bookmarks/:qid` + `DELETE /bookmarks/:qid` | Y* | Split into two verbs. |
| `/api/study_session` | POST | `POST /study-sessions` | Y | |

### 9.5 Analytics (`bp_analytics.py`)

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/analytics` | GET | `GET /analytics` (composite) or split into `mastery`, `heatmap`, `pacing`, `consistency` | Y* | R4 picks composite vs split. |

### 9.6 Error log (`bp_errorlog.py`)

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/errorlog` | GET | `GET /errorlog` | Y | |

### 9.7 Review / SRS (`bp_review.py`)

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/review` | GET | `GET /review/due` | Y* | Returns due cards + queue summary. |
| `/api/review_answer` | POST | `POST /review/:error_id/answer` | Y | |

### 9.8 Doubt / AI (`bp_doubt.py`)

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/api/doubt/deep-dive` | POST | `POST /doubt/deep-dive` | Y | LLM behind trait; cache table unchanged. |
| `/api/doubt/chat` | POST | `POST /doubt/chat` | Y | |

### 9.9 Admin (`bp_admin.py`)

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/admin/` | GET | `GET /admin/api/dashboard` | Y* | React admin panel. |
| `/admin/flags` | GET | `GET /admin/api/flags` | Y | |
| `/admin/api/flag/:id/:action` | POST | `POST /admin/api/flags/:id/:action` | Y | |
| `/admin/review` | GET | `GET /admin/api/review-queue` | Y | |
| `/admin/api/review/:qid/:action` | POST | `POST /admin/api/questions/:qid/review/:action` | Y | |
| `/admin/duplicates` | GET | `GET /admin/api/duplicates` | Y | |
| `/admin/api/duplicate/disable/:qid` | POST | `POST /admin/api/questions/:qid/disable` | Y* | Consolidates with the generic disable endpoint. |
| `/admin/synthesize` | GET | `GET /admin/api/synthesize` | Y | |
| `/admin/api/synthesize/preview` | POST | `POST /admin/api/synthesize/batches` | Y* | Preview → create batch. |
| `/admin/synthesize/:id/preview` | GET | `GET /admin/api/synthesize/batches/:id` | Y | |
| `/admin/synthesize/:id/commit` | POST | `POST /admin/api/synthesize/batches/:id/commit` | Y | |
| `/admin/questions` | GET | `GET /admin/api/questions` | Y | Paginated. |
| `/admin/questions/:qid/edit` | GET/POST | `GET/PATCH /admin/api/questions/:qid` | Y* | RESTful. |
| `/admin/api/question/:qid/toggle_disabled` | POST | `POST /admin/api/questions/:qid/toggle-disabled` | Y | |
| `/admin/api/question/:qid/delete` | POST | `DELETE /admin/api/questions/:qid` | Y* | Verb switch. |
| `/admin/topics` | GET/POST | `GET/POST /admin/api/topics` | Y | |
| `/admin/topics/:tid/delete` | POST | `DELETE /admin/api/topics/:tid` | Y* | |
| `/admin/users` | GET/POST | `GET/POST /admin/api/users` | Y | |
| `/admin/users/:uid/update` | POST | `PATCH /admin/api/users/:uid` | Y* | |
| `/admin/uploads` | GET/POST | `GET/POST /admin/api/uploads` | Y | Multipart body; Claude extraction fires as a background job. |
| `/admin/uploads/:id/preview` | GET | `GET /admin/api/uploads/:id/preview` | Y | |
| `/admin/uploads/:id/import` | POST | `POST /admin/api/uploads/:id/import` | Y | |
| `/admin/prompts` | GET/POST | `GET/POST /admin/api/prompts` | Y | |

### 9.10 Diag (`bp_diag.py`) — currently disabled

| Flask route | Verb | v3 Rust route | v3? | Notes |
|---|---|---|---|---|
| `/diag/:token` | GET | — | N | Design flaw (URL-token auth). Replaced by `GET /healthz` + `GET /readyz` (no auth needed; return no sensitive info). |
| `/setup/seed/:token` | POST | — | N | Admin seed is a CLI subcommand in v3: `exam-prep-backend seed-admin --username ... --password ...`. |

### 9.11 New in v3

| Route | Verb | v3? | Notes |
|---|---|---|---|
| `/healthz` | GET | Y | Liveness. No auth. |
| `/readyz` | GET | Y | Readiness — Turso reachable + migrations applied. No auth. |
| `/auth/signup` | POST | Y | Multi-user. |
| `/auth/me` | GET | Y | SPA needs current user. |

**Count:** 46 existing routes surveyed. 44 kept (many with verb/path adjustments per REST conventions), 2 dropped (both from the disabled `bp_diag.py`), 4 new. R4 finalizes the exact JSON shapes.

---

## 10. Non-goals for this document

Called out to prevent scope creep in review:

- **Auth details** — JWT rotation, refresh tokens, magic-link login, OAuth. R2 owns these.
- **DB migration plan** — how we move from sqlite-over-libsql-HTTP to a proper migrations pipeline, whether we drop sqlite pragmas at build time. R3 owns this.
- **REST vs GraphQL vs tRPC** — R4.
- **Frontend** — R5.
- **Rollout** — R6 (blue/green vs cutover, subdomain vs path, DNS).

---

## 11. Cargo dependency list (recommended versions)

Pinned to the minor version. Bump inside minors freely via `cargo update`; treat minor bumps as intentional PRs.

```
# --- runtime + framework ---
tokio          = { version = "1.40", features = ["macros", "rt-multi-thread", "signal", "time", "sync", "fs"] }
axum           = { version = "0.8",  features = ["macros", "http2", "multipart"] }
tower          = { version = "0.5",  features = ["util", "timeout", "limit"] }
tower-http     = { version = "0.6",  features = ["trace", "cors", "compression-gzip", "catch-panic", "request-id"] }
hyper          = { version = "1.5" }
tower_governor = "0.4"                     # per-IP rate limit on /auth/*

# --- database ---
libsql         = { version = "0.6",  features = ["remote"] }   # official Turso Rust client
# alternative: sqlx = { version = "0.8", features = ["sqlite", "runtime-tokio-rustls"] } if we swap Turso for local sqlite in tests. R3 decides.

# --- serialization ---
serde          = { version = "1",    features = ["derive"] }
serde_json     = "1"
serde_with     = "3"                       # #[serde_as] helpers for datetimes etc.
validator      = { version = "0.18", features = ["derive"] }

# --- errors ---
thiserror      = "1"
anyhow         = "1"                       # main.rs only

# --- config + secrets ---
figment        = { version = "0.10", features = ["env", "toml"] }
dotenvy        = "0.15"
secrecy        = "0.10"

# --- auth ---
jsonwebtoken   = "9"
argon2         = "0.5"                     # password hashing; upgrades from werkzeug's pbkdf2

# --- http client (for Turso + LLMs) ---
reqwest        = { version = "0.12", default-features = false, features = ["json", "rustls-tls", "gzip", "http2"] }
url            = "2"

# --- observability ---
tracing            = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter", "json", "fmt"] }

# --- utilities ---
uuid           = { version = "1",    features = ["v4", "fast-rng"] }
chrono         = { version = "0.4",  features = ["serde"] }
time           = { version = "0.3",  features = ["serde", "macros"] }
async-trait    = "0.1"                     # for LlmClient trait
once_cell      = "1"                       # for lazy_static constants

# --- PDF extraction ---
pdf-extract    = "0.7"                     # used inside spawn_blocking

# --- dev-dependencies (below [dev-dependencies] in Cargo.toml) ---
pretty_assertions = "1"
tempfile          = "3"
insta             = { version = "1", features = ["yaml"] }    # snapshot tests, optional
```

Notes on omitted crates people might expect:

- **No `sea-orm`, `diesel`, or `sqlx`-for-Turso.** libSQL has its own client and query builder; adding an ORM on top costs compile time and adds a layer nobody on the team knows better than raw SQL. If we ever regret this, migrate one module at a time.
- **No `utoipa` / `okapi`.** OpenAPI generation is future work; the SPA and backend live in the same repo so a typed client can be hand-written or generated with `ts-rs` (R5's call).
- **No `sentry`.** Add if we ever have paying users. `tracing` + Render logs are enough for solo prep.

---

## 12. Rust MSRV + toolchain

- **MSRV: Rust 1.83** (current stable at time of writing). Enforced in CI.
- `rust-toolchain.toml` pinned to `1.83`. Bump every 3-4 months to stay within 2 stable releases of head.
- Lints: `#![warn(clippy::all, clippy::pedantic)]` at crate root, with a `#![allow]` for the handful of pedantic lints that fire on axum extractor signatures. Add `#[deny(clippy::unwrap_used, clippy::expect_used)]` in `src/` — allowed only in `tests/`.

---

## 13. Migration order (informational — full plan in R7)

For downstream planners: this doc positions the Rust backend so it can be built alongside the running Flask app, cutting over per-route once parity is verified. Order that dovetails with the roadmap in `docs/plans/README.md`:

1. R1 (this doc) → R2 auth → R3 DB / migrations → R4 API contract → R5 frontend → R6 rollout.
2. First cutover slice: `/auth/*` + `/healthz`. Everything else still hits Flask via a reverse proxy on the same subdomain.
3. Cut analytics + review next (read-heavy, low risk).
4. Cut test-taking last (highest state complexity, sessions to migrate).

---

## 14. Checklist for the reader

Before starting R1 implementation, confirm:

- [ ] `axum 0.8` acceptable; not blocked by team preference for actix.
- [ ] MVC layout in §3 acceptable; no strong preference for hexagonal / DDD.
- [ ] `figment` for config; not overkill for solo dev.
- [ ] `argon2` for password hashing (vs current werkzeug pbkdf2-sha256). Existing hashes migrate on next login (best-effort).
- [ ] `libsql` official Rust client is stable enough today; if not, R3 substitutes with sqlite-in-memory for tests + libsql-server for prod.
- [ ] Render "Web Service" with a Dockerfile — confirm Kartik's Render plan supports Docker (Starter plan does; free plan does not build Docker natively but does run pre-built images).

---

_Written: 2026-07-19. Planning only. Sibling docs: R2 (auth), R3 (db), R4 (api), R5 (frontend), R6 (rollout) — to come._
