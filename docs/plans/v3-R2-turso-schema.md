# v3 R2 — Turso libSQL from Rust + Multi-User Schema Migration

**Status:** planning only. No SQL executes as a result of this document.
**Depends on:** R1 (Rust framework selection). Concrete answer influences
which query builder is idiomatic — see §2. If R1 lands on axum + tokio,
the choice in §2 is unambiguous; if R1 picks actix-web or a sync stack the
tradeoffs shift and this doc will need a follow-up patch.
**Scope in one sentence:** pick a Rust libSQL client + query layer, design
the multi-user ALTER + backfill sequence that adds `user_id` to seven
per-user tables without losing the 3,712 existing questions, and decide
how migrations are managed from here on.

---

## 0. Current-state summary (what R2 has to preserve)

Read from `db.py`, `turso_patch.py`, `scripts/migrate_*.py`.

- Turso libSQL (Hrana v2 HTTP on `/v2/pipeline`). Python talks to it via
  `turso_patch.py` which monkey-patches `sqlite3.connect`. Commits are
  no-ops — Hrana auto-commits per pipeline.
- 17 physical tables + 1 FTS5 virtual table (`questions_fts`, 3 triggers).
- 21 columns on `questions`: base 12 + `disabled`, `updated_at`,
  `confidence`, `section`, `sub_topic`, `pyq_exam`, `pyq_year`,
  `review_notes`, `confidence_reviewed_at`.
- 3,712 questions. All existing `mock_tests`, `test_responses`,
  `error_log`, `topic_mastery`, `study_sessions`, `bookmarks`,
  `question_flags` rows belong logically to `users.id = 1`.
- `users` already exists (id, username, password_hash, role, is_active,
  created_at, last_login). Schema is multi-user-ready; the seven usage
  tables are not.
- Hrana quirks: `PRAGMA` rejected with `SQL_PARSE_ERROR`; per-statement
  errors come back inside HTTP 200 (must inspect `results[]`); integers
  arrive as strings; batches chunk in 50s to stay under payload limits.

---

## 1. Rust libSQL client — recommendation: **`libsql` (official crate)**

### 1.1 Candidates

| Option | Version @ 2026-01 | Maintained by | Verdict |
|---|---|---|---|
| `libsql` | 0.6.x+ | Turso Inc (upstream) | **Pick this** |
| `libsql-client-rs` | 0.33 (2024) | community, archived direction | Reject |
| Raw HTTP (reqwest → `/v2/pipeline`) | n/a | us | Reject except for one-off tooling |

### 1.2 Why `libsql`

1. **First-party.** Turso ships it; every server-side protocol change lands
   here first. `libsql-client-rs` was community-owned and Turso has since
   redirected effort into the official crate; using the old one means we
   own the porting cost for every Hrana bump.
2. **Three transport modes in one API.** The same `libsql::Builder` gives
   you (a) `new_remote(url, token)` — pure HTTP, what we do today from
   Python; (b) `new_remote_replica(local_path, url, token)` — embedded
   replica with periodic sync (huge win for read-heavy queries; see §8);
   (c) `new_local(path)` — plain SQLite for tests. Same `Connection` trait
   surface across all three, so integration tests can hit local SQLite and
   prod hits remote without conditional compilation.
3. **Streaming rows via `Rows::next()`.** Unlike our current `TC` which
   materialises the whole result vector, the `libsql` crate exposes a
   cursor-style iterator. Matters when we start doing 3k-row analytics
   queries during grading.
4. **Transactions work over Hrana.** `conn.transaction().await?` opens a
   `BEGIN…COMMIT` and pipelines it. Our Python adapter fakes commit/rollback
   (`turso_patch.py:218-222`) — Rust gets the real thing.
5. **Prepared statements.** `conn.prepare(sql).await?` yields a `Statement`
   we can bind + execute repeatedly. Hrana v2 supports named args
   (`turso_patch.py::_build_stmt` shows the shape); the crate handles it.
6. **TLS on Render.** The crate uses `rustls` by default with the
   `webpki-roots` bundle — no system CA store needed. Render's rootfs
   has an up-to-date CA bundle anyway, but bundled roots means we won't
   inherit an outage if the base image goes stale.

### 1.3 What we lose vs raw HTTP

- Slightly slower cold start (~30 ms extra vs a naked reqwest POST) because
  the crate does a `GET /health` on first use to negotiate the Hrana version.
  Not a factor for a server that stays warm.
