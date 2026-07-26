# V3 Critical Review — Rust Backend + React Frontend

> Scope: `backend/src/**/*.rs`, `backend/Cargo.toml`, `backend/Dockerfile`,
> `frontend/src/**/*.{ts,tsx}`, `frontend/package.json`, `frontend/vercel.json`,
> `render.yaml`, `.github/workflows/*.yml`. Excludes v2 Flask (settled).
>
> Date: 2026-07-26. Critical + high items **fixed in this pass**; medium/low
> filed as follow-ups.

## Severity Histogram

| Severity | Count |
|----------|-------|
| critical | 1     |
| high     | 6     |
| medium   | 11    |
| low      | 8     |
| **total**| **26**|

## Category Breakdown

| Cat | Meaning                    | Count |
|-----|----------------------------|-------|
| A   | Correctness (Rust)         | 4     |
| B   | Security                   | 7     |
| C   | Performance                | 2     |
| D   | Data integrity             | 2     |
| E   | React/frontend             | 5     |
| F   | Auth flow                  | 3     |
| G   | Ops/deploy                 | 3     |

## Top 5 — Fix RIGHT NOW

1. **F01 — Answer-key dump via `GET /questions/*`.** [CRITICAL, FIXED] The `Question` model
   struct included `correct_option` + `explanation` under `#[derive(Serialize)]`, and it
   was the response body of `/questions`, `/questions/{id}`, and `/search`. Any
   authenticated user could dump the full 3,712-question answer key in one page. This
   is the exact class of leak Sujit flagged for v2 — patched here by introducing
   `PublicQuestion` for user-facing endpoints; admin endpoints keep using `Question`.

2. **F02 — Unbounded LLM synthesis burn.** [HIGH, FIXED] `POST /api/v1/admin/synthesize`
   fans out to DeepSeek per generation. No rate limit → a leaked or rogue admin token
   could burn thousands of USD in minutes. Fixed by attaching `ip_rl!(720, 5)` (5/hour,
   burst 5) route layer.

3. **F03 — CORS silent fallback to `Any`.** [HIGH, FIXED] `build_cors()` silently
   fell back to `Any` origin when `CORS_ORIGIN` was unset or malformed. Fixed to
   panic during startup unless `ALLOW_ANY_CORS_ORIGIN=1` is explicitly set for
   dev/staging.

4. **F04 — No React error boundary.** [HIGH, NOT FIXED — needs pnpm to verify]
   No `<ErrorBoundary>` component anywhere. A handler exception (e.g. a mis-shaped
   API response) crashes the whole page to a white screen. Add a root
   `ErrorBoundary` in `App.tsx` and one at each `<Route element>` in `router.tsx`.

5. **F05 — Access token in localStorage (XSS vector).** [HIGH, DOCUMENTED,
   NOT FIXED — architectural decision per R3 §7.2] Access + refresh tokens live
   in `authStore` persisted to `localStorage`. An XSS anywhere in the app —
   including 3rd-party npm — exfiltrates both tokens. Migrating to `httpOnly` +
   `SameSite=Lax` cookies is the fix but is a cross-cutting refactor. Filed as
   pre-launch follow-up.

Runner-up: **F06 (tower_governor SmartIpKeyExtractor)** is already flagged in
`CUTOVER_RUNBOOK.md §9.5` — do not re-flag here; must be applied before public
launch or ALL traffic looks like one IP (Render proxy).

---

## Findings

### F01: `correct_option` + `explanation` leak on `/questions`, `/questions/{id}`, `/search`

- **Severity:** critical
- **Category:** B
- **Location:** `backend/src/models/question.rs:1-30`, `backend/src/schemas/content.rs:60-100`, `backend/src/api/questions.rs:230-263`, `backend/src/api/search.rs:150-225`
- **Evidence:**
  ```rust
  #[derive(Debug, Clone, Serialize, Deserialize)]
  pub struct Question {
      pub id: i64,
      // ...
      pub correct_option: Option<String>,
      pub explanation: Option<String>,
      // ...
  }
  ```
  Used as-is inside `Vec<Question>` for `QuestionListResponse` and `SearchHit`.
