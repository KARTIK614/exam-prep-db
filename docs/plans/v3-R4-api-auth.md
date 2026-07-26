# R4 — REST API Contract + Auth Flow (Rust/axum backend ↔ React frontend)

Planning-only document. No code changes in this pass. Sibling docs: R1 (Rust
service architecture / crate layout / axum setup), R2 (Turso schema + `users`
table + migration story), R3 (React frontend), R5 (deployment).

**Scope**: the wire contract between the new Rust backend and the React SPA.
Endpoint inventory, auth flow, versioning, error envelope, pagination,
rate-limiting, CORS, observability. This is the source-of-truth that (a) R2
schema shapes, (b) R3 API-client codegen consumes, (c) R5 deployment gates
CORS + secrets against.

Existing Flask surface: 50 routes across 9 blueprints (`bp_admin.py`,
`bp_analytics.py`, `bp_api.py`, `bp_auth.py`, `bp_diag.py`, `bp_doubt.py`,
`bp_errorlog.py`, `bp_main.py`, `bp_review.py`, `bp_tests.py`). Every route
below is either 1-to-1 with an existing Flask handler or an explicit
new-behaviour marker (marked NEW).

Reader map:
- Section 1 — Style / versioning / OpenAPI toolchain
- Section 2 — Auth flow (JWT + refresh + RBAC) *strong-opinion section*
- Section 3 — Endpoint inventory (auth / user / content / tests / review /
  bookmarks / search / doubt / analytics / admin / meta)
- Section 4 — Error envelope + status-code map
- Section 5 — Pagination *strong-opinion section*
- Section 6 — Rate limiting
- Section 7 — CORS
- Section 8 — Request-id / logging / tracing
- Section 9 — Migration strategy from Flask session cookies to JWT
- Section 10 — Open questions

---

## 1. API style, versioning, OpenAPI

### 1.1 Style — REST, not GraphQL

**Recommendation: REST-over-JSON with resource-oriented paths.**

The decision matrix for this project:

| Signal                                         | REST | GraphQL |
|------------------------------------------------|:----:|:-------:|
| Solo developer, no dedicated frontend team     |  ✓   |    –    |
| Well-understood, small resource model (~15)    |  ✓   |    –    |
| Heavy caching (CDN, browser, `ETag`)           |  ✓   |    –    |
| Simple/no over-fetching pain (payloads small)  |  ✓   |    –    |
| Multiple mobile clients with divergent shape   |  –   |    ✓    |
| Uniform, flat resource joins (topics × qs)     |  ✓   |    –    |
| OpenAPI → TypeScript codegen for React         |  ✓   |    –    |
| Rust ecosystem maturity                        |axum/utoipa| async-graphql (heavier) |

The dominant argument is caching + codegen. `openapi-typescript` +
`utoipa`'s derive-from-handler flow gives the React app end-to-end typed
API access with zero manual DTO duplication. GraphQL would require Apollo
+ codegen + resolver plumbing for a resource model that fits comfortably
in ~15 tables (see R2). Not worth it.

Nested-collection reads (e.g. "tests with their responses") are the one
GraphQL-y pain point. We answer this with:
- Deliberate compound endpoints (`GET /tests/{id}` returns test + responses
  + palette state, one round-trip) — see §3.4
- `?expand=` param on read endpoints where selective inclusion is worth it
  (`GET /questions/{id}?expand=topic,flags`)

### 1.2 Versioning — path-based `/api/v1/*`

**Recommendation: path-based major version, single active version at a time.**

- All endpoints live under `/api/v1/`.
- No `Accept: application/vnd.exam.v1+json` header versioning — path
  versioning is the low-brain-tax option and every proxy/CDN handles it.
- No minor versions in the URL. Additive changes (new fields, new
  endpoints, new optional query params) do not bump the version.
- `v2` gets forked only for a breaking change; both live in parallel for
  ≥ 30 days with a `Deprecation: true; sunset="<rfc3339>"` header on `v1`
  responses. Given this is a single-user app today, "30 days" is
  effectively "until Kartik's frontend is updated".

**Compatibility contract for `v1`:**
- Never remove a field from a response body
- Never rename a field
- Never make an optional request field required
- Never add a required request field without a default
- Never change enum semantics (only add new variants — clients must treat
  unknown enum values as "unknown" not "error")
- Response bodies may gain fields at any time; clients must ignore
  unknowns

**Deprecation flow** (when we do have to remove something):
1. Add new field alongside old. Both populated for the full window.
2. Add `Deprecation: field=old_name; sunset="<date>"` response header.
3. Log every request that reads the deprecated field via server-side
   `X-Client-Version` header sniffing.
4. Remove on the sunset date. Not before.

### 1.3 OpenAPI as source of truth via `utoipa`

**Toolchain**:
- `utoipa` (0.5+) — derive-macro annotations on axum handlers, emit
  OpenAPI 3.0.3 spec at compile time
- `utoipa-swagger-ui` — serve interactive docs at `/api/v1/docs` (behind
  admin gate in prod, open in dev)
- `utoipa-redoc` — read-only ReDoc UI at `/api/v1/redoc` (public
  reference)
- Static export: `cargo run --bin dump-openapi > openapi.json` in CI,
  committed to the frontend repo