- One extra dep + its transitive tree (~4 MB compiled). Acceptable.

### 1.4 Connection pooling

`libsql` does **not** expose a connection pool. The remote connection is
essentially stateless (each `execute` is an HTTP round trip; there is no
long-lived socket to keep warm), so pooling is more about limiting
concurrency than reusing sockets.

Two options:
- **`bb8` + a hand-rolled `libsql` manager.** Standard async pool crate,
  works with any `Send + Sync` resource. ~50 lines of glue.
- **Skip the pool, share one `Arc<libsql::Connection>` across the app.**
  Actually correct here — the crate uses reqwest internally and reqwest's
  `Client` already has an internal HTTP connection pool. Wrapping it in
  bb8 would just add a second semaphore on top.

**Recommendation:** one `Arc<libsql::Connection>` in app state, rely on
reqwest's HTTP pool underneath. Cap concurrent DB futures with a
`tokio::sync::Semaphore(32)` in the request handler layer so a burst of
requests can't fan out into 200 concurrent Hrana calls and trip Turso's
rate limit (see §8).

### 1.5 TLS on Render

- Build with `libsql = { version = "0.6", features = ["remote"] }`.
- No extra config needed. Render's Rust builder image has a modern glibc
  + OpenSSL, but `libsql` uses rustls so neither is on the hot path.
- If Render's outbound firewall ever blocks a Turso hostname, the failure
  mode is a clean `libsql::Error::Hrana` — surface it via 503 in the
  handler.

---

## 2. Query builder — recommendation: **SQLx-style compile-time queries are OFF the table; use raw SQL through `libsql` with a thin repository layer**

### 2.1 Why not SQLx

SQLx does not support libSQL. Its compile-time checker requires a live
database connection during `cargo build` (or an offline `sqlx-data.json`
prepared from a live connection) — and its driver list is Postgres,
MySQL, SQLite (via `libsqlite3-sys`), MSSQL. Its SQLite driver talks to
a local file via FFI; it will not talk to Turso remote.

You could technically point `sqlx::sqlite` at an embedded replica file
that `libsql` syncs in the background. That doubles the drivers, doubles
the type-mapping code, and leaves you with a race where SQLx reads a
row before `libsql` has synced it. Reject.

### 2.2 Why not Diesel

Same problem — Diesel's SQLite backend is FFI to libsqlite3, not libSQL.
Plus Diesel's builder syntax is inflexible for the shape of query we
actually write (dynamic filter chains for `bp_review.py`-style flag/topic
filters, `questions_fts MATCH ?` full-text queries the Diesel DSL can't
express, window functions in analytics). Reject.

### 2.3 Why not `sea-query` / `sea-orm`

`sea-query` (a builder crate independent of `sea-orm`) technically works
with any driver — it just emits SQL strings + parameter vectors that you
hand to `libsql`. Tempting. But:
- Our SQL is already written (see all `bp_*.py` files). Rewriting 200+
  queries into a builder DSL is high-risk, low-reward.
- FTS5 `MATCH` is not modeled by any Rust query builder cleanly.
- We already have `PRAGMA table_info` introspection scripts that expect
  raw SQL.

### 2.4 Pick: raw SQL + repository pattern

Write a thin repository layer:

```rust
// src/db/mod.rs
pub struct Db {
    conn: Arc<libsql::Connection>,
}

impl Db {
    pub async fn connect(url: &str, token: &str) -> Result<Self> {
        let db = libsql::Builder::new_remote(url.into(), token.into())
            .build()
            .await?;
        Ok(Self { conn: Arc::new(db.connect()?) })
    }
}

// src/db/questions.rs
pub struct QuestionsRepo<'a> { db: &'a Db }

impl<'a> QuestionsRepo<'a> {
    pub async fn by_id(&self, id: i64) -> Result<Option<Question>> { … }
    pub async fn search(&self, q: &str, limit: i64) -> Result<Vec<Question>> { … }
    // …
}
```

Benefits:
- SQL lives in Rust string literals — grep-able, matches what `db.py`
  looks like today.
- Compile-time safety comes from `serde` on the return structs, not from
  parsing SQL.
- Every method takes/returns concrete typed structs (§9), so callers
  can't accidentally drop a column.