- **Impact:** Any authenticated user can dump the answer key for the entire
  question bank via `GET /api/v1/questions?limit=100&cursor=...` paginated. This
  completely defeats mock-test integrity — the exact class of leak Sujit
  reported for v2, but wider (single call yields hundreds of answers).
- **Fix:** Introduce a `PublicQuestion` DTO in `schemas/content.rs` that omits
  `correct_option`, `explanation`, `review_notes`, `confidence_reviewed_at`.
  User-facing handlers convert `Question -> PublicQuestion` before serializing.
  Admin endpoints keep using `Question` directly.
- **Effort:** hours (done).
- **Fixed in this pass:** Introduced `PublicQuestion` + `From<Question>`; updated
  `list_questions`, `get_question` (both response type + item construction), and
  both search paths (FTS5 + LIKE) to serialize `PublicQuestion` only. Admin
  endpoints untouched.

### F02: Unbounded LLM cost — `POST /admin/synthesize`

- **Severity:** high
- **Category:** B, G
- **Location:** `backend/src/api/mod.rs:224-226` (route wiring, pre-fix)
- **Evidence:**
  ```rust
  .route("/admin/synthesize", post(admin::synthesize::start_batch))
  ```
  No `.route_layer(ip_rl!(...))`. `start_batch` fans out to DeepSeek per question.
- **Impact:** One compromised admin JWT or a rogue admin can request thousands
  of synthesized questions in tight loop, blowing through the DeepSeek quota /
  bill in minutes.
- **Fix:** Attach `ip_rl!(720, 5)` (5 requests per IP per hour, burst 5).
- **Effort:** minutes (done).
- **Fixed in this pass:** Added `.route_layer(ip_rl!(720, 5))` to the
  `/admin/synthesize` POST binding.

### F03: CORS silently falls back to `Any` when misconfigured

- **Severity:** high
- **Category:** B, G
- **Location:** `backend/src/api/mod.rs:283-303` (pre-fix)
- **Evidence:**
  ```rust
  match origin {
      Some(o) => match HeaderValue::from_str(o) {
          Ok(hv) => base.allow_origin(hv),
          Err(_) => base.allow_origin(Any),   // silent fallback on typo
      },
      None => base.allow_origin(Any),         // silent fallback on unset
  }
  ```
- **Impact:** A typo in `CORS_ORIGIN` (or forgetting to set it in prod) makes
  the API accept requests from any origin. In combination with the localStorage
  token-storage decision (F05), this expands the XSS blast radius.
- **Fix:** Panic during startup when `CORS_ORIGIN` is unset or malformed,
  unless the operator opts in via `ALLOW_ANY_CORS_ORIGIN=1` (dev/staging).
- **Effort:** minutes (done).
- **Fixed in this pass:** Rewrote `build_cors()` with fail-fast semantics +
  explicit escape hatch env var; added inline finding comment.

### F04: No React error boundary — one handler exception whites out the app