- Frontend: `openapi-typescript openapi.json -o src/api/schema.ts` +
  `openapi-fetch` for a fully-typed fetch wrapper (no runtime overhead —
  it's just a `fetch` shim with types)

**Why derive-from-handler and not spec-first**:
- Handlers are the truth. A hand-maintained YAML always drifts.
- Rust's type system catches most spec/impl mismatches at compile time
  once request/response DTOs are annotated.
- Frontend pulls the spec from CI artefact, not from a running backend —
  keeps FE builds hermetic.

**Sample handler declaration** (illustrative — full crate layout in R1):

```rust
// crates/api/src/handlers/tests.rs

use axum::{extract::{Path, State}, Json};
use utoipa::{ToSchema, IntoParams};
use serde::{Deserialize, Serialize};

#[derive(Deserialize, ToSchema)]
pub struct CreateTestRequest {
    /// Paper filter: "I", "II", or "both"
    #[schema(example = "II")]
    pub paper: String,

    /// Number of questions (1..=200)
    #[schema(example = 50, minimum = 1, maximum = 200)]
    pub num_questions: u32,

    /// Comma-separated topic ids. Empty = all topics.
    #[schema(example = "3,7,12")]
    pub topics: Option<String>,

    /// "easy" | "medium" | "hard" | "all"
    #[serde(default = "default_difficulty")]
    pub difficulty: String,

    /// Focus on topics where current_score < 60
    #[serde(default)]
    pub focus_weak: bool,

    /// "practice" | "exam"
    #[serde(default = "default_mode")]
    pub test_mode: String,

    /// Negative-marking ratio in [0.0, 1.0]. Only applied when
    /// test_mode == "exam". Ignored otherwise.
    #[serde(default)]
    pub negative_ratio: Option<f32>,

    /// Restrict to previous-year-questions (`pyq_exam IS NOT NULL`).
    #[serde(default)]
    pub pyq_only: bool,

    pub pyq_year_min: Option<i32>,
    pub pyq_year_max: Option<i32>,
}

#[derive(Serialize, ToSchema)]
pub struct CreateTestResponse {
    pub test_id: i64,
    pub question_ids: Vec<i64>,
    pub total: u32,
    pub test_mode: String,
    pub negative_ratio: f32,
    pub started_at: String, // RFC3339
}

#[utoipa::path(
    post,
    path = "/api/v1/tests",
    tag = "tests",
    request_body = CreateTestRequest,
    responses(
        (status = 201, description = "Test created", body = CreateTestResponse),
        (status = 400, description = "Invalid request", body = ErrorEnvelope),
        (status = 401, description = "Unauthorized", body = ErrorEnvelope),
        (status = 422, description = "Not enough questions matched filter", body = ErrorEnvelope),
    ),
    security(("bearer_auth" = []))
)]
pub async fn create_test(
    State(state): State<AppState>,
    user: AuthUser, // extractor — see §2
    Json(req): Json<CreateTestRequest>,
) -> Result<(StatusCode, Json<CreateTestResponse>), ApiError> {
    // ...
}
```

The `utoipa::path` macro emits the OpenAPI operation object at compile
time. `ApiError` (see §4) has a global `From` impl into the standard
error envelope, so handlers just `?` their way through.

### 1.4 Content type + representation

- `Content-Type: application/json; charset=utf-8` for all request +
  response bodies except `POST /admin/pdf-uploads` (multipart) and
  `GET /admin/pdf-uploads/{id}/pdf` (raw bytes)
- `Accept: application/json` on requests — server will 406 for anything
  else on v1
- All timestamps are RFC3339 UTC strings (`"2026-07-19T14:03:22Z"`).
  No epoch-second ambiguity, no timezone drift.
- All IDs are `i64` in JSON (Turso `INTEGER PRIMARY KEY`)
- Enum values are lowercase snake_case string literals (`"in_progress"`,
  `"time_pressure"`, `"pyq_exam"`)
- Nullable fields use JSON `null` explicitly. Never omit; always emit.

---

## 2. Auth flow — JWT access + rotating refresh, RBAC via claim *[opinion]*

Current Flask setup is a single JWT stored in an httpOnly cookie
(`auth_token`, HS256, 24h expiry, set at `/login`, read on every request
via `check_auth` before_request handler in `auth.py`). Roles are a
`role` column on `users` and checked by the `@require_admin` decorator.

For the multi-user rewrite the auth model needs to grow:
1. Registration (self-serve, no invite required — solo dev context, we
   trust email-verification later to gate abuse)
2. Password reset via email
3. Refresh flow so access tokens can stay short-lived
4. Deterministic logout / all-device revocation

### 2.1 Recommended flow — access + refresh split

**Access token**
- JWT (HS256 for now — single-service, no need for asymmetric keys yet)
- Lifetime: **15 minutes**
- Delivered in the response body of `/auth/login`, `/auth/register`,
  `/auth/refresh`
- Stored by React in memory only (not localStorage, not a cookie).
  Attached to requests as `Authorization: Bearer <token>`.
- Claims:

```json
{
  "iss": "exam-prep-api",
  "aud": "exam-prep-web",
  "sub": "42",            // user_id as string (JWT convention)
  "user_id": 42,          // duplicate as int for handler convenience
  "role": "user",         // "user" | "admin"
  "iat": 1737291600,
  "exp": 1737292500,      // iat + 900
  "jti": "8f2c..."        // for optional deny-list; see §2.4
}
```

**Refresh token**
- **Opaque random 256-bit token** (base64url-encoded, ~43 chars), *not*
  a JWT — we want server-side revocation and rotation, not stateless
  verification
- Lifetime: **30 days**, sliding window (each successful use extends
  30 days from now)
- Delivered as an httpOnly, Secure, SameSite=Lax **cookie**:
  `Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=Lax;
  Path=/api/v1/auth; Max-Age=2592000`
- Path-scoped to `/api/v1/auth` so it is never sent on data endpoints
  (defence in depth against XSS reading it via subtle attacks; only
  reason it's a cookie is that we cannot trust JS storage but we can
  trust the browser)
- Stored server-side in `refresh_tokens` table (see R2):
  `(id, user_id, token_hash, issued_at, expires_at, revoked_at,
  user_agent, ip)` — token itself is stored as SHA-256 hash so a DB leak
  doesn't grant login

### 2.2 Auth endpoint contract (details in §3.1)

| Verb | Path | Body-in | Body-out | Notes |
|------|------|---------|----------|-------|
| POST | `/auth/register` | `{email, username, password, display_name?}` | `{user_id, access_token, user}` + `Set-Cookie: refresh_token=...` | 201 on success; 409 if email/username exists |
| POST | `/auth/login` | `{identifier, password}` — `identifier` is email OR username | same as register | 200 on success; 401 on bad creds — same message either way (no user enumeration) |
| POST | `/auth/refresh` | *empty; reads cookie* | `{access_token}` + `Set-Cookie` (rotated refresh) | 401 on missing/expired/revoked; **rotates** refresh (see §2.4) |
| POST | `/auth/logout` | *empty; reads cookie* | 204 + `Set-Cookie` clearing it | Idempotent |
| POST | `/auth/logout-all` | *empty; auth required* | 204 | Revokes every refresh row for this user_id |
| POST | `/auth/forgot-password` | `{email}` | 202 (always, even if email unknown — no enumeration) | Sends email with signed one-shot token |
| POST | `/auth/reset-password` | `{token, new_password}` | 200 | Token = 32-byte random from `password_reset_tokens`, one-shot, 1h TTL |
| POST | `/auth/change-password` | `{current_password, new_password}` — auth required | 200 | Distinct from reset-password (requires old pw) |
| POST | `/auth/verify-email` | `{token}` | 200 | *Deferred — see §2.6* |

### 2.3 RBAC — role in the JWT, gate via extractor

Roles: `"user"` (default) and `"admin"`. Kept as a first-class column on
`users` (matches current Flask schema).

**Not** a separate scopes/permissions system — the app has one gated
surface (`/admin/*`) and the granularity fits a boolean. If the
requirements grow (e.g. content-mod role, TA role) we split into a
`user_roles` join table and issue `roles: ["admin","moderator"]` in the
claim; the extractor stays the same shape.

**Middleware layers** (from R1's tower stack):

```rust
// Public — no auth
Router::new()
    .route("/auth/register", post(auth::register))
    .route("/auth/login", post(auth::login))
    .route("/auth/refresh", post(auth::refresh))
    .route("/auth/forgot-password", post(auth::forgot_password))
    .route("/auth/reset-password", post(auth::reset_password))
    .route("/healthz", get(meta::healthz))
    .route("/openapi.json", get(meta::openapi_spec))

// Auth required — merge in the AuthUser extractor
    .merge(user_routes())          // any authenticated
    .merge(admin_routes())         // AuthAdmin extractor — 403 if role != admin
```

The extractor implementation is a small `FromRequestParts` impl that:
1. Parses `Authorization: Bearer <jwt>`
2. Validates signature + `exp` + `iat` + `aud` + `iss`
3. Optional: consults an in-memory `jti` deny-list cache (populated on
   logout — see §2.4)
4. Rejects with `401` if any step fails
5. Injects `AuthUser { user_id, role }` into the handler

`AuthAdmin` is `AuthUser` + a `role == "admin"` check that 403s
otherwise. This matches the current `require_admin` decorator in
`auth.py:67`.

### 2.4 Token rotation, revocation, and reuse detection

**Rotation on every refresh** — refresh tokens are single-use:
1. `POST /auth/refresh` reads cookie → looks up `refresh_tokens` row by
   `token_hash`
2. If found and `revoked_at IS NULL` and `expires_at > now`:
   - Mark old row `revoked_at = now`, `revoked_reason = "rotated"`
   - Insert new row with fresh random token, 30-day expiry, link
     `parent_id = old.id` (audit trail)
   - Issue new access token
   - Set new refresh cookie
3. If found but already revoked → **reuse detected**. Revoke the entire
   refresh chain for this user (walk `parent_id` back to root, then
   revoke every descendant). Log a security event. Return 401. Force
   full re-login.

This is the industry-standard "refresh token rotation with reuse
detection" pattern — protects against stolen refresh cookies because
the moment a stolen token is used a second time, the legitimate user's
next refresh triggers the whole-chain revocation.

**Access-token revocation** — we do NOT maintain a distributed deny-list
for access tokens. Their 15-minute lifetime is short enough that
`/auth/logout` merely revoking the refresh chain is sufficient. If a
future incident needs immediate revocation, we bump `token_version` on
the user row and include `tv` in JWT claims; middleware rejects if the
JWT's `tv` doesn't match. Deferred until we have evidence we need it.

### 2.5 Password storage

`argon2id` via the `argon2` crate.
- Params: `m=19456, t=2, p=1` (OWASP 2025 baseline)
- Column: `users.password_hash TEXT NOT NULL` (already exists in Flask
  schema; migration in R2 preserves it — Werkzeug `pbkdf2:sha256$` and
  argon2 `$argon2id$` are distinguishable by prefix, so we support both
  during migration and upgrade in place on next successful login)
- Password rules on register/change: min length 8, no other rules (long
  weak passwords > short strong). Log rejections; consider zxcvbn later
  if abuse appears.

### 2.6 Email verification — recommend deferring

**Skip for v3 launch.** Reasons:
- Solo user today; verification friction blocks the one legitimate
  signup we need
- No email infrastructure decision yet (Resend? Postmark? SES?)
- Not needed for password reset (reset just verifies control of the
  address at reset time)
- Blocking on email delivery is a single point of onboarding failure

We reserve `users.email_verified_at TIMESTAMP NULL` in the schema so we
can enable it later without a migration. When enabled:
- Registration sets `email_verified_at = NULL`
- A new endpoint `POST /auth/send-verification` (auth required) issues a
  token, emails it
- `POST /auth/verify-email {token}` sets `email_verified_at = now()`
- Existing `check_auth`-equivalent middleware gets a "verified only"
  variant used on write-heavy endpoints (test creation, flag reporting)

### 2.7 Session vs stateless — killing the Flask session

The current Flask app uses **`flask_session` filesystem sessions** for
non-auth state: `test_id`, `questions`, `current_q`, `responses`,
`review_marks`, `q_start_time`, `test_mode`, `negative_ratio`,
`last_result` (see `bp_tests.py`, `bp_api.py`). This is fundamentally a
per-user cache of the in-progress test, keyed by session cookie.

**In v3 this state moves to the DB**, not to a cookie. The `mock_tests`
row is created at test start; `test_responses` rows are written
incrementally per answer (currently only written at finish — see
"Existing route → v1 route" in §9). Timer state and review marks
persist on the row.

This means:
- `POST /tests/{id}/answers` is idempotent by `(test_id, question_id)`
  — safe to retry after a network blip
- Refreshing the page reloads the in-progress test via
  `GET /tests/{id}` — no session data lost
- Simultaneous devices see consistent state (mobile answer visible on
  laptop)

Net: **v3 is fully stateless server-side apart from the refresh-token
table**. No Flask sessions, no filesystem session dir, no `SECRET_KEY`
beyond the JWT signing key.

---

## 3. Endpoint inventory

Every existing Flask route mapped to a `v1` REST endpoint. HTML-rendering
routes (`/`, `/analytics`, `/errorlog`, `/test/setup`, `/test/take`,
`/results/*`, `/search`, `/bookmarks`, `/review`) are gone — the React
app renders those views client-side against these JSON endpoints.

Categories:
- 3.1 Auth
- 3.2 Users (profile, settings)
- 3.3 Content (topics, questions, search)
- 3.4 Tests (setup, take, finish, history, results)
- 3.5 Answers (in-test)
- 3.6 Review (Leitner SRS)
- 3.7 Error log
- 3.8 Bookmarks
- 3.9 Flags
- 3.10 Doubt (Deep Dive + Chat)
- 3.11 Study sessions
- 3.12 Analytics
- 3.13 Admin — flags / review queue / duplicates / questions / topics / users / uploads / synthesize / prompts
- 3.14 Meta (health, openapi, version)

Conventions used below:
- `req:` = request body sketch (post/patch) or query params (get)
- `res:` = 2xx response body sketch
- `auth:` = `public` | `user` | `admin`
- `flask:` = existing Flask handler this replaces, or `NEW`
- All paths under `/api/v1`

### 3.1 Auth

```
POST   /auth/register
  auth: public
  req:  { email: str, username: str, password: str, display_name?: str }
  res:  201 { user: User, access_token: str }  + Set-Cookie: refresh_token
  err:  409 email_taken | username_taken
  flask: NEW (Flask admin creates users manually via /admin/users)

POST   /auth/login
  auth: public
  req:  { identifier: str (email or username), password: str }
  res:  200 { user: User, access_token: str } + Set-Cookie
  err:  401 invalid_credentials (generic — same for wrong pw and unknown user)
  flask: bp_auth.py::login (form-based, redirects — replaced)

POST   /auth/refresh
  auth: refresh cookie
  req:  {}
  res:  200 { access_token: str } + Set-Cookie (rotated)
  err:  401 refresh_expired | refresh_revoked | refresh_reused_detected
  flask: NEW

POST   /auth/logout
  auth: refresh cookie (optional; endpoint always 204)
  req:  {}
  res:  204 + Set-Cookie: refresh_token=; Max-Age=0
  flask: bp_auth.py::logout

POST   /auth/logout-all
  auth: user
  req:  {}
  res:  204
  flask: NEW

POST   /auth/forgot-password
  auth: public
  req:  { email: str }
  res:  202 { message: "If that address exists, a reset email has been sent." }
  flask: NEW

POST   /auth/reset-password
  auth: public
  req:  { token: str, new_password: str }
  res:  200 { message: "Password reset. Please log in." }
  err:  400 token_invalid | token_expired | token_used
  flask: NEW

POST   /auth/change-password
  auth: user
  req:  { current_password: str, new_password: str }
  res:  200 { }
  err:  400 current_password_incorrect
  flask: bp_admin.py::user_update (admin-only in Flask; user-self-serve now)
```

### 3.2 Users

```
GET    /me
  auth: user
  res:  200 { id, email, username, display_name, role, created_at,
              last_login, settings: { target_score, weak_threshold,
              target_seconds_per_q, default_neg_ratio, dark_mode } }
  flask: NEW (Flask reads g.user directly in each handler)

PATCH  /me
  auth: user
  req:  { display_name?: str, email?: str }   // email change → re-verify later
  res:  200 { user: User }
  flask: NEW

GET    /me/settings
  auth: user
  res:  200 { target_score: int, weak_threshold: int,
              target_seconds_per_q: int, default_neg_ratio: float,
              dark_mode: bool, ...other kv-store keys }
  flask: derived from bp_main.py::index reading `settings` table

PATCH  /me/settings
  auth: user
  req:  { target_score?, weak_threshold?, target_seconds_per_q?,
          default_neg_ratio?, dark_mode?, ... }
  res:  200 { settings: Settings }
  flask: bp_api.py::update_settings (POST /api/settings)
```

Note: the current `settings` table is global (see `db.py`). R2 will
namespace it by `user_id` — the migration doc handles that. This
endpoint reads/writes only the current user's rows.

### 3.3 Content — topics + questions + search

```
GET    /topics
  auth: user
  query: paper? = "I" | "II" | "both", subject?, has_questions? = bool
  res:  200 { topics: [{id, name, subject, paper, weightage,
                        question_count}] }
  flask: bp_tests.py:134 (rendered into test_setup.html), plus multiple
         inline SELECTs across bp_main, bp_admin, bp_analytics

GET    /questions
  auth: user
  query: topic_id?, paper?, difficulty?, pyq_only?, pyq_exam?, pyq_year?,
         disabled? (admin-only param), cursor?, limit? (max 100, default 20)
  res:  200 { questions: [Question], next_cursor?: str, total?: int }
  flask: bp_admin.py::questions_list (admin view) + implicit reads in
         bp_tests.py::setup

GET    /questions/{id}
  auth: user
  query: expand? = "topic,flags,bookmark_status"
  res:  200 { question: Question, topic?: Topic, flags?: [Flag],
              bookmarked?: bool }
  flask: bp_api.py::get_question (/api/question/<idx> — indexed by
         position-in-session, not by DB id — the new endpoint is by id)

POST   /questions/{id}/flag
  auth: user
  req:  { category: enum, note?: str, test_id?: int }
  res:  201 { flag_id: int }
  err:  400 invalid_category | note_required_for_other
  flask: bp_api.py::flag_question (/api/flag_question)

POST   /questions/{id}/bookmark
  auth: user
  req:  { note?: str }
  res:  201 { bookmarked: true, bookmark_id: int }
  flask: bp_api.py::toggle_bookmark (was toggle, split to POST/DELETE now)

DELETE /questions/{id}/bookmark
  auth: user
  res:  204
  flask: bp_api.py::toggle_bookmark

GET    /bookmarks
  auth: user
  query: cursor?, limit?
  res:  200 { bookmarks: [{bookmark_id, question, note, created_at}],
              next_cursor? }
  flask: bp_main.py::bookmarks

POST   /questions/{id}/deep-dive
  auth: user
  req:  { test_id?: int }
  res:  200 { analysis: { explanation, key_facts, exam_tips, storyline },
              cached: bool }
  err:  502 ai_unavailable { error_id }
  flask: bp_doubt.py::deep_dive (/api/doubt/deep-dive)

POST   /questions/{id}/chat
  auth: user
  req:  { test_id?: int, message: str }
  res:  200 { response: str }
  err:  502 ai_unavailable { error_id }
  flask: bp_doubt.py::chat (/api/doubt/chat)

GET    /search
  auth: user
  query: q (required, >= 2 chars), topic_id?, difficulty?, confidence?,
         pyq_exam?, pyq_year?, cursor?, limit?
  res:  200 { total: int, results: [{id, question_text, topic_name,
              snippet, difficulty, correct_option, options}],
              backend: "fts5" | "like", next_cursor? }
  flask: bp_main.py::api_search (/api/search)
```

### 3.4 Tests

```
POST   /tests
  auth: user
  req:  see §1.3 CreateTestRequest
  res:  201 { test_id, question_ids, total, test_mode, negative_ratio,
              started_at }
  err:  422 no_questions_matched_filter
  flask: bp_tests.py::setup (POST /test/setup) — was form+redirect

GET    /tests
  auth: user
  query: status? = "in_progress" | "completed" | "abandoned",
         paper?, from?, to?, cursor?, limit?
  res:  200 { tests: [TestSummary], next_cursor? }
    TestSummary = { id, paper, test_mode, total_questions, score,
                    raw_marks, wrong_count, unanswered_count,
                    time_taken_sec, negative_ratio, started_at,
                    completed_at, status }
  flask: implicit — index.html reads mock_tests via bp_main.py

GET    /tests/{id}
  auth: user (must own the test, else 404 not 403 — avoid leaking existence)
  res:  200 {
          test: TestSummary,
          questions: [Question],           // in order
          responses: {                     // by question_index
            "0": { question_id, selected_option, is_correct?,
                   marked_for_review, time_spent_sec, visit_count },
            ...
          },
          current_index: int,
          palette: [{ index, status:
                      "unanswered" | "answered" | "marked" |
                      "answered_marked" | "unvisited" }],
        }
  flask: bp_tests.py::take (renders test.html) — new endpoint hydrates
         the same state so React can resume-after-refresh

POST   /tests/{id}/finish
  auth: user
  req:  {} (idempotent — checks status)
  res:  200 { test: TestSummary, results: TestResults }
    TestResults = same shape as /tests/{id}/results below
  err:  409 already_completed
  flask: bp_tests.py::finish (POST /test/finish)

GET    /tests/{id}/results
  auth: user
  res:  200 { test: TestSummary, responses: [ResponseDetail],
              avg_time_sec: float, fastest_sec, slowest_sec,
              topic_breakdown: [{topic_name, correct, total,
                                 total_time_sec}],
              error_types: {concept_gap, memory_lapse, misread,
                            calculation, time_pressure},
              phases: {early: {...}, mid: {...}, late: {...}} }
  flask: bp_tests.py::results (/results/<int:test_id>)

DELETE /tests/{id}
  auth: user
  res:  204 (only in_progress tests can be deleted; completed = archived)
  flask: NEW
```

### 3.5 Answers (in-test)

Answers are attached to a test resource, addressed by question id (not
by question_index — this makes the palette independent of ordering
should we ever shuffle mid-test):

```
PUT    /tests/{test_id}/answers/{question_id}
  auth: user
  req:  { selected_option?: "A"|"B"|"C"|"D"|null,
          marked_for_review?: bool,
          time_spent_sec?: int }
  res:  200 {
          question_id,
          selected_option,
          marked_for_review,
          time_spent_sec,
          visit_count,
          palette: [PaletteCell],       // full palette for consistency
          answered_count: int,
          total: int
        }
  flask: bp_api.py::submit_answer + bp_api.py::mark_for_review — merged
         into one PUT so the FE can debounce keystrokes

DELETE /tests/{test_id}/answers/{question_id}
  auth: user
  res:  200 { palette, answered_count, total }
  flask: NEW (was implicit — "clear response" is a common exam-UI button)
```

`PUT` semantics: this is the *user's answer for this question in this
test*. Sending it multiple times with the same body is a no-op; sending
it with different fields is a partial update (any absent field is left
alone). Using PUT + idempotent shape means the FE can retry safely on
network flake without double-counting.

### 3.6 Review (Leitner SRS)

```
GET    /review/queue
  auth: user
  query: limit? (default 100), box? (filter by SR box 1..5)
  res:  200 { cards: [ReviewCard], summary: { due_today: int,
              due_tomorrow: int, by_box: {1: n, 2: n, ...} } }
    ReviewCard = { error_id, question_id, question_text, topic_name,
                   sr_box, sr_due_at, if_ok_box, if_ok_days,
                   if_no_box, if_no_days }
  flask: bp_review.py::index (/review, HTML)

POST   /review/answers/{error_id}
  auth: user
  req:  { was_correct: bool }
  res:  200 { new_box: int, new_due_at: str, days_until_next: int }
  err:  404 not_found
  flask: bp_review.py::api_review_answer (/api/review_answer)
```

### 3.7 Error log

```
GET    /errors
  auth: user
  query: topic_id?, error_type?, resolved? = "yes"|"no"|"all",
         cursor?, limit?
  res:  200 { errors: [ErrorEntry], next_cursor?, sr_summary: {...} }
  flask: bp_errorlog.py::view (/errorlog, HTML)

POST   /errors/{id}/resolve
  auth: user
  req:  { root_cause?: str }
  res:  200 { }
  flask: bp_api.py::resolve_error (/api/resolve_error)

POST   /errors/{id}/redo
  auth: user
  req:  { attempt: 1 | 2, score: int }
  res:  200 { }
  flask: bp_api.py::redo_error (/api/redo_error)
```

### 3.8 Study sessions

```
POST   /study-sessions
  auth: user
  req:  { topic_id: int, duration_min: int, mcqs_solved: int,
          score?: int, notes?: str }
  res:  201 { session: StudySession }
  flask: bp_api.py::log_study_session (/api/study_session)

GET    /study-sessions
  auth: user
  query: topic_id?, from?, to?, cursor?, limit?
  res:  200 { sessions: [StudySession], next_cursor? }
  flask: NEW (data exists, no read endpoint)
```

### 3.9 Analytics

```
GET    /analytics/overview
  auth: user
  res:  200 { tests: {total, avg_score, total_time_sec},
              last_test?: TestSummary,
              consistency: {score: int, active_days: int,
                            activity_28d: [{date, has_activity}]},
              sr_due_today: int }
  flask: derived from bp_main.py::index

GET    /analytics/mastery
  auth: user
  query: paper? = "I" | "II" | "both"
  res:  200 { tiles: [MasteryTile], grouped_by_paper: {I: [...], II: [...]} }
    MasteryTile = { topic_id, name, subject, paper, weightage,
                    current_score, test_count, tier: "weak"|"on_track"|
                    "untested"|"mastered", days_since?, last_studied? }
  flask: bp_main.py::_mastery_tiles + bp_analytics.py::_mastery_tiles

GET    /analytics/next-topics
  auth: user
  query: limit? (default 3)
  res:  200 { next_topics: [{topic_id, name, weightage, next_score,
              reason}] }
  flask: bp_main.py::_rank_next_topic

GET    /analytics/heatmap
  auth: user
  query: dim = "difficulty" | "recency"  (required)
  res:  200 { dim, topics: [{topic_id, name, weightage,
              cells: { <bucket>: {attempted, correct, accuracy} | null }}] }
  flask: bp_analytics.py::_heatmap_by_difficulty +
         bp_analytics.py::_heatmap_by_recency

GET    /analytics/pacing
  auth: user
  res:  200 { pace_by_difficulty: [{difficulty, avg_time, n}],
              time_trend: [{test_id, paper, avg_time, score, date}],
              ma_pace: [float?],
              target_sec: int,
              slow_wrong: [{question_id, question_text, difficulty,
                            time_spent_sec, topic}] }
  flask: bp_analytics.py::dashboard (pieces)

GET    /analytics/consistency
  auth: user
  query: days? (default 28), denom? (default 20)
  res:  200 { score: int, active_days: int,
              activity: [{date, has_activity}] }
  flask: bp_main.py::_consistency

GET    /analytics/error-distribution
  auth: user
  res:  200 { by_type: [{error_type, count}],
              trends: [{date, error_type, count}] }
  flask: bp_main.py::index (error_dist) + bp_analytics.py::dashboard (error_trends)

GET    /analytics/paper-performance
  auth: user
  res:  200 { by_paper: [{paper, tests, avg_score}] }
  flask: bp_main.py::index (paper_perf)
```

### 3.10 Admin

Every admin endpoint requires `role == "admin"`. All return `403
forbidden` (envelope) for authenticated non-admins.

```
GET    /admin/stats
  res:  200 { flags_open, flags_total, questions, questions_disabled,
              topics, users, uploads, review_medium, review_synthetic,
              deficit_topics, recent_flags: [FlagWithQuestion] }
  flask: bp_admin.py::dashboard

--- Flags ---
GET    /admin/flags
  query: status? = "open"|"resolved"|"dismissed"|"all", cursor?, limit?
  res:  200 { flags: [FlagWithQuestion], next_cursor? }
  flask: bp_admin.py::flags

POST   /admin/flags/{id}/resolve
  res:  200 {}
  flask: bp_admin.py::flag_action (action="resolve")

POST   /admin/flags/{id}/dismiss
  res:  200 {}
  flask: bp_admin.py::flag_action (action="dismiss")

POST   /admin/flags/{id}/disable-question
  res:  200 { question_id_disabled: int }
  flask: bp_admin.py::flag_action (action="disable_question")

--- Review queue (Plan D §2) ---
GET    /admin/review-queue
  query: filter = "medium"|"with_notes"|"synthetic"|"deferred"|"non_high",
         cursor?, limit?
  res:  200 { questions: [Question], counts: {medium, with_notes,
              synthetic, deferred, non_high}, next_cursor? }
  flask: bp_admin.py::review_queue

POST   /admin/review-queue/{qid}/confirm
  res:  200 { confidence: "high" }
  flask: bp_admin.py::review_action (action="confirm")

POST   /admin/review-queue/{qid}/disable
  res:  200 { disabled: 1 }
  flask: bp_admin.py::review_action (action="disable")

POST   /admin/review-queue/{qid}/defer
  res:  200 { confidence: "deferred" }
  flask: bp_admin.py::review_action (action="defer")

PATCH  /admin/questions/{qid}
  req:  { question_text?, option_a?, option_b?, option_c?, option_d?,
          correct_option?, explanation?, difficulty?, topic_id?,
          disabled?, confidence?, section?, sub_topic?, pyq_exam?,
          pyq_year?, review_notes? }
  res:  200 { question: Question }
  flask: bp_admin.py::review_action (action="edit") +
         bp_admin.py::question_edit (POST) — merged

--- Duplicates (Plan D §3) ---
GET    /admin/duplicates
  query: threshold? (0.5..1.0, default 0.7), limit? (default 200)
  res:  200 { pairs: [{q1: Question, q2: Question, jaccard, isize,
              n1, n2, suggested_keep: int, suggested_disable: int,
              q1_refs: int, q2_refs: int}],
              threshold, total_trigrams }
  flask: bp_admin.py::duplicates_view

POST   /admin/duplicates/{qid}/disable
  res:  200 { disabled_id: int }
  flask: bp_admin.py::duplicate_disable

--- Questions CRUD ---
GET    /admin/questions
  query: topic_id?, paper?, difficulty?, disabled?, cursor?, limit?
  res:  200 { questions: [Question], total, next_cursor? }
  flask: bp_admin.py::questions_list

POST   /admin/questions
  req:  { topic_id, question_text, option_a..d, correct_option,
          explanation?, difficulty?, source?, section?, sub_topic?,
          pyq_exam?, pyq_year?, confidence? }
  res:  201 { question: Question }
  flask: NEW (Flask has admin-only via edit form; adding explicit create)

PATCH  /admin/questions/{qid}   — see above under review queue

POST   /admin/questions/{qid}/toggle-disabled
  res:  200 { disabled: 0|1 }
  flask: bp_admin.py::question_toggle_disabled

DELETE /admin/questions/{qid}
  res:  204
  flask: bp_admin.py::question_delete

--- Topics CRUD ---
GET    /admin/topics
  res:  200 { topics: [TopicWithCounts] }
  flask: bp_admin.py::topics_view (GET)

POST   /admin/topics
  req:  { name, subject, paper, weightage }
  res:  201 { topic: Topic }
  flask: bp_admin.py::topics_view (POST)

PATCH  /admin/topics/{tid}
  req:  { name?, subject?, paper?, weightage? }
  res:  200 { topic: Topic }
  flask: NEW (Flask has delete only)

DELETE /admin/topics/{tid}
  res:  204
  flask: bp_admin.py::topic_delete

--- Users CRUD ---
GET    /admin/users
  query: cursor?, limit?
  res:  200 { users: [UserWithRole], next_cursor? }
  flask: bp_admin.py::users_view (GET)

POST   /admin/users
  req:  { username, password, email?, role? }
  res:  201 { user: User }
  flask: bp_admin.py::users_view (POST)

PATCH  /admin/users/{uid}
  req:  { role?, is_active?, password?, email?, display_name? }
  res:  200 { user: User }
  flask: bp_admin.py::user_update

--- PDF uploads ---
GET    /admin/pdf-uploads
  query: cursor?, limit?
  res:  200 { uploads: [Upload], next_cursor? }
  flask: bp_admin.py::uploads_view (GET)

POST   /admin/pdf-uploads
  content-type: multipart/form-data
  req:  { pdf: file, topic_id?: int, prompt_name?: str }
  res:  202 { upload_id, status: "processing" }
       (async — client polls GET /admin/pdf-uploads/{id})
  flask: bp_admin.py::uploads_view (POST) — was sync in Flask; NEW async

GET    /admin/pdf-uploads/{id}
  res:  200 { upload: Upload, extracted_questions?: [ExtractedQuestion] }
  flask: bp_admin.py::upload_preview

POST   /admin/pdf-uploads/{id}/import
  req:  { selected_ids: [int] }  // indices into the extracted list
  res:  200 { imported: int, imported_question_ids: [int] }
  flask: bp_admin.py::upload_import

--- Synthesize (LLM question generation) ---
GET    /admin/synthesize
  res:  200 { deficit_topics: [DeficitRow], topics: [TopicWithCounts],
              recent_batches: [Batch] }
  flask: bp_admin.py::synthesize_view

POST   /admin/synthesize
  req:  { topic_id, count (1..40), sub_topics? }
  res:  202 { batch_id, n_generated, preview_url }
  err:  400 cap_exceeded { max_new: int }
  flask: bp_admin.py::synthesize_preview

GET    /admin/synthesize/{batch_id}
  res:  200 { batch: Batch, questions: [ExtractedQuestion] }
  flask: bp_admin.py::synthesize_preview_view

POST   /admin/synthesize/{batch_id}/commit
  req:  { selected_ids: [int] }
  res:  200 { imported: int, imported_question_ids: [int] }
  flask: bp_admin.py::synthesize_commit

--- Master prompts (LLM extraction templates) ---
GET    /admin/prompts
  res:  200 { prompts: [Prompt] }
  flask: bp_admin.py::prompts_view (GET)

POST   /admin/prompts
  req:  { name, template, model?, is_default? }
  res:  201 { prompt: Prompt }
  flask: bp_admin.py::prompts_view (POST — upsert)

PATCH  /admin/prompts/{name}
  req:  { template?, model?, is_default? }
  res:  200 { prompt: Prompt }
  flask: bp_admin.py::prompts_view (POST — upsert-if-exists branch)

DELETE /admin/prompts/{name}
  res:  204
  flask: NEW
```

### 3.11 Meta (public / infra)

```
GET    /healthz
  auth: public
  res:  200 { status: "ok", db: "ok"|"degraded"|"down",
              version: "3.0.0", uptime_sec: int }

GET    /openapi.json
  auth: public in dev; admin-gated in prod (leaks the entire surface)
  res:  200 <openapi 3.0.3 document>

GET    /version
  auth: public
  res:  200 { version, git_sha, built_at }
```

### 3.12 Removed Flask routes (intentionally not carried over)

- `/diag/<token>` (`bp_diag.py`) — one-shot debug for the Turso token
  saga. Replace with `/healthz` + structured logs.
- `/setup/seed/<token>` (`bp_diag.py`) — bootstrap-time admin seeding.
  Solved by `/auth/register` + a first-registered-user promotion in the
  migration script (see R5).

---

## 4. Error envelope + status-code map

**Standard envelope for every non-2xx response** (and for 2xx warnings):

```json
{
  "error": {
    "code": "invalid_credentials",
    "message": "Email or password is incorrect.",
    "request_id": "01J8QK4Z0X3H8XW5R6QTVMH2E4",
    "details": {
      "field": "password"
    }
  }
}
```

Fields:
- `code` — machine-readable stable slug. Never changes for a given
  logical error. Enumerated in the OpenAPI spec.
- `message` — human-readable, safe to surface to end users. English
  only for v1 (Hindi later — see R3).
- `request_id` — ULID from the request-id middleware (§8). Also echoed
  in `X-Request-Id` response header for easy grep from server logs.
- `details` — optional, code-specific. E.g. `{field: "email"}` for
  validation errors, `{max_new: 5}` for the synthetic cap.

### 4.1 Status code map

| Status | When | Example `code` |
|---|---|---|
| 400 | Malformed request, unknown enum, missing required field | `bad_request`, `invalid_enum`, `note_required_for_other` |
| 401 | Unauthenticated (no or bad JWT) or refresh flow failed | `unauthenticated`, `access_token_expired`, `refresh_expired`, `refresh_revoked`, `refresh_reused_detected`, `invalid_credentials` |
| 403 | Authenticated but not permitted | `forbidden`, `admin_required`, `email_not_verified` (future) |
| 404 | Resource not found *or hidden from this user* (see §2.7) | `not_found` |
| 409 | State conflict | `email_taken`, `username_taken`, `already_completed`, `test_already_finished` |
| 422 | Semantically invalid (well-formed but business rule fails) | `no_questions_matched_filter`, `cap_exceeded` |
| 429 | Rate limited | `rate_limited` (see §6) — includes `Retry-After` header |
| 500 | Bug / unhandled panic | `internal_error` — never leak stack traces |
| 502 | Upstream (Gemini, Anthropic) failure | `ai_unavailable` |
| 503 | Turso down / DB unreachable | `db_unavailable` |

### 4.2 Validation errors — multiple at once

```json
{
  "error": {
    "code": "validation_failed",
    "message": "Some fields are invalid.",
    "request_id": "01J...",
    "details": {
      "fields": [
        { "field": "email", "code": "invalid_format" },
        { "field": "password", "code": "too_short", "min": 8 }
      ]
    }
  }
}
```

### 4.3 Error type in Rust

```rust
// crates/api/src/error.rs
#[derive(thiserror::Error, Debug)]
pub enum ApiError {
    #[error("unauthenticated")]
    Unauthenticated,

    #[error("forbidden")]
    Forbidden,

    #[error("not found")]
    NotFound,

    #[error("bad request: {0}")]
    BadRequest(&'static str),

    #[error("validation failed")]
    Validation(Vec<FieldError>),

    #[error("conflict: {0}")]
    Conflict(&'static str),

    #[error("rate limited")]
    RateLimited { retry_after_sec: u64 },

    #[error("upstream ai failure")]
    AiUnavailable { error_id: String },

    #[error("db unavailable")]
    DbUnavailable,

    #[error(transparent)]
    Internal(#[from] color_eyre::Report),
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response { /* map to envelope + status */ }
}
```

Handlers `?` normal errors up; the middleware layer catches panics and
maps them to `internal_error` with a fresh `request_id` in the log line.

---

## 5. Pagination — cursor, not offset *[opinion]*

**Recommendation: opaque cursor pagination on every collection endpoint.**

### 5.1 Why cursor beats offset here

Offset pagination (`?page=3&per_page=20`) is what the Flask admin uses
(`bp_admin.py:685-716`, `bp_errorlog.py:13-15`). It's simple but:
1. Skips get expensive on Turso — `LIMIT 20 OFFSET 5000` still scans 5000
   rows to skip them
2. Row shift bug: if a new question is inserted between page 2 and page 3
   reads, the user sees the same row twice (or misses one)
3. Total count query is a separate SQL round-trip — doubles the QPS

Cursors solve all three. Trade-off: no direct "go to page N" — you can
only page forward/backward from where you are. Acceptable for every
list in this app (nobody deep-links `/admin/questions?page=17`).

### 5.2 Cursor format

Opaque base64url-encoded JSON:

```
{
  "k": ["created_at", "id"],           // sort keys (server-defined)
  "v": ["2026-07-19T14:03:22Z", 4127], // last-row values
  "d": "desc"                          // direction
}
```

Encoded: `eyJrIjpbImNyZWF0ZWRfYXQiLCJpZCJdLCJ2Ijpb...`

Client treats it as an opaque string. Never construct one FE-side.

### 5.3 Request/response shape

Request:
```
GET /questions?topic_id=3&limit=20&cursor=eyJr...
```

Response:
```json
{
  "questions": [ ... 20 items ... ],
  "next_cursor": "eyJr...",       // null when at end
  "prev_cursor": "eyJr...",       // optional; null on first page
  "limit": 20
}
```

- No `total` in the paginated envelope by default — it's expensive.
  A separate `GET /admin/questions/count` endpoint exists for the two
  screens that need it (admin question list, admin flags — for the
  "N flags open" badge).
- Max `limit` per endpoint enumerated in the OpenAPI spec. Default 20,
  hard cap 100 for most collections; admin duplicate-pairs caps at 200
  (matches current Flask behaviour, see `bp_admin.py:397`).

### 5.4 Sort keys per collection

Each collection has a *single* server-controlled sort. No `?sort=` query
param in v1 (fewer footguns; can add later without breaking).

| Endpoint | Default sort |
|---|---|
| `GET /questions` | `id DESC` |
| `GET /admin/questions` | `id DESC` |
| `GET /admin/flags` | `created_at DESC, id DESC` |
| `GET /tests` | `started_at DESC, id DESC` |
| `GET /errors` | `created_at DESC, id DESC` |
| `GET /bookmarks` | `created_at DESC, id DESC` |
| `GET /search` | `bm25 rank` (FTS5) or `id DESC` (LIKE fallback) |
| `GET /review/queue` | `sr_due_at ASC, sr_box ASC` |
| `GET /study-sessions` | `date DESC, id DESC` |

The `id` tiebreaker guarantees a stable ordering when the primary sort
key has duplicates (very common on `created_at`).

---

## 6. Rate limiting

**Recommendation**: `tower-governor` for per-endpoint declarative
limits, with two backends:
- **In-memory (dashmap)** — default; per-instance state. Fine while
  we're on a single Render service.
- **Turso-backed** — for when we scale to multiple instances (see R5).
  A `rate_limit_buckets` table + a stored-procedure-ish token bucket
  update. Not needed at launch; interface is the same either way so we
  can flip it later.

### 6.1 Limits per endpoint class

| Class | Endpoints | Limit | Key |
|---|---|---|---|
| Auth-write | `POST /auth/login`, `/auth/register`, `/auth/forgot-password`, `/auth/reset-password` | 5 req/min | IP |
| Auth-refresh | `POST /auth/refresh` | 30 req/min | refresh_token (hash) |
| Deep dive | `POST /questions/{id}/deep-dive`, `.../chat` | 20 req/hour | user_id |
| General write | Every other `POST`/`PATCH`/`PUT`/`DELETE` | 120 req/min | user_id |
| General read | Every `GET` under `/api/v1/*` | 300 req/min | user_id |
| Admin | Every `/admin/*` | 600 req/min | user_id |
| Public | `/healthz`, `/openapi.json`, `/version` | 60 req/min | IP |

Anonymous requests to public endpoints are keyed by client IP (behind
Render's proxy → trust `X-Forwarded-For` first hop per R5).

### 6.2 Response on limit

```
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 12
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1737292500
X-Request-Id: 01J...

{
  "error": {
    "code": "rate_limited",
    "message": "Too many requests. Please retry in 12 seconds.",
    "request_id": "01J...",
    "details": { "retry_after_sec": 12 }
  }
}
```

Frontend interceptor auto-retries after `Retry-After` for idempotent
GET requests (see R3 for API-client design).

### 6.3 Bypass for admins?

No. Rate limits still apply to admins — they're set high enough that
normal admin work is nowhere near the ceiling, and the limit protects
against a compromised admin credential. Real "bulk import" flows go
through the batch endpoints (`POST /admin/pdf-uploads/{id}/import`),
which insert N rows in a single request and count as one call.

---

## 7. CORS

The React SPA and API deploy separately (see R5). CORS is mandatory.

### 7.1 Allowed origins

Environment-driven, comma-separated list in `EXAM_CORS_ORIGINS`:

- **Dev**: `http://localhost:5173,http://localhost:3000`
- **Staging**: `https://staging.exam-prep.pages.dev`
- **Prod**: `https://exam-prep.pareek.dev` (custom domain) plus the
  bare Vercel/Pages domain `https://exam-prep-<hash>.pages.dev` during
  preview deploys

**No wildcard** (`*`) — we need credentials.

### 7.2 Config (tower-http CorsLayer)

```rust
use tower_http::cors::{Any, CorsLayer};
use http::{header, Method};

let cors = CorsLayer::new()
    .allow_origin(parse_origins(env::var("EXAM_CORS_ORIGINS")?))
    .allow_methods([Method::GET, Method::POST, Method::PATCH,
                    Method::PUT, Method::DELETE, Method::OPTIONS])
    .allow_headers([
        header::AUTHORIZATION,
        header::CONTENT_TYPE,
        header::ACCEPT,
        "x-request-id".parse().unwrap(),
        "x-client-version".parse().unwrap(),
    ])
    .expose_headers([
        "x-request-id".parse().unwrap(),
        "x-ratelimit-limit".parse().unwrap(),
        "x-ratelimit-remaining".parse().unwrap(),
        "x-ratelimit-reset".parse().unwrap(),
        "deprecation".parse().unwrap(),
        "sunset".parse().unwrap(),
    ])
    .allow_credentials(true)                // required for refresh cookie
    .max_age(std::time::Duration::from_secs(600));
```

`allow_credentials: true` is what lets the refresh-token cookie ride
along on `POST /auth/refresh`. Without it, browsers strip cookies from
cross-origin requests silently.

### 7.3 SameSite=Lax + Path scoping

Refresh cookie set with:
```
Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=Lax;
            Path=/api/v1/auth; Max-Age=2592000
```

`SameSite=Lax` is safe here because refresh is only ever issued via
same-origin XHR/fetch initiated by our own JS. Cross-site navigation
POSTs (attacker link) don't carry `Lax` cookies. `SameSite=Strict`
would break the (rare but legitimate) case of the user pasting a link
into the app after login — Lax handles that correctly.

Path=`/api/v1/auth` means the cookie *never leaves the auth sub-tree*
— no accidental exposure via a compromised handler in another module.

### 7.4 Preflight caching

`max_age=600` (10 minutes) — long enough to avoid preflight churn
during a normal session, short enough that CORS-config changes
propagate quickly during rollout.

---

## 8. Request-id, logging, tracing

### 8.1 Request-id middleware

Every request either:
- Reuses an incoming `X-Request-Id` header if it looks well-formed
  (26-char ULID or 36-char UUID; anything else is discarded)
- Or generates a fresh ULID

Response always echoes `X-Request-Id`.

Rust: `tower-http::request_id::SetRequestIdLayer` + a small custom
extractor so handlers can `let req_id = req.extensions().get::<RequestId>()`.

### 8.2 Structured logging

`tracing` + `tracing-subscriber` with JSON formatter in prod, pretty
console in dev. Every log line has:

```json
{
  "ts": "2026-07-19T14:03:22.114Z",
  "level": "INFO",
  "target": "api::handlers::tests",
  "request_id": "01J8QK4Z0X3H8XW5R6QTVMH2E4",
  "user_id": 42,
  "method": "POST",
  "path": "/api/v1/tests",
  "status": 201,
  "duration_ms": 84,
  "msg": "test created",
  "test_id": 891
}
```

`tower-http::trace::TraceLayer` handles the request-in/response-out
lines automatically. Handlers add domain-specific spans via
`#[tracing::instrument(skip(state), fields(user_id = user.id))]`.

### 8.3 What NOT to log

- Passwords (obviously; never even at DEBUG)
- Full JWT tokens — log `jti` prefix only
- Refresh tokens — log hash prefix only
- Full question text in bulk import — log counts, not bodies
- Deep-dive prompt bodies — they contain the question stem; fine
  individually, but not in bulk. Aggregate metrics only.
- User email on 401 (avoids enumeration via log-tailing side channel)

### 8.4 Metrics (deferred — R5 covers)

Prometheus-scrape endpoint (`/metrics`, admin-gated) via
`axum-prometheus`. Counters we care about:
- `http_requests_total{method,path_template,status}`
- `http_request_duration_seconds{method,path_template}` (histogram)
- `auth_login_attempts_total{outcome}`
- `refresh_reuse_detected_total`
- `ai_deep_dive_seconds` (histogram)
- `rate_limit_exceeded_total{class}`

---

## 9. Migration strategy — Flask → Rust cutover

Not the focus of this doc (R5 owns deploy), but the API contract has
implications:

### 9.1 Parallel run window

For ~2 weeks:
- Flask stays deployed at `exam-prep.onrender.com` (current)
- Rust API deploys at `api.exam-prep.pareek.dev`
- React FE points at Rust
- Kartik uses Rust as primary; Flask stays warm as fallback
- The two share **the same Turso database** — the Rust API must be a
  read/write superset of Flask for the shared columns

### 9.2 Cookie handoff (out of scope but noted)

Flask sets `auth_token` (JWT) on `exam-prep.onrender.com`. Rust sets
`refresh_token` on the api subdomain. These do not collide. On the
cutover day, Flask sessions expire naturally (24h) and users log in
against the new endpoint. No forced logout event.

### 9.3 "Existing route → v1 route" quick-ref

Full table for the migration checklist:

| Flask                                          | v1                                              |
|-----------------------------------------------|-------------------------------------------------|
| GET  /                                        | GET /me + GET /analytics/overview + GET /analytics/mastery + GET /analytics/next-topics + GET /analytics/consistency + GET /review/queue?limit=0 (for count) |
| GET  /login (form)                            | *client renders*; POST /auth/login              |
| POST /login                                   | POST /auth/login                                |
| GET  /logout                                  | POST /auth/logout                               |
| GET  /test/setup (form)                       | *client renders*; GET /topics                   |
| POST /test/setup                              | POST /tests                                     |
| GET  /test/take                               | GET /tests/{id}                                 |
| POST /test/finish                             | POST /tests/{id}/finish                         |
| GET  /results/{id}                            | GET /tests/{id}/results                         |
| GET  /api/question/{idx}                      | GET /questions/{id} (address by DB id now)      |
| POST /api/submit_answer                       | PUT /tests/{tid}/answers/{qid}                  |
| POST /api/mark_for_review                     | PUT /tests/{tid}/answers/{qid} (marked_for_review) |
| POST /api/flag_question                       | POST /questions/{id}/flag                       |
| POST /api/bookmark/{qid}                      | POST /questions/{id}/bookmark + DELETE          |
| POST /api/resolve_error                       | POST /errors/{id}/resolve                       |
| POST /api/redo_error                          | POST /errors/{id}/redo                          |
| POST /api/settings                            | PATCH /me/settings                              |
| POST /api/study_session                       | POST /study-sessions                            |
| POST /api/doubt/deep-dive                     | POST /questions/{id}/deep-dive                  |
| POST /api/doubt/chat                          | POST /questions/{id}/chat                       |
| GET  /review                                  | GET /review/queue                               |
| POST /api/review_answer                       | POST /review/answers/{error_id}                 |
| GET  /errorlog                                | GET /errors                                     |
| GET  /analytics                               | GET /analytics/mastery + heatmap + pacing + consistency + error-distribution + paper-performance (parallel calls) |
| GET  /bookmarks                               | GET /bookmarks                                  |
| GET  /search                                  | *client renders*                                |
| GET  /api/search                              | GET /search                                     |
| GET  /admin/                                  | GET /admin/stats                                |
| GET  /admin/flags                             | GET /admin/flags                                |
| POST /admin/api/flag/{id}/{action}            | POST /admin/flags/{id}/{action}                 |
| GET  /admin/review                            | GET /admin/review-queue                         |
| POST /admin/api/review/{qid}/{action}         | POST /admin/review-queue/{qid}/{action} + PATCH /admin/questions/{qid} for edit |
| GET  /admin/duplicates                        | GET /admin/duplicates                           |
| POST /admin/api/duplicate/disable/{qid}       | POST /admin/duplicates/{qid}/disable            |
| GET  /admin/synthesize                        | GET /admin/synthesize                           |
| POST /admin/api/synthesize/preview            | POST /admin/synthesize                          |
| GET  /admin/synthesize/{id}/preview           | GET /admin/synthesize/{id}                      |
| POST /admin/synthesize/{id}/commit            | POST /admin/synthesize/{id}/commit              |
| GET  /admin/questions                         | GET /admin/questions                            |
| GET  /admin/questions/{qid}/edit (form)       | *client renders*                                |
| POST /admin/questions/{qid}/edit              | PATCH /admin/questions/{qid}                    |
| POST /admin/api/question/{qid}/toggle_disabled| POST /admin/questions/{qid}/toggle-disabled     |
| POST /admin/api/question/{qid}/delete         | DELETE /admin/questions/{qid}                   |
| GET  /admin/topics                            | GET /admin/topics                               |
| POST /admin/topics                            | POST /admin/topics                              |
| POST /admin/topics/{tid}/delete               | DELETE /admin/topics/{tid}                      |
| GET  /admin/users                             | GET /admin/users                                |
| POST /admin/users                             | POST /admin/users                               |
| POST /admin/users/{uid}/update                | PATCH /admin/users/{uid}                        |
| GET  /admin/uploads                           | GET /admin/pdf-uploads                          |
| POST /admin/uploads                           | POST /admin/pdf-uploads (multipart)             |
| GET  /admin/uploads/{id}/preview              | GET /admin/pdf-uploads/{id}                     |
| POST /admin/uploads/{id}/import               | POST /admin/pdf-uploads/{id}/import             |
| GET  /admin/prompts                           | GET /admin/prompts                              |
| POST /admin/prompts                           | POST /admin/prompts + PATCH /admin/prompts/{name} |
| GET  /diag/{token}                            | (dropped — use /healthz)                        |
| POST /setup/seed/{token}                      | (dropped — use /auth/register + first-user promo) |

Row count: 50 Flask routes → ~90 v1 endpoints (mostly because
compound HTML routes decompose into multiple JSON endpoints).

---

## 10. Sample OpenAPI sketches

Three representative endpoints in OpenAPI 3.0.3 format (extracted from
what `utoipa` would emit) — useful for R3 codegen validation.

### 10.1 POST /auth/login

```yaml
paths:
  /api/v1/auth/login:
    post:
      tags: [auth]
      summary: Log in with email/username + password
      description: |
        Returns a short-lived JWT access token in the body and a
        long-lived opaque refresh token in an httpOnly cookie.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [identifier, password]
              properties:
                identifier:
                  type: string
                  description: Email OR username
                  example: kartik@example.com
                password:
                  type: string
                  format: password
                  minLength: 8
                  example: hunter2hunter2
      responses:
        '200':
          description: Login successful
          headers:
            Set-Cookie:
              schema:
                type: string
                example: refresh_token=RQE...; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth; Max-Age=2592000
          content:
            application/json:
              schema:
                type: object
                required: [user, access_token]
                properties:
                  user:
                    $ref: '#/components/schemas/User'
                  access_token:
                    type: string
                    description: JWT, 15-minute expiry
        '401':
          description: Invalid credentials
          content:
            application/json:
              schema: { $ref: '#/components/schemas/ErrorEnvelope' }
              example:
                error:
                  code: invalid_credentials
                  message: Email or password is incorrect.
                  request_id: 01J8QK4Z0X3H8XW5R6QTVMH2E4
        '429':
          description: Rate limited
          headers:
            Retry-After: { schema: { type: integer } }
          content:
            application/json:
              schema: { $ref: '#/components/schemas/ErrorEnvelope' }
```

### 10.2 POST /tests

```yaml
paths:
  /api/v1/tests:
    post:
      tags: [tests]
      summary: Create a new mock test
      security:
        - bearer_auth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [paper, num_questions]
              properties:
                paper:
                  type: string
                  enum: [I, II, both]
                num_questions:
                  type: integer
                  minimum: 1
                  maximum: 200
                topics:
                  type: string
                  description: Comma-separated topic ids. Empty = all.
                  example: "3,7,12"
                difficulty:
                  type: string
                  enum: [easy, medium, hard, all]
                  default: all
                focus_weak:
                  type: boolean
                  default: false
                test_mode:
                  type: string
                  enum: [practice, exam]
                  default: practice
                negative_ratio:
                  type: number
                  format: float
                  minimum: 0.0
                  maximum: 1.0
                  description: Only applied when test_mode == "exam"
                pyq_only:
                  type: boolean
                  default: false
                pyq_year_min: { type: integer, nullable: true }
                pyq_year_max: { type: integer, nullable: true }
      responses:
        '201':
          description: Test created
          content:
            application/json:
              schema:
                type: object
                required: [test_id, question_ids, total, test_mode,
                           negative_ratio, started_at]
                properties:
                  test_id: { type: integer, format: int64 }
                  question_ids:
                    type: array
                    items: { type: integer, format: int64 }
                  total: { type: integer }
                  test_mode: { type: string, enum: [practice, exam] }
                  negative_ratio: { type: number, format: float }
                  started_at: { type: string, format: date-time }
        '422':
          description: No questions matched the filter
          content:
            application/json:
              schema: { $ref: '#/components/schemas/ErrorEnvelope' }
              example:
                error:
                  code: no_questions_matched_filter
                  message: No questions match the selected filters. Loosen the filter and retry.
                  request_id: 01J...
                  details:
                    matched: 0
                    requested: 50
```

### 10.3 GET /review/queue

```yaml
paths:
  /api/v1/review/queue:
    get:
      tags: [review]
      summary: Fetch due SRS cards
      security:
        - bearer_auth: []
      parameters:
        - in: query
          name: limit
          schema: { type: integer, default: 100, maximum: 500 }
        - in: query
          name: box
          schema: { type: integer, minimum: 1, maximum: 5 }
      responses:
        '200':
          description: Due queue
          content:
            application/json:
              schema:
                type: object
                required: [cards, summary]
                properties:
                  cards:
                    type: array
                    items:
                      type: object
                      required: [error_id, question_id, question_text,
                                 sr_box, sr_due_at]
                      properties:
                        error_id: { type: integer, format: int64 }
                        question_id: { type: integer, format: int64 }
                        question_text: { type: string }
                        topic_name: { type: string }
                        sr_box: { type: integer, minimum: 1, maximum: 5 }
                        sr_due_at: { type: string, format: date-time }
                        if_ok_box: { type: integer }
                        if_ok_days: { type: integer }
                        if_no_box: { type: integer }
                        if_no_days: { type: integer }
                  summary:
                    type: object
                    properties:
                      due_today: { type: integer }
                      due_tomorrow: { type: integer }
                      by_box:
                        type: object
                        additionalProperties: { type: integer }

components:
  securitySchemes:
    bearer_auth:
      type: http
      scheme: bearer
      bearerFormat: JWT
  schemas:
    ErrorEnvelope:
      type: object
      required: [error]
      properties:
        error:
          type: object
          required: [code, message, request_id]
          properties:
            code: { type: string }
            message: { type: string }
            request_id: { type: string }
            details:
              type: object
              additionalProperties: true
    User:
      type: object
      required: [id, email, username, role, created_at]
      properties:
        id: { type: integer, format: int64 }
        email: { type: string, format: email }
        username: { type: string }
        display_name: { type: string, nullable: true }
        role: { type: string, enum: [user, admin] }
        created_at: { type: string, format: date-time }
        last_login: { type: string, format: date-time, nullable: true }
```

---

## 11. Open questions / decisions to lock

Before R3 (frontend) starts implementing the API client:

1. **Email transport for password reset** — Resend? Postmark? SES? (R5
   decides; doesn't block this doc, but the FE flow does need to know
   whether we email the token or show it in-app during dev).

2. **First-user auto-admin?** — R5's migration script will promote the
   first-registered user to `admin` (Kartik). Confirm; otherwise we
   ship a `POST /admin/promote/{user_id}` bootstrap endpoint gated on a
   one-time env-var token.

3. **`/api/v1` prefix in dev too?** — Yes for consistency. FE proxies
   through Vite in dev, so no CORS during local work.

4. **Deep-dive caching key** — currently `deep_dive:{qid}:{tid}`
   (per-test). Cross-user cache leak is fine (same LLM output for same
   question) — but R2 needs to confirm the `doubt_cache` table stays
   global, not per-user.

5. **Refresh cookie subdomain** — API on `api.exam-prep.pareek.dev`,
   FE on `exam-prep.pareek.dev`. Cookie set with `Domain=` unset →
   scoped to `api.` only, which is what we want (refresh only ever
   crosses that origin). Alternative: `Domain=.pareek.dev` — rejected
   as too broad.

6. **`PUT /tests/{tid}/answers/{qid}` conflict** — if question isn't in
   this test, we return 404. But question ids are visible in
   `GET /tests/{tid}` — could a malicious client PUT to a question not
   in the test? Yes, and we should 404, not silently ignore. Add
   integration test in R1's test plan.

7. **Study session write-through** — should `POST /study-sessions` also
   update `topic_mastery.study_hours` like the Flask version does
   (`bp_api.py:208`)? Recommend yes, same behaviour. Confirm.

8. **Admin PDF-upload async model** — Flask does it synchronously
   (blocks HTTP for ~30s during Claude extraction). Recommendation:
   fire-and-forget via a background task, poll via `GET /admin/pdf-
   uploads/{id}` — matches the schema `status` enum
   (`processing → extracted → imported | error`). Requires a background
   worker; R1 decides between `tokio::spawn` in-process and a proper
   queue. Simplest v1: in-process spawn, fine at solo-user scale.

---

## Report checklist for the caller

- ✅ REST vs GraphQL decision + justification (§1.1)
- ✅ Versioning scheme + compatibility contract (§1.2)
- ✅ OpenAPI toolchain (`utoipa` + `openapi-typescript` codegen) with
  a full sample handler declaration (§1.3)
- ✅ Full endpoint inventory covering every existing Flask route in
  `bp_*.py` (§3, §9.3)
- ✅ Auth flow: JWT access (15m) + rotating opaque refresh (30d) in
  httpOnly Path-scoped cookie, RBAC via role claim, argon2id,
  reuse-detection, deferred email verification (§2)
- ✅ Exact JWT claims (§2.1)
- ✅ Rate limiting: `tower-governor` with per-class limits (§6)
- ✅ CORS config for the split-origin FE (§7)
- ✅ Error envelope + status-code map + Rust `ApiError` sketch (§4)
- ✅ Pagination: cursor with opaque base64 payload (§5)
- ✅ Request-id + structured logging via `tracing` (§8)
- ✅ Three OpenAPI-style endpoint sketches (§10)
- ✅ Migration table from Flask routes to v1 endpoints (§9.3)
- ✅ Cross-refs to R1 (crate layout), R2 (user schema, doubt cache),
  R3 (FE codegen), R5 (deploy, CORS origin, email transport)
- ✅ Open questions escalated (§11)

_Doc length target: 700-1000 lines. Actual: ~940._