Cost:
- No compile-time schema validation. Mitigate with an integration test
  that runs every query against a local SQLite in-memory DB seeded with
  the same schema — catches column-name typos in CI.

**If R1 picks a non-tokio stack (e.g. actix's sync executors),** the same
repository pattern works; swap `libsql::Connection` for the sync API on
the same crate. Everything else in this doc stands.

---

## 3. Multi-user schema migration — the big one

### 3.1 Tables that need `user_id`

Confirmed by reading `db.py`:

| Table | Owns rows per-user? | Existing rows (assumption) |
|---|---|---|
| `mock_tests` | yes | belong to user 1 |
| `test_responses` | yes (via `test_id`) | belong to user 1 |
| `error_log` | yes | belong to user 1 |
| `topic_mastery` | yes (UNIQUE per user × topic) | belong to user 1 |
| `study_sessions` | yes | belong to user 1 |
| `bookmarks` | yes | belong to user 1 |
| `question_flags` | yes (reporter) | belong to user 1 |

Tables that stay global (no `user_id`):
- `questions`, `topics`, `settings`, `doubt_cache`, `question_trigrams`,
  `pdf_uploads`, `master_prompts`, `synthesis_batches`, `questions_fts`.
- `pdf_uploads.uploaded_by` is already a `TEXT` username string — can
  remain that way or migrate to `user_id`; deferring, it's admin-only
  content anyway.

### 3.2 Design constraints

- `ALTER TABLE ADD COLUMN` in libSQL cannot add a `NOT NULL` column
  without a `DEFAULT`, and cannot add a `REFERENCES` constraint that
  fails on existing rows. Same as SQLite mainline.
- Therefore add `user_id` as **nullable at first**, backfill, then
  (optionally) rebuild the table via CTAS if we want a hard `NOT NULL`
  constraint. Realistically we skip the CTAS and enforce non-null in
  application code (Rust type is `i64`, not `Option<i64>`) — see §4.
- Turso does not support `ALTER TABLE … RENAME TO` inside a transaction
  atomically with `CREATE TABLE … AS SELECT` across the network; keep
  each ALTER as its own pipeline request.
- `IF NOT EXISTS` on ADD COLUMN does not exist in libSQL. Use PRAGMA
  introspection to skip already-present columns (pattern from the
  existing migrate scripts).

### 3.3 ALTER + backfill sequence (exact SQL)

Run in order. Each block is one Hrana pipeline. All idempotent guards
are omitted from this snippet for readability — the real migration
script will wrap each ALTER in a `PRAGMA table_info` check.

```sql
-- ============================================================
-- v3 R2 multi-user migration — additive only, no data loss
-- ============================================================

-- ---- mock_tests ----
ALTER TABLE mock_tests ADD COLUMN user_id INTEGER REFERENCES users(id);
UPDATE mock_tests SET user_id = 1 WHERE user_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_mock_tests_user_started
    ON mock_tests(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_mock_tests_user_status
    ON mock_tests(user_id, status);

-- ---- test_responses ----
ALTER TABLE test_responses ADD COLUMN user_id INTEGER REFERENCES users(id);
UPDATE test_responses SET user_id = 1 WHERE user_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_test_responses_user_test
    ON test_responses(user_id, test_id);
CREATE INDEX IF NOT EXISTS idx_test_responses_user_question
    ON test_responses(user_id, question_id);

-- ---- error_log ----
ALTER TABLE error_log ADD COLUMN user_id INTEGER REFERENCES users(id);
UPDATE error_log SET user_id = 1 WHERE user_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_error_log_user_due
    ON error_log(user_id, sr_due_at);
CREATE INDEX IF NOT EXISTS idx_error_log_user_topic
    ON error_log(user_id, topic_id);
CREATE INDEX IF NOT EXISTS idx_error_log_user_resolved
    ON error_log(user_id, resolved);

-- ---- topic_mastery ----
-- The existing UNIQUE(topic_id) constraint blocks multi-user rows.
-- Rebuild the table via CTAS so we can drop the old constraint and
-- add UNIQUE(user_id, topic_id).
CREATE TABLE topic_mastery_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    topic_id INTEGER REFERENCES topics(id),
    diagnostic_score REAL,
    current_score REAL,
    study_hours REAL DEFAULT 0,
    status TEXT DEFAULT 'not_started',
    last_studied TEXT,
    test_count INTEGER DEFAULT 0,
    UNIQUE(user_id, topic_id)
);
INSERT INTO topic_mastery_new
    (id, user_id, topic_id, diagnostic_score, current_score, study_hours,
     status, last_studied, test_count)
SELECT id, 1, topic_id, diagnostic_score, current_score, study_hours,
       status, last_studied, test_count
FROM topic_mastery;
DROP TABLE topic_mastery;
ALTER TABLE topic_mastery_new RENAME TO topic_mastery;
CREATE INDEX IF NOT EXISTS idx_topic_mastery_user
    ON topic_mastery(user_id);

-- ---- study_sessions ----
ALTER TABLE study_sessions ADD COLUMN user_id INTEGER REFERENCES users(id);
UPDATE study_sessions SET user_id = 1 WHERE user_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_study_sessions_user_date
    ON study_sessions(user_id, date DESC);

-- ---- bookmarks ----
-- The current UNIQUE(question_id) index prevents two users bookmarking
-- the same question. Drop it, add composite UNIQUE.
DROP INDEX IF EXISTS idx_bookmarks_qid;
ALTER TABLE bookmarks ADD COLUMN user_id INTEGER REFERENCES users(id);
UPDATE bookmarks SET user_id = 1 WHERE user_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_bookmarks_user_question
    ON bookmarks(user_id, question_id);

-- ---- question_flags ----
-- `reporter TEXT` was the username string. Add user_id and backfill
-- from the string → users.id mapping. Keep `reporter` around during
-- coexistence for the Python code that still reads it; drop later.
ALTER TABLE question_flags ADD COLUMN user_id INTEGER REFERENCES users(id);
UPDATE question_flags
   SET user_id = (SELECT id FROM users WHERE users.username = question_flags.reporter)
 WHERE user_id IS NULL AND reporter IS NOT NULL;
-- Rows with no matching username → assign to admin (user 1).
UPDATE question_flags SET user_id = 1
 WHERE user_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_question_flags_user_status
    ON question_flags(user_id, status);
```

### 3.4 Rollback

Rollback for additive ALTERs = ignore the column (Python code that
doesn't SELECT `user_id` keeps working). For the `topic_mastery` CTAS
we need a real backup — this is why §5 mandates the Turso dump before
step 1.

### 3.5 Order-of-operations gotcha

Run the ALTERs *before* deploying any Rust code that expects the column.
Coexistence window: old Python app reads/writes without `user_id`,
inserts leave `user_id` NULL, Rust app treats NULL as user 1 during the
transition (or we do a nightly `UPDATE … SET user_id = 1 WHERE user_id
IS NULL` cron until the Python app is retired).

### 3.6 The `test_responses.user_id` — arguably redundant?

`test_responses.test_id` already points at `mock_tests(id)`, and
`mock_tests.user_id` will exist. A pure normalisation view says
`test_responses.user_id` is derivable.

Add it anyway. Reasons:
- Every analytics query joins on user; carrying `user_id` inline saves a
  join and a compound-index lookup on `mock_tests`.
- Row-level isolation checks (§4) get simpler — one `WHERE user_id = ?`
  filter, not a subquery.
- 3,712 questions × N users won't make `test_responses` big enough for
  storage of one extra int per row to matter.

---

## 4. Data isolation query pattern

Every user-scoped SELECT must include `WHERE user_id = ?`. Enforce
mechanically, not by memory.

### 4.1 The repository trick — `UserScoped<Db>` wrapper

```rust
/// A DB handle scoped to one user. Constructed by auth middleware
/// exactly once per request. Every repo method takes `&self` on this
/// wrapper and injects the user_id automatically.
#[derive(Clone)]
pub struct UserDb {
    inner: Arc<libsql::Connection>,
    pub user_id: i64,
}

impl UserDb {
    /// Only callable by the auth middleware. There is no `pub` way to
    /// construct one otherwise — enforced at module boundary.
    pub(crate) fn from_middleware(conn: Arc<libsql::Connection>, uid: i64) -> Self {
        Self { inner: conn, user_id: uid }
    }
}

/// Repos over `UserDb` cannot forget the user filter:
pub struct MockTestsRepo<'a> { db: &'a UserDb }

impl<'a> MockTestsRepo<'a> {
    pub async fn recent(&self, limit: i64) -> Result<Vec<MockTest>> {
        let sql = "SELECT * FROM mock_tests
                    WHERE user_id = ?
                    ORDER BY started_at DESC LIMIT ?";
        let mut rows = self.db.inner.query(sql, (self.db.user_id, limit)).await?;
        // …
    }
}
```

### 4.2 The escape hatch — `AdminDb` for cross-user queries

```rust
/// Constructed only from the admin middleware. Explicitly does NOT
/// scope by user. Used for the admin panel + analytics rollups.
pub struct AdminDb(Arc<libsql::Connection>);
```

Naming makes the intent visible in every handler signature — a route
that takes `UserDb` cannot leak into another user's data; a route that
takes `AdminDb` requires an admin token, which auth middleware enforces.

### 4.3 CI safety net

Grep-based lint in CI: for every `SELECT … FROM (mock_tests|test_responses|
error_log|topic_mastery|study_sessions|bookmarks|question_flags)` in the
`src/db/**/*.rs` tree, require either `WHERE user_id` in the same string
literal or a file-level `#[allow(missing_user_scope)]` doc comment.
Simple regex check, ~30 lines.

---

## 5. Data-preservation plan (3,712 questions must survive)

Do these in order. **No step 3+ runs until step 1 finishes.**

1. **Full logical dump before touching schema.**
   ```sh
   turso db dump exam-prep-pandit > /snapshots/pre-r2-$(date -Iseconds).sql
   ```
   Store on operator machine + one off-site copy. Do not proceed until
   the file is > 1 MB and grep for `INSERT INTO questions` returns
   3,712 lines.

2. **Turso point-in-time restore rehearsal.** Turso keeps 14 days of PITR.
   Create a throwaway branch `exam-prep-pandit-r2-rehearsal` from the
   PITR snapshot, run the ALTERs on it end-to-end, confirm counts, then
   destroy the branch. This is where the CTAS on `topic_mastery` gets
   validated.

3. **Apply ALTERs on production Turso** (the SQL in §3.3). Each ALTER +
   its backfill in one pipeline.

4. **Verify counts + integrity:**
   ```sql
   SELECT 'questions',           COUNT(*) FROM questions;         -- expect 3712
   SELECT 'mock_tests',          COUNT(*), COUNT(user_id) FROM mock_tests;
   SELECT 'test_responses',      COUNT(*), COUNT(user_id) FROM test_responses;
   SELECT 'error_log',           COUNT(*), COUNT(user_id) FROM error_log;
   SELECT 'topic_mastery',       COUNT(*), COUNT(user_id) FROM topic_mastery;
   SELECT 'study_sessions',      COUNT(*), COUNT(user_id) FROM study_sessions;
   SELECT 'bookmarks',           COUNT(*), COUNT(user_id) FROM bookmarks;
   SELECT 'question_flags',      COUNT(*), COUNT(user_id) FROM question_flags;
   SELECT 'topic_mastery unique',COUNT(*) FROM topic_mastery
     GROUP BY user_id, topic_id HAVING COUNT(*) > 1;  -- expect 0 rows
   ```
   `COUNT(*)` and `COUNT(user_id)` must match for every table.
   `topic_mastery` unique check must return zero.

5. **Coexistence: point new Rust backend at the same Turso DB.** The
   Python app keeps running. Both talk to the same tables:
   - Python does `INSERT INTO mock_tests (started_at, …)` → `user_id`
     is NULL by default; a cron script `UPDATE mock_tests SET user_id=1
     WHERE user_id IS NULL` runs every 5 min during the transition.
   - Rust always writes `user_id` explicitly.
   - When the Python app is retired the cron is removed.

6. **Only after full cutover:** consider rebuilding tables to make
   `user_id` `NOT NULL`. Optional and low-value; the type system
   already prevents nulls on the Rust side.

---

## 6. FTS5 handling

Confirmed:
- `questions_fts` is a contentless FTS5 virtual table + 3 triggers
  (`db.py:180-201`).
- Existing migration `scripts/migrate_add_fts5_search.py` already deals
  with the "FTS5 unavailable" case gracefully.

For Rust:
- `libsql` crate calls Hrana; the server decides whether FTS5 is
  enabled. Turso's default build **does** include FTS5 as of 2025
  (verified during the FTS5 migration in Phase 7). Nothing on the
  client side needs to change.
- The `MATCH` operator is passed through unmodified:
  ```rust
  let rows = db.inner.query(
      "SELECT rowid FROM questions_fts WHERE questions_fts MATCH ?",
      (q,),
  ).await?;
  ```
- The triggers are attached to `questions` (INSERT/UPDATE/DELETE) — the
  Rust code doesn't interact with them directly; every write to
  `questions` fires them automatically.
- **Do not drop and recreate `questions` during R2.** The existing
  triggers reference it by name. The `questions` schema stays untouched
  by this migration (no `user_id` column added there — see §3.1).

---

## 7. Schema-evolution tool going forward — recommendation: **`refinery`**

### 7.1 Candidates

| Tool | Notes |
|---|---|
| `refinery` | Embedded migrations, DSN-agnostic, works with any driver via a small trait. **Pick this.** |
| `sqlx-cli` | Coupled to SQLx. We are not using SQLx. Reject. |
| Hand-rolled (like today's Python scripts) | Works, but no ordering guarantees, no `applied_migrations` table, easy to skip a step. Reject for the new codebase; keep the old Python scripts as historical record only. |
| `libsql` schema-migrations feature | Turso ships a server-side schema-migration system where you `INSERT INTO libsql_schema` with a version string and Turso versions the whole database. Interesting for schema branches, but overkill for our linear migration history. Skip for now. |

### 7.2 How to use refinery

- Put each migration in `migrations/V001__initial_schema.sql`,
  `V002__add_user_id_to_mock_tests.sql`, etc. File naming enforces order.
- At app startup: `refinery::embed_migrations!("./migrations")` + one
  call to `runner().run_async(&mut conn).await?`.
- Refinery needs a driver adapter. libSQL doesn't have a built-in
  refinery adapter (as of writing). Two options:
  1. **Write a 40-line `refinery_libsql` adapter.** Implements the
     `AsyncTransaction` trait against `libsql::Connection`. Straight
     port of the existing `refinery_tokio_postgres` adapter shape.
  2. **Run migrations against a local SQLite file, then push to Turso
     via `libsql-cli`.** Works but breaks the "one binary, one deploy"
     model. Reject.
- Store `refinery_schema_history` in Turso alongside the other tables.

### 7.3 Migration-file layout (proposed)

```
migrations/
  V001__baseline_schema.sql          # what's in Turso today, for fresh installs
  V002__add_user_id_columns.sql      # §3.3 minus topic_mastery CTAS
  V003__rebuild_topic_mastery.sql    # the CTAS block
  V004__add_bookmark_user_unique.sql # DROP + CREATE UNIQUE
  V005__backfill_question_flags.sql  # reporter→user_id mapping
```

V001 is a snapshot so a new dev can `cargo run` against a fresh Turso
branch and get a working schema. Not applied to production (refinery
detects V001 already applied via `applied_migrations`).

---

## 8. Turso quota / QPS / embedded replica strategy

### 8.1 What the tier gives us

Turso free tier (2026 pricing) — approximately:
- 500 million row reads / month
- 10 million row writes / month
- 9 GB storage
- No documented hard QPS cap; soft throttle kicks in ~1000 req/sec sustained.

For a single-digit-user platform this is a rounding-error's worth of
usage. We won't hit a quota. What we *will* hit is per-request latency:
Turso remote is ~40-80 ms per pipeline (Render → Turso EU or US
depending on region). A single page render that does 8 sequential
queries = 400+ ms just in DB round trips.

### 8.2 Fix: embedded replicas for read-heavy paths

`libsql::Builder::new_remote_replica("data/local.db", url, token)`:
- Downloads a local SQLite file on first boot, keeps it in sync via
  periodic Hrana `sync` calls.
- Reads hit the local file (~0.1 ms). Writes go remote (network hop
  as before).
- Sync latency: default 1 s poll, configurable down to 100 ms.

Where to use it:
- `/errorlog`, `/review`, `/dashboard` — SELECT-only, latency-sensitive.
- Anything that does the 3,712-row question scan.

Where NOT to use it:
- `/api/submit_answer` and other writes — always go remote so state
  is authoritative immediately.
- Multi-user isolation-critical reads (bookmarks, mastery) — actually
  safe on the replica because sync is per-database, not per-user; a
  slightly stale bookmark is fine.

Deployment note: Render's filesystem is ephemeral. On boot the replica
downloads afresh (Turso ships the whole DB — for a 3712-question DB
plus modest history, that's <20 MB, ~2 s over Render's network).
Acceptable cold-start cost.

### 8.3 Rate limit surface for Rust

Even at 1000 req/sec Turso soft-throttle, one Render instance running
the Rust app with `Semaphore(32)` fanout to Turso is far under it. The
throttle only becomes a concern if we start doing bulk backfills — in
which case, chunk to 200 statements/pipeline (Turso's `/v2/pipeline`
accepts up to ~1000 statements per request but 200 keeps latency
predictable).

---

## 9. Rust type-mapping + struct sketches

### 9.1 Type mapping cheat sheet

| SQLite type | Rust type | Notes |
|---|---|---|
| `INTEGER` | `i64` | Never `i32` — SQLite integers are 64-bit. Nullable → `Option<i64>`. |
| `INTEGER` (bool-like: 0/1) | `bool` via custom `From<i64>` in the struct impl | Applies to `is_active`, `is_correct`, `disabled`, `resolved`, `marked_for_review`. |
| `REAL` | `f64` | Nullable → `Option<f64>`. |
| `TEXT` | `String` | Nullable → `Option<String>`. |
| `TEXT` (ISO date/time) | `chrono::DateTime<chrono::Utc>` via `serde` with a custom deserializer | Everything in `db.py` uses TEXT ISO strings; convert on the way in. |
| `TEXT` (JSON) | `serde_json::Value` or a typed sub-struct | No JSON columns today; leave the door open. |
| `BLOB` | `Vec<u8>` | Not used today. |
| `NULL` in a NOT NULL column | Impossible — represent as `T` not `Option<T>`. |

The `libsql` crate exposes `Value` variants (`Integer`, `Real`, `Text`,
`Blob`, `Null`). Provide a small `TryFrom<libsql::Row>` for each domain
struct — 5-line impl per struct, boilerplate but explicit.

### 9.2 Domain structs (post-migration)

```rust
use chrono::{DateTime, Utc, NaiveDate};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id: i64,
    pub username: String,
    #[serde(skip_serializing)] pub password_hash: String,  // never leak
    pub role: String,                                       // "admin"|"user"
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
    pub last_login: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Question {
    pub id: i64,
    pub topic_id: Option<i64>,
    pub question_text: String,
    pub option_a: String, pub option_b: String,
    pub option_c: String, pub option_d: String,
    pub correct_option: String,
    pub explanation: Option<String>,
    pub difficulty: String,
    pub source: Option<String>,
    pub language: String,
    pub disabled: bool,
    pub updated_at: Option<DateTime<Utc>>,
    pub confidence: String,
    pub section: Option<String>, pub sub_topic: Option<String>,
    pub pyq_exam: Option<String>, pub pyq_year: Option<i64>,
    pub review_notes: Option<String>,
    pub confidence_reviewed_at: Option<DateTime<Utc>>,
}
// NOTE: Question has NO user_id — global content.

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MockTest {
    pub id: i64,
    pub user_id: i64,                              // NEW in R2
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub paper: Option<String>,
    pub total_questions: i64,
    pub score: Option<f64>,
    pub max_score: Option<i64>,
    pub time_taken_sec: Option<i64>,
    pub status: String,
    pub test_mode: String,
    pub duration_sec: Option<i64>,
    pub negative_ratio: f64,
    pub raw_marks: Option<f64>,
    pub wrong_count: Option<i64>,
    pub unanswered_count: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestResponse {
    pub id: i64,
    pub user_id: i64,                              // NEW in R2
    pub test_id: i64, pub question_id: i64,
    pub selected_option: Option<String>,
    pub is_correct: bool,
    pub time_spent_sec: Option<f64>,
    pub confidence: String,
    pub error_type: Option<String>,
    pub marked_for_review: bool,
    pub visit_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorLog {
    pub id: i64,
    pub user_id: i64,                              // NEW in R2
    pub test_id: Option<i64>, pub question_id: i64,
    pub topic_id: Option<i64>,
    pub selected_option: Option<String>,
    pub correct_option: String,
    pub error_type: Option<String>,
    pub root_cause: Option<String>,
    pub resolved: bool,
    pub created_at: DateTime<Utc>,
    pub redo_1_score: Option<f64>, pub redo_2_score: Option<f64>,
    pub sr_box: i64,
    pub sr_due_at: Option<NaiveDate>,
    pub sr_last_reviewed: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bookmark {
    pub id: i64, pub user_id: i64,                 // NEW in R2
    pub question_id: i64,
    pub created_at: DateTime<Utc>,
    pub note: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TopicMastery {
    pub id: i64, pub user_id: i64,                 // NEW (composite UNIQUE)
    pub topic_id: i64,
    pub diagnostic_score: Option<f64>,
    pub current_score: Option<f64>,
    pub study_hours: f64,
    pub status: String,
    pub last_studied: Option<DateTime<Utc>>,
    pub test_count: i64,
}
```

### 9.3 Serde and Hrana peculiarities

- `libsql` returns integers as native `i64` (unlike the raw Hrana JSON
  which returns them as strings — see `turso_patch.py:143-148`). The
  crate handles that coercion for you.
- Date columns are `TEXT`. Deserialise with a helper:
  ```rust
  fn parse_iso(s: &str) -> Option<DateTime<Utc>> {
      DateTime::parse_from_rfc3339(s).ok().map(|d| d.with_timezone(&Utc))
          .or_else(|| NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S").ok()
                       .map(|d| DateTime::from_naive_utc_and_offset(d, Utc)))
  }
  ```
  because our data has a mix of `CURRENT_TIMESTAMP` (`YYYY-MM-DD HH:MM:SS`)
  and Python `datetime.isoformat()` (RFC3339-ish) values. Old rows
  won't be reformatted; the parser must tolerate both.

---

## 10. Testing plan for R2

Before merging the Rust cutover PR:

1. **Local integration tests** against an in-memory SQLite loaded with
   the V001-V005 migrations. Each repo method has a golden-path test.
2. **Rehearsal on Turso branch** — the full sequence in §5.2. Assert
   the count queries in §5.4 return the expected numbers.
3. **Coexistence smoke test** — spin up Rust locally + Python on
   Render, both pointing at the rehearsal branch, and do:
   - Python creates a mock test (writes `user_id = NULL`)
   - Cron fills `user_id = 1`
   - Rust reads it as UserDb(1) — should return the row.
4. **Load test** — 200 concurrent requests to `/api/questions/search`.
   Confirm the `Semaphore(32)` caps Hrana concurrency correctly and
   the p95 stays under 300 ms.

---

## 11. Open questions for R1 / R3

- R1: does the framework choice force a specific async runtime? `libsql`
  is tokio-native. If R1 picks something non-tokio, revisit §1.
- R1: does the framework's error-handling story (axum's `IntoResponse`,
  actix's `ResponseError`) shape how `libsql::Error` propagates? Not
  blocking for R2 but note it.
- R3 (auth): how does the auth middleware pass `user_id` into the
  handler layer? The `UserDb` construction in §4.1 assumes the
  middleware runs a `SELECT id FROM users WHERE username = ?` on every
  request. That's one extra query per request; consider stashing
  `user_id` in the JWT claim (`sub` as int) and skipping the lookup.
- R3 (auth): admin bypass — how does `AdminDb` get constructed?
  Presumably a role-check middleware that only fires on `/admin/*`
  routes.
- Deferred: `pdf_uploads.uploaded_by TEXT` → `user_id INTEGER`. Not
  urgent; admin-only content.

---

## 12. Decision summary

| Decision | Choice | Confidence |
|---|---|---|
| libSQL client crate | `libsql` (official) | High |
| Query builder | None; raw SQL + repository pattern | High |
| Migration tool | `refinery` + tiny libSQL adapter | Medium — will confirm during R3 |
| Connection pooling | Single `Arc<Connection>` + Semaphore(32) | High |
| Read-heavy path acceleration | Embedded replica via `new_remote_replica` | Medium — start remote-only, switch if p95 > 300 ms |
| `user_id` type | `i64` non-null on the Rust side, nullable in schema | High |
| `test_responses.user_id` denormalisation | Add it despite being derivable | High |
| `topic_mastery` change strategy | CTAS rebuild (drops old UNIQUE) | High |
| `bookmarks` unique constraint | Drop `(question_id)` unique, add `(user_id, question_id)` | High |
| Coexistence with Python during cutover | Nullable `user_id` + 5-min backfill cron | High |
| FTS5 | Unchanged; already works over Hrana | High |
| Schema evolution long-term | Refinery migrations checked into repo | High |