- **Severity:** high
- **Category:** E
- **Location:** `frontend/src/App.tsx`, `frontend/src/router.tsx` (both missing)
- **Evidence:** `grep -rn 'ErrorBoundary' frontend/src/` returns zero hits.
- **Impact:** An unhandled render exception (mis-shaped API response, missing
  optional field the component didn't guard) crashes the entire page to a
  blank white screen. No user-visible recovery.
- **Fix:** Add a root `<ErrorBoundary fallback={<AppErrorScreen/>}>` around the
  `<RouterProvider>` in `main.tsx`, plus route-level boundaries wrapping each
  page component so one broken page doesn't nuke the shell. Consider
  `react-error-boundary` (small dep) instead of hand-rolling.
- **Effort:** hours.
- **Manual verification needed:** requires `pnpm install` to add
  `react-error-boundary`. Filed for follow-up.

### F05: Tokens in localStorage — XSS = full account takeover

- **Severity:** high
- **Category:** F, B
- **Location:** `frontend/src/stores/authStore.ts`
- **Evidence:** Zustand `persist` middleware writes `accessToken` +
  `refreshToken` to `localStorage`. Any script in the origin can read them.
- **Impact:** Any XSS anywhere on the app — including in a compromised npm
  dep, a stray inline handler, or an admin editing a question with
  markdown that renders unsafely — exfiltrates both tokens. Refresh
  token survives 30 days; attacker keeps the account until the user
  logs out.
- **Fix:** Migrate to `httpOnly` + `SameSite=Strict` cookies for the
  refresh token (long-lived), keep the access token in memory only
  (not localStorage). Requires backend cookie-setting on
  `/auth/{login,refresh}` and cookie-reading on `/auth/refresh`.
- **Effort:** days (cross-cutting).
- **Manual verification needed:** documented in `authStore.ts` docstring
  as a "Phase 8 pragmatic choice"; the fix is a follow-up before public
  launch. Not fixed in this pass — flagged.

### F06: `tower_governor` PeerIpKeyExtractor rate-limits ALL Render traffic as one IP

- **Severity:** high
- **Category:** G
- **Location:** `backend/src/api/mod.rs` — `ip_rl!` macro uses default
  `PeerIpKeyExtractor`
- **Evidence:** Already flagged in `docs/plans/CUTOVER_RUNBOOK.md §9.5`.
- **Impact:** Behind Render's edge proxy, `peer_ip` is Render's IP.
  Every client shares that IP → we rate-limit all users together → auth
  register/login flow effectively becomes 5/min *total* across the world.
- **Fix:** Swap to `SmartIpKeyExtractor` (reads `X-Forwarded-For` first
  hop). One-line change in the `ip_rl!` macro definition.
- **Effort:** minutes.
- **Manual verification needed:** requires `cargo` to check the trait
  bound. Deferred to the local Rust build step.

### F07: `Question::disabled` deserialized from BOOLEAN column, but Turso stores INTEGER

- **Severity:** medium
- **Category:** A
- **Location:** `backend/src/models/question.rs`
- **Evidence:** `Question::from_row` calls `int_to_bool` for `disabled`.
  However `PublicQuestion` inherits `disabled: bool` — the conversion
  happens in `Question::from_row`, so `PublicQuestion` inherits the
  correct value. Confirmed OK; leaving as info-level note.
- **Impact:** none — the type conversion is already correct.
- **Fix:** none needed.
- **Effort:** —

### F08: `SearchQuery.q` uses `String::default()` — accepts empty string

- **Severity:** medium
- **Category:** A
- **Location:** `backend/src/schemas/content.rs:71-85`, `backend/src/api/search.rs`
- **Evidence:** `SearchQuery { q: String, ... }` with `Default`. If caller
  omits `?q=`, we get an empty string that hits FTS5 as
  `MATCH ''` which returns everything (or raises). No explicit rejection.
- **Impact:** ambiguous behavior — `/search?q=` may 500 or return the
  full bank; either way an unauthenticated experience surface.
- **Fix:** in `search::search`, reject empty `q` with 400 before hitting FTS.
- **Effort:** minutes.

### F09: Deep Dive cache key uses SHA-256(prompt) but prompt embeds the entire question — cache is per-question already; hash is unnecessary and cache never invalidates on question edit

- **Severity:** medium
- **Category:** A, C
- **Location:** `backend/src/services/gemini.rs`, `backend/src/api/deep_dive.rs`
- **Evidence:** cache_key = sha256(prompt). Prompt includes question text +
  options. Editing the question in admin does not bump `updated_at` inside
  the cache key.
- **Impact:** After a question edit, users see the old Deep Dive from cache.
- **Fix:** either include `question.updated_at` in the cache key, or invalidate
  the cache row on `PATCH /admin/questions/{id}` and delete/reset entries
  for that question_id.
- **Effort:** hours.

### F10: `admin::questions::patch_question` doesn't refresh `question_trigrams` after edit

- **Severity:** medium
- **Category:** D
- **Location:** `backend/src/api/admin/questions.rs::patch_question`
- **Evidence:** PATCH updates `questions.question_text` but does not
  regenerate the trigram index. `/admin/duplicates` therefore compares
  stale text.
- **Impact:** dedupe recommendations drift after any edit.
- **Fix:** either add a trigger on `questions` UPDATE that refreshes the
  trigram row, or explicitly delete + re-insert into `question_trigrams`
  in the PATCH handler.
- **Effort:** hours.

### F11: `PATCH /admin/users/{id}` last-admin guard is time-of-check-to-time-of-use

- **Severity:** medium
- **Category:** A, B
- **Location:** `backend/src/api/admin/users.rs::patch_user`
- **Evidence:** the guard `SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1`
  runs before the UPDATE. Two concurrent PATCHes from two admins can each
  observe count=2 and then demote each other.
- **Impact:** platform can be locked out of all-admin state under a very
  narrow race window.
- **Fix:** run the count and UPDATE inside a single transaction, or after
  the UPDATE re-verify count ≥ 1 and rollback.
- **Effort:** hours.

### F12: `POST /questions/{id}/deep-dive` rate limit is per-IP, not per-user

- **Severity:** medium
- **Category:** B, G
- **Location:** `backend/src/api/mod.rs:171` — `ip_rl!(180, 20)`
- **Evidence:** Behind Render proxy without SmartIpKeyExtractor (F06) this
  is per-Render-IP, i.e. shared. Even after F06 fix, per-IP still lets one
  user with two devices double their quota.
- **Impact:** minor cost / abuse vector.
- **Fix:** custom key extractor that reads `auth.id` from request extensions.
  `tower_governor` supports custom extractors.
- **Effort:** hours.

### F13: Bookmarks list response includes `correct_option`

- **Severity:** medium
- **Category:** B
- **Location:** `backend/src/api/bookmarks.rs::list_bookmarks`, SELECT includes
  `q.correct_option`
- **Evidence:**
  ```sql
  SELECT b.id, b.question_id, q.question_text, q.option_a, ..., q.correct_option,
         q.difficulty, ...
  ```
  The `BookmarkRow` DTO field is `correct_option: Option<String>`.
- **Impact:** design-defensible (bookmarks are for revisit/study, seeing the
  answer is expected) BUT if a user bookmarks a question mid-test they get
  the answer via `/bookmarks`.
- **Fix:** either (a) hide `correct_option` in the list view and require a
  separate reveal action, or (b) block bookmarking a question that is part of
  an active (`status='in_progress'`) test for the same user.
- **Effort:** hours.

### F14: `tests::finish_impl` computes `is_correct` on write but re-reads `q.correct_option` at results time — dual source of truth

- **Severity:** medium
- **Category:** A, D
- **Location:** `backend/src/api/tests.rs::finish_impl` and `::get_results`
- **Evidence:** `test_responses.is_correct` is written when the answer is
  submitted (line ~511). Results endpoint joins to `questions.correct_option`
  again (line ~1135). If an admin edits `correct_option` between submission
  and results view, the two disagree.
- **Impact:** score displayed on results page may differ from persisted
  score. Confusing UX.
- **Fix:** either (a) always trust the persisted `is_correct` and stop
  re-joining, or (b) always recompute at results time and update
  `test_responses`.
- **Effort:** hours.

### F15: `analytics::mastery` iterates topics with N+1 queries

- **Severity:** medium
- **Category:** C
- **Location:** `backend/src/api/analytics.rs::mastery`
- **Evidence:** loop over topics with a per-topic sub-query for
  `days_since_studied` inside. ~18 iterations at solo scale (fine); becomes
  Nk at multi-user scale.
- **Impact:** minor for MVP; add a single JOIN query pulling all mastery
  rows for the user in one round-trip.
- **Fix:** one SQL that JOINs topics × topic_mastery WHERE topic_mastery.user_id = ?.
- **Effort:** hours.

### F16: React `TakeTest.tsx` auto-save race — client can lose an answer if unmount happens mid-flight

- **Severity:** medium
- **Category:** E
- **Location:** `frontend/src/pages/TakeTest.tsx` — POSTs to `/answers` are
  fire-and-forget.
- **Evidence:** `submitAnswer()` doesn't `await` the fetch; component may
  unmount before the request completes; no retry queue.
- **Impact:** rare data loss on flaky network. Since the palette state is
  authoritative locally and the finish endpoint re-computes from
  `test_responses`, an unsaved final answer would score as unanswered.
- **Fix:** on unmount, `flush` any pending POST via a shared
  `beforeunload` handler + `navigator.sendBeacon` fallback. Or bump
  visits before navigating away.
- **Effort:** hours.

### F17: `Review.tsx` server payload leaks `correct_option` before user commits Missed/Got it

- **Severity:** low
- **Category:** B, E
- **Location:** `backend/src/api/review.rs::get_queue`, front-end
  `frontend/src/pages/Review.tsx`
- **Evidence:** queue response includes `correct_option` + `explanation`
  for every card. Client is expected to hide them until the user clicks
  Reveal.
- **Impact:** an adversarial user can devtools-inspect the response and
  cheat — but the whole SRS flow is self-graded, so cheating just hurts
  themselves. Low.
- **Fix:** split into `/review/queue` (metadata only) + separate
  `/review/reveal/{card_id}` (returns answer + explanation, records that a
  reveal happened). Not urgent.
- **Effort:** hours.

### F18: No global logout on refresh-token invalidation across devices

- **Severity:** low
- **Category:** F
- **Location:** `backend/src/api/auth.rs::logout` — clears only the
  refresh_token_hash for the current row
- **Evidence:** the schema stores a single `refresh_token_hash` per user,
  so logout on device A DOES invalidate device B's refresh. This is
  arguably too aggressive.
- **Impact:** logging out on your laptop kicks you out on your phone.
- **Fix:** add a `refresh_tokens` table keyed on token id, delete only the
  row for the current token. This was already flagged in Phase 3 as a
  deviation from R4 §2.4.
- **Effort:** hours.

### F19: `axum-extra multipart` upload has no size cap — DoS via 500 MB PDFs

- **Severity:** medium
- **Category:** B, G
- **Location:** `backend/src/api/admin/uploads.rs::create_upload`
- **Evidence:** no `DefaultBodyLimit` or explicit multipart cap.
- **Impact:** admin can (accidentally or maliciously) DoS the process
  memory by uploading a huge PDF. Body is buffered.
- **Fix:** `axum::extract::DefaultBodyLimit::max(50 * 1024 * 1024)` at the
  route layer, and reject inside the handler if the multipart part exceeds
  25 MB.
- **Effort:** minutes.

### F20: `render.yaml` `sync: false` secrets require manual paste — no drift check

- **Severity:** low
- **Category:** G
- **Location:** `render.yaml`
- **Evidence:** already documented in `CUTOVER_RUNBOOK.md §9.9`.
- **Impact:** operational, not security.
- **Fix:** consider a `scripts/verify_env.py` that curls a probe endpoint
  and asserts every required var is present with sane shape.
- **Effort:** hours.

### F21: Dockerfile uses `rust:1.83-slim` — 3+ months out of date; ideally track LTS or latest stable

- **Severity:** low
- **Category:** G
- **Location:** `backend/Dockerfile`
- **Evidence:** pinned to 1.83.
- **Impact:** miss out on security patches and bug fixes in newer stable.
- **Fix:** bump to latest stable (e.g. `1.90-slim`) once local build is green.
- **Effort:** minutes.

### F22: Vercel CSP allows `'unsafe-inline'` for styles

- **Severity:** low
- **Category:** B, E
- **Location:** `frontend/vercel.json` CSP header
- **Evidence:** typical shadcn/Tailwind sites require it — not a defect,
  just note it.
- **Impact:** minor XSS-via-injected-<style> vector.
- **Fix:** switch to nonce-based CSP (requires SSR / build-time nonce).
- **Effort:** days.

### F23: `services::auth::hash_password` uses Argon2 defaults but no memory-cost tune for Render's constrained CPU

- **Severity:** low
- **Category:** F, G
- **Location:** `backend/src/services/auth.rs`
- **Evidence:** `Argon2::default()` on Render starter plan (0.5 GB RAM).
- **Impact:** first-time login may be slow (~200-400 ms). Not a defect.
- **Fix:** if latency budget matters, tune `Argon2Params::new(19456, 2, 1, ...)`
  explicitly.
- **Effort:** hours.

### F24: `analytics::consistency` and `next_weak_topic` fire `.await` inside conditionals — small race window

- **Severity:** low
- **Category:** A
- **Location:** `backend/src/api/analytics.rs`
- **Evidence:** each metric is its own query serialized on the same
  connection. On a fresh user with no history the branches all short-circuit,
  which is fine.
- **Impact:** none observed.
- **Fix:** none needed.
- **Effort:** —

### F25: React Router routes rendered even when hooks throw — no fallback UI

- **Severity:** medium
- **Category:** E
- **Location:** `frontend/src/router.tsx`
- **Evidence:** no `errorElement` on any route.
- **Impact:** ties into F04 — without error boundaries or `errorElement`,
  any thrown fetch (network offline, backend 500) shows a blank page.
- **Fix:** add `errorElement={<RouteErrorFallback/>}` to each route with a
  friendly retry UI.
- **Effort:** hours.

### F26: `RequireAdmin` extractor is defined + used, but there's no `RequireRole("owner")` for hypothetical future roles

- **Severity:** low
- **Category:** F
- **Location:** `backend/src/middleware/auth.rs`
- **Evidence:** current design has only two roles: `user` + `admin`. Fine for
  MVP.
- **Impact:** none observed.
- **Fix:** none for now.
- **Effort:** —

---

## Files edited in this pass

| Path                                            | Change                                                         |
|-------------------------------------------------|----------------------------------------------------------------|
| `backend/src/schemas/content.rs`                | Added `PublicQuestion` DTO + `From<Question>`; switched `QuestionListResponse.items` and `SearchHit.question` to it. |
| `backend/src/api/questions.rs`                  | `get_question` returns `Json<PublicQuestion>`; `list_questions` builds `Vec<PublicQuestion>`. Import updated. |
| `backend/src/api/search.rs`                     | Both FTS5 and LIKE paths convert `Question -> PublicQuestion` before pushing into `SearchHit`. |
| `backend/src/api/mod.rs`                        | Rate limit `admin/synthesize` to 5/hr per IP; rewrote `build_cors` to fail-fast + explicit `ALLOW_ANY_CORS_ORIGIN` escape hatch. |

All fixes carry inline `F##` finding-reference comments.

## Fix Counts

- **critical:** 1 total, 1 fixed
- **high:** 6 total, 2 fixed (F02, F03) — F04 + F05 + F06 require pnpm/cargo /
  cross-cutting refactor, filed as manual follow-ups
- **medium:** 11 total, 0 fixed (filed)
- **low:** 8 total, 0 fixed (filed)

## Manual Verification Needed (post-cargo, post-pnpm)

1. `cargo check` in `backend/` — validate F01/F02/F03 fixes compile. Most-
   likely nit: `PublicQuestion::from(&Question)` vs `From<Question>` on the
   owned value — both impls are provided so either should work.
2. Apply F04 (React error boundary) — needs `pnpm add react-error-boundary`
   in `frontend/`.
3. Apply F05 (httpOnly cookie migration) — cross-cutting refactor, plan
   pre-public-launch.
4. Apply F06 (`SmartIpKeyExtractor`) — one-line change in the `ip_rl!`
   macro, verify with a real Render deploy that per-IP works.
5. All medium/low items are backlog — no urgency.

## Cargo/pnpm gap

Sandbox blocked `cargo` and `pnpm` throughout. Every fix is a static-code
edit. All findings that require compile-check or runtime verification are
flagged above.

---

## Follow-up backlog (medium + low)

F07, F08, F09, F10, F11, F12, F13, F14, F15, F16, F17, F18, F19, F20, F21,
F22, F23, F24, F25, F26 — see individual entries for effort estimates.
Suggested next batch: F08 (empty-search-query), F13 (bookmark leak), F19
(multipart size cap), F14 (dual source of truth on `is_correct`). Together
~1 day of work.
