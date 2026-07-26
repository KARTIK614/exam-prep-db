//! `/api/v1/tests/*` — test-taking API surface.
//!
//! Endpoints (all require `RequireAuth`, all scope by user_id):
//!
//!   POST   /tests                       -- create a new attempt
//!   GET    /tests                       -- history for the current user
//!   GET    /tests/{id}                  -- full state for resume
//!   POST   /tests/{id}/answers          -- upsert one answer row
//!   POST   /tests/{id}/mark-for-review  -- toggle palette flag
//!   POST   /tests/{id}/finish           -- idempotent scoring
//!   GET    /tests/{id}/results          -- idempotent GET of finish result
//!
//! Semantics mirrored from `bp_tests.py`:
//!   * negative-marking presets: none=0, third=1/3, quarter=0.25,
//!     fifth=0.2, custom=<caller>. Force 0 in practice mode.
//!   * Score is raw accuracy `correct/total * 100`, floored at 0.
//!   * `raw_marks = correct - wrong * negative_ratio` (exam mode only).
//!   * error_log rows are seeded only for wrong answers; unanswered
//!     questions never touch test_responses (preserves the historical
//!     invariant `is_correct = 0` ⇒ "attempted and wrong").
//!   * Topic mastery updates use a 60/40 EMA on `current_score`.
//!
//! Cross-user safety: every route that takes `{id}` verifies
//! `mock_tests.user_id = caller.id` and returns 404 (not 403) on
//! mismatch to avoid enumerating other users' test ids.

use std::collections::{HashMap, HashSet};

use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::Json;
use chrono::Utc;
use libsql::params;

use crate::api::pagination::{clamp_limit, decode_cursor, next_cursor};
use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::{AuthUser, RequireAuth};
use crate::models::{
    int_to_bool, value_to_opt_f64, value_to_opt_i64, value_to_opt_string,
};
use crate::schemas::tests::{
    CreateTestRequest, CreateTestResponse, FinishResponse, MarkForReviewRequest,
    MarkForReviewResponse, ResultsQuestionRow, ResultsResponse, SubmitAnswerRequest,
    SubmitAnswerResponse, TestHistoryItem, TestListQuery, TestListResponse, TestQuestion,
    TestResponseSnapshot, TestStateResponse, TopicBreakdownRow,
};
use crate::services::sr;

// ---------- helpers --------------------------------------------------------

/// Map `neg_marking_preset` + `neg_marking_ratio` + `test_mode` to the
/// canonical stored ratio. Practice mode always yields 0.
fn resolve_negative_ratio(
    test_mode: &str,
    preset: Option<&str>,
    custom_ratio: Option<f64>,
) -> f64 {
    if test_mode != "exam" {
        return 0.0;
    }
    let key = preset.unwrap_or("third").to_ascii_lowercase();
    let raw = match key.as_str() {
        "none" => 0.0,
        "quarter" => 0.25,
        "fifth" => 0.20,
        "custom" => custom_ratio.unwrap_or(1.0 / 3.0),
        // "third" or anything unrecognised falls back to BCI default.
        _ => 1.0 / 3.0,
    };
    raw.clamp(0.0, 1.0)
}

fn validate_test_mode(m: &str) -> Result<String, AppError> {
    match m {
        "practice" | "exam" => Ok(m.to_string()),
        _ => Err(AppError::BadRequest(format!(
            "invalid test_mode: {m} (expected practice|exam)"
        ))),
    }
}

fn validate_difficulty(d: Option<&str>) -> Result<Option<String>, AppError> {
    match d {
        None => Ok(None),
        Some(v) => match v {
            "easy" | "medium" | "hard" => Ok(Some(v.to_string())),
            _ => Err(AppError::BadRequest(format!(
                "invalid difficulty: {v} (expected easy|medium|hard)"
            ))),
        },
    }
}

fn validate_option(opt: &str) -> Result<String, AppError> {
    match opt {
        "A" | "B" | "C" | "D" => Ok(opt.to_string()),
        _ => Err(AppError::BadRequest(format!(
            "invalid selected_option: {opt} (expected A|B|C|D)"
        ))),
    }
}

/// One-row lookup: test summary + ownership check.
///
/// Returns `Ok(row_fields)` when the caller owns the row, `NotFound`
/// when either the row doesn't exist OR belongs to another user (per
/// R4 §2.7 — no enumeration).
async fn load_test_for_user(
    state: &AppState,
    test_id: i64,
    user_id: i64,
) -> Result<TestRow, AppError> {
    // We SELECT the columns needed by every handler in this module —
    // narrowing keeps the round-trip small.
    let sql = "SELECT id, user_id, test_mode, negative_ratio, status, \
                      started_at, total_questions, score, raw_marks, \
                      wrong_count, unanswered_count, time_taken_sec, \
                      completed_at \
               FROM mock_tests WHERE id = ?1 LIMIT 1";
    let mut rows = state.db.conn().query(sql, params![test_id]).await?;
    let row = rows.next().await?.ok_or(AppError::NotFound("test"))?;

    let owner: i64 = row
        .get::<i64>(1)
        .map_err(|e| AppError::Internal(format!("read mock_tests.user_id: {e}")))?;
    if owner != user_id {
        // Deliberate 404: don't reveal that the row exists.
        return Err(AppError::NotFound("test"));
    }

    Ok(TestRow {
        id: row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("read mock_tests.id: {e}")))?,
        user_id: owner,
        test_mode: value_to_opt_string(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("read test_mode: {e}")))?,
        ),
        negative_ratio: value_to_opt_f64(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("read negative_ratio: {e}")))?,
        ),
        status: value_to_opt_string(
            row.get_value(4)
                .map_err(|e| AppError::Internal(format!("read status: {e}")))?,
        ),
        started_at: value_to_opt_string(
            row.get_value(5)
                .map_err(|e| AppError::Internal(format!("read started_at: {e}")))?,
        ),
        total_questions: value_to_opt_i64(
            row.get_value(6)
                .map_err(|e| AppError::Internal(format!("read total_questions: {e}")))?,
        ),
        score: value_to_opt_f64(
            row.get_value(7)
                .map_err(|e| AppError::Internal(format!("read score: {e}")))?,
        ),
        raw_marks: value_to_opt_f64(
            row.get_value(8)
                .map_err(|e| AppError::Internal(format!("read raw_marks: {e}")))?,
        ),
        wrong_count: value_to_opt_i64(
            row.get_value(9)
                .map_err(|e| AppError::Internal(format!("read wrong_count: {e}")))?,
        ),
        unanswered_count: value_to_opt_i64(
            row.get_value(10)
                .map_err(|e| AppError::Internal(format!("read unanswered_count: {e}")))?,
        ),
        time_taken_sec: value_to_opt_i64(
            row.get_value(11)
                .map_err(|e| AppError::Internal(format!("read time_taken_sec: {e}")))?,
        ),
        completed_at: value_to_opt_string(
            row.get_value(12)
                .map_err(|e| AppError::Internal(format!("read completed_at: {e}")))?,
        ),
    })
}

/// Minimum row shape carried across helpers. Not a public schema.
#[derive(Debug, Clone)]
struct TestRow {
    id: i64,
    #[allow(dead_code)]
    user_id: i64,
    test_mode: Option<String>,
    negative_ratio: Option<f64>,
    status: Option<String>,
    started_at: Option<String>,
    total_questions: Option<i64>,
    score: Option<f64>,
    raw_marks: Option<f64>,
    wrong_count: Option<i64>,
    unanswered_count: Option<i64>,
    time_taken_sec: Option<i64>,
    completed_at: Option<String>,
}

// ---------- POST /tests ----------------------------------------------------

/// Create a new test attempt.
///
/// Question selection strategy: SELECT the id + topic_id of every
/// non-disabled question matching the filters, shuffle in-Rust (Turso
/// doesn't ship a stable `random()` shortcut we can trust cross-region),
/// and slice the first `question_count`. This keeps the SQL portable
/// and gives us the option to weight the sampling later.
pub async fn create_test(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Json(req): Json<CreateTestRequest>,
) -> Result<(StatusCode, Json<CreateTestResponse>), AppError> {
    let test_mode = validate_test_mode(&req.test_mode)?;
    let difficulty = validate_difficulty(req.difficulty.as_deref())?;
    let negative_ratio = resolve_negative_ratio(
        &test_mode,
        req.neg_marking_preset.as_deref(),
        req.neg_marking_ratio,
    );

    // Clamp count into [1, 200] — matches the plan doc's ceiling.
    let want = req.question_count.clamp(1, 200) as usize;

    // Build the filter SQL + bind list.
    let mut clauses: Vec<String> = vec!["(q.disabled = 0 OR q.disabled IS NULL)".into()];
    let mut vals: Vec<libsql::Value> = Vec::new();

    if !req.topic_ids.is_empty() {
        let placeholders = std::iter::repeat("?")
            .take(req.topic_ids.len())
            .collect::<Vec<_>>()
            .join(",");
        clauses.push(format!("q.topic_id IN ({placeholders})"));
        for tid in &req.topic_ids {
            vals.push(libsql::Value::Integer(*tid));
        }
    }
    if let Some(d) = difficulty.as_deref() {
        clauses.push("q.difficulty = ?".into());
        vals.push(libsql::Value::Text(d.to_string()));
    }
    if matches!(req.pyq_only, Some(true)) {
        clauses.push("(q.pyq_exam IS NOT NULL AND q.pyq_exam <> '')".into());
    }
    if let Some(y) = req.pyq_year_min {
        clauses.push("COALESCE(q.pyq_year, 0) >= ?".into());
        vals.push(libsql::Value::Integer(y as i64));
    }
    if let Some(y) = req.pyq_year_max {
        clauses.push("COALESCE(q.pyq_year, 0) <= ?".into());
        vals.push(libsql::Value::Integer(y as i64));
    }

    let where_sql = clauses.join(" AND ");
    let candidates_sql = format!(
        "SELECT q.id FROM questions q WHERE {where_sql} ORDER BY q.id"
    );

    let mut rows = state.db.conn().query(&candidates_sql, vals).await?;
    let mut candidate_ids: Vec<i64> = Vec::new();
    while let Some(row) = rows.next().await? {
        candidate_ids.push(
            row.get::<i64>(0)
                .map_err(|e| AppError::Internal(format!("read candidate id: {e}")))?,
        );
    }

    if candidate_ids.is_empty() {
        return Err(AppError::BadRequest(
            "no questions matched the requested filters".into(),
        ));
    }

    // Pick `want` at random. Reservoir sampling would be nicer for
    // huge candidate sets, but the biggest topic bucket in the db
    // right now is ~500 rows — a Fisher-Yates shuffle on that is
    // cheap.
    use rand::seq::SliceRandom;
    let mut rng = rand::thread_rng();
    candidate_ids.shuffle(&mut rng);
    let taken: Vec<i64> = candidate_ids.into_iter().take(want).collect();

    // Insert the mock_tests row. We do NOT store the question_ids
    // list on this row — resume-later uses a `test_questions` join
    // table when we add one, but for Phase 5 we rely on
    // `test_responses` to remember what was asked. To make resume
    // possible even before any answer lands, we insert one
    // "unanswered" row per selected question up front (see below).
    let now = Utc::now().to_rfc3339();
    let insert_sql = "INSERT INTO mock_tests \
                          (started_at, total_questions, max_score, status, \
                           test_mode, negative_ratio, user_id) \
                      VALUES (?1, ?2, ?3, 'in_progress', ?4, ?5, ?6) \
                      RETURNING id";
    let mut rows = state
        .db
        .conn()
        .query(
            insert_sql,
            params![
                now.clone(),
                taken.len() as i64,
                taken.len() as i64,
                test_mode.clone(),
                negative_ratio,
                auth.id,
            ],
        )
        .await?;
    let row = rows
        .next()
        .await?
        .ok_or_else(|| AppError::Internal("INSERT ... RETURNING produced no row".into()))?;
    let test_id: i64 = row
        .get::<i64>(0)
        .map_err(|e| AppError::Internal(format!("read new test id: {e}")))?;

    // Pre-seed one test_responses row per question so `GET /tests/{id}`
    // can enumerate the question set even before the user has answered.
    // `selected_option = NULL, is_correct = 0, visit_count = 0`. We use
    // INSERT OR IGNORE + a UNIQUE(test_id, question_id) index — but that
    // unique index only exists after Phase-5 migration, so we defensively
    // catch duplicate inserts.
    for qid in &taken {
        let _ = state
            .db
            .conn()
            .execute(
                "INSERT INTO test_responses \
                    (test_id, question_id, user_id, selected_option, \
                     is_correct, marked_for_review, visit_count) \
                 VALUES (?1, ?2, ?3, NULL, 0, 0, 0)",
                params![test_id, *qid, auth.id],
            )
            .await;
    }

    Ok((
        StatusCode::CREATED,
        Json(CreateTestResponse {
            test_id,
            question_ids: taken,
            test_mode,
            negative_ratio,
        }),
    ))
}

// ---------- GET /tests/{id} ------------------------------------------------

/// Full state for a test — used by the FE to resume-after-refresh.
pub async fn get_test(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Path(test_id): Path<i64>,
) -> Result<Json<TestStateResponse>, AppError> {
    let test = load_test_for_user(&state, test_id, auth.id).await?;

    // Ordered enumeration of the question set. `test_responses.id`
    // reflects insertion order (which is our "asked in this order")
    // because we insert one row per question at test creation time.
    let q_sql = "SELECT tr.id, tr.question_id, q.question_text, \
                        q.option_a, q.option_b, q.option_c, q.option_d, \
                        tr.selected_option, tr.marked_for_review, \
                        tr.visit_count, tr.time_spent_sec \
                 FROM test_responses tr \
                 JOIN questions q ON q.id = tr.question_id \
                 WHERE tr.test_id = ?1 AND tr.user_id = ?2 \
                 ORDER BY tr.id ASC";
    let mut rows = state
        .db
        .conn()
        .query(q_sql, params![test.id, auth.id])
        .await?;

    let mut questions: Vec<TestQuestion> = Vec::new();
    let mut responses: Vec<TestResponseSnapshot> = Vec::new();
    let mut idx: i64 = 0;
    while let Some(row) = rows.next().await? {
        let qid: i64 = row
            .get::<i64>(1)
            .map_err(|e| AppError::Internal(format!("read tr.question_id: {e}")))?;
        questions.push(TestQuestion {
            id: qid,
            question_text: value_to_opt_string(
                row.get_value(2)
                    .map_err(|e| AppError::Internal(format!("read question_text: {e}")))?,
            ),
            option_a: value_to_opt_string(
                row.get_value(3)
                    .map_err(|e| AppError::Internal(format!("read option_a: {e}")))?,
            ),
            option_b: value_to_opt_string(
                row.get_value(4)
                    .map_err(|e| AppError::Internal(format!("read option_b: {e}")))?,
            ),
            option_c: value_to_opt_string(
                row.get_value(5)
                    .map_err(|e| AppError::Internal(format!("read option_c: {e}")))?,
            ),
            option_d: value_to_opt_string(
                row.get_value(6)
                    .map_err(|e| AppError::Internal(format!("read option_d: {e}")))?,
            ),
            order_index: idx,
        });
        let selected = value_to_opt_string(
            row.get_value(7)
                .map_err(|e| AppError::Internal(format!("read selected_option: {e}")))?,
        );
        let marked = int_to_bool(value_to_opt_i64(
            row.get_value(8)
                .map_err(|e| AppError::Internal(format!("read marked_for_review: {e}")))?,
        ));
        let visits = value_to_opt_i64(
            row.get_value(9)
                .map_err(|e| AppError::Internal(format!("read visit_count: {e}")))?,
        )
        .unwrap_or(0);
        let time = value_to_opt_f64(
            row.get_value(10)
                .map_err(|e| AppError::Internal(format!("read time_spent_sec: {e}")))?,
        );
        responses.push(TestResponseSnapshot {
            question_id: qid,
            selected_option: selected,
            marked_for_review: marked,
            visit_count: visits,
            time_spent_sec: time,
        });
        idx += 1;
    }

    Ok(Json(TestStateResponse {
        test_id: test.id,
        test_mode: test.test_mode.clone().unwrap_or_else(|| "practice".into()),
        negative_ratio: test.negative_ratio.unwrap_or(0.0),
        started_at: test.started_at.clone(),
        questions,
        responses,
        status: test.status.clone().unwrap_or_else(|| "in_progress".into()),
    }))
}

// ---------- POST /tests/{id}/answers --------------------------------------

/// Submit / update the caller's answer for one question in this test.
///
/// Semantics: upsert on `(user_id, test_id, question_id)`. First call
/// creates the row (or updates the seeded placeholder). Subsequent
/// calls update `selected_option` / `time_spent_sec` and increment
/// `visit_count` so we can distinguish a single visit from repeated
/// revisits.
pub async fn submit_answer(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Path(test_id): Path<i64>,
    Json(req): Json<SubmitAnswerRequest>,
) -> Result<Json<SubmitAnswerResponse>, AppError> {
    let test = load_test_for_user(&state, test_id, auth.id).await?;
    if test.status.as_deref() == Some("completed") {
        return Err(AppError::Conflict(
            "cannot modify answers on a completed test".into(),
        ));
    }

    // Reject a stray question_id that isn't part of this test.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT id FROM test_responses \
             WHERE test_id = ?1 AND user_id = ?2 AND question_id = ?3 LIMIT 1",
            params![test.id, auth.id, req.question_id],
        )
        .await?;
    let existing = rows.next().await?;
    let selected = match req.selected_option.as_deref() {
        Some(s) => Some(validate_option(s)?),
        None => None,
    };

    // Look up correctness against the questions table so results can
    // read is_correct without a second join (Flask ran this at finish
    // only — we bring it forward so /answers is enough to score).
    let mut crow = state
        .db
        .conn()
        .query(
            "SELECT correct_option, topic_id FROM questions WHERE id = ?1 LIMIT 1",
            params![req.question_id],
        )
        .await?;
    let (correct_opt, _topic_id): (Option<String>, Option<i64>) = match crow.next().await? {
        Some(r) => (
            value_to_opt_string(
                r.get_value(0)
                    .map_err(|e| AppError::Internal(format!("read q.correct_option: {e}")))?,
            ),
            value_to_opt_i64(
                r.get_value(1)
                    .map_err(|e| AppError::Internal(format!("read q.topic_id: {e}")))?,
            ),
        ),
        None => return Err(AppError::NotFound("question")),
    };
    let is_correct = match (selected.as_deref(), correct_opt.as_deref()) {
        (Some(s), Some(c)) => s == c,
        _ => false,
    };

    let marked_int: i64 = if req.marked_for_review { 1 } else { 0 };
    let correct_int: i64 = if is_correct { 1 } else { 0 };

    if existing.is_some() {
        // Update the row + bump visit_count.
        state
            .db
            .conn()
            .execute(
                "UPDATE test_responses \
                 SET selected_option = ?1, is_correct = ?2, \
                     time_spent_sec = ?3, marked_for_review = ?4, \
                     visit_count = COALESCE(visit_count, 0) + 1 \
                 WHERE test_id = ?5 AND user_id = ?6 AND question_id = ?7",
                params![
                    selected.clone(),
                    correct_int,
                    req.time_spent_sec,
                    marked_int,
                    test.id,
                    auth.id,
                    req.question_id,
                ],
            )
            .await?;
    } else {
        // First-time insert — no seeded placeholder available. Should
        // be rare because create_test pre-seeds every row, but the
        // handler stays robust.
        state
            .db
            .conn()
            .execute(
                "INSERT INTO test_responses \
                    (test_id, question_id, user_id, selected_option, \
                     is_correct, time_spent_sec, marked_for_review, visit_count) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 1)",
                params![
                    test.id,
                    req.question_id,
                    auth.id,
                    selected,
                    correct_int,
                    req.time_spent_sec,
                    marked_int,
                ],
            )
            .await?;
    }

    Ok(Json(SubmitAnswerResponse { status: "ok" }))
}

// ---------- POST /tests/{id}/mark-for-review ------------------------------

pub async fn mark_for_review(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Path(test_id): Path<i64>,
    Json(req): Json<MarkForReviewRequest>,
) -> Result<Json<MarkForReviewResponse>, AppError> {
    let test = load_test_for_user(&state, test_id, auth.id).await?;
    if test.status.as_deref() == Some("completed") {
        return Err(AppError::Conflict(
            "cannot modify a completed test".into(),
        ));
    }

    let marked_int: i64 = if req.marked { 1 } else { 0 };
    let n = state
        .db
        .conn()
        .execute(
            "UPDATE test_responses \
             SET marked_for_review = ?1 \
             WHERE test_id = ?2 AND user_id = ?3 AND question_id = ?4",
            params![marked_int, test.id, auth.id, req.question_id],
        )
        .await?;

    if n == 0 {
        // No pre-existing row — insert a bare-bones placeholder so the
        // mark survives even before any answer.
        state
            .db
            .conn()
            .execute(
                "INSERT INTO test_responses \
                    (test_id, question_id, user_id, selected_option, \
                     is_correct, marked_for_review, visit_count) \
                 VALUES (?1, ?2, ?3, NULL, 0, ?4, 0)",
                params![test.id, req.question_id, auth.id, marked_int],
            )
            .await?;
    }

    Ok(Json(MarkForReviewResponse { status: "ok" }))
}

// ---------- POST /tests/{id}/finish + GET /tests/{id}/results -------------

/// Idempotent scoring. If the row is already `status='completed'`, we
/// skip the mutation path and return the persisted numbers.
///
/// This is a bit of a monster because it does:
///   1. Load responses + join in correct_option / topic_id.
///   2. Compute correct / wrong / unanswered.
///   3. Compute score_pct + raw_marks (exam-mode only for neg).
///   4. UPDATE mock_tests.
///   5. INSERT OR IGNORE into error_log for each wrong answer.
///   6. UPSERT topic_mastery via a 60/40 EMA on current_score.
///
/// We keep the whole flow serial (no `db.transaction()` in libsql yet
/// on remote conns), ordering writes so a partial-run leaves the DB
/// consistent: mock_tests marks 'completed' LAST, so if we crash mid-
/// way the next call re-runs from the top with the same inputs.
async fn finish_impl(
    state: &AppState,
    auth: &AuthUser,
    test_id: i64,
) -> Result<FinishResponse, AppError> {
    let mut test = load_test_for_user(state, test_id, auth.id).await?;

    // Fast-path: already completed → return the persisted numbers.
    if test.status.as_deref() == Some("completed") {
        let breakdown = load_topic_breakdown(state, auth, test.id).await?;
        return Ok(FinishResponse {
            test_id: test.id,
            correct: correct_from(&test),
            wrong: test.wrong_count.unwrap_or(0),
            unanswered: test.unanswered_count.unwrap_or(0),
            score_pct: test.score.unwrap_or(0.0),
            raw_marks: test.raw_marks.unwrap_or(0.0),
            negative_ratio: test.negative_ratio.unwrap_or(0.0),
            breakdown_by_topic: breakdown,
        });
    }

    // Pull every response + question + topic in one shot.
    let sql = "SELECT tr.question_id, tr.selected_option, tr.is_correct, \
                      tr.time_spent_sec, q.correct_option, q.topic_id, \
                      t.name AS topic_name \
               FROM test_responses tr \
               JOIN questions q ON q.id = tr.question_id \
               LEFT JOIN topics t ON t.id = q.topic_id \
               WHERE tr.test_id = ?1 AND tr.user_id = ?2 \
               ORDER BY tr.id ASC";
    let mut rows = state
        .db
        .conn()
        .query(sql, params![test.id, auth.id])
        .await?;

    #[derive(Debug, Clone)]
    struct Resp {
        question_id: i64,
        selected: Option<String>,
        correct_opt: Option<String>,
        time_spent_sec: Option<f64>,
        topic_id: Option<i64>,
        topic_name: Option<String>,
    }
    let mut all: Vec<Resp> = Vec::new();
    while let Some(row) = rows.next().await? {
        let qid: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("finish: read qid: {e}")))?;
        let sel = value_to_opt_string(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("finish: read selected: {e}")))?,
        );
        // is_correct at index 2 is a snapshot; we re-derive from
        // (selected, correct_opt) below to catch any drift.
        let _existing_correct = value_to_opt_i64(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("finish: read is_correct: {e}")))?,
        );
        let time = value_to_opt_f64(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("finish: read time_spent_sec: {e}")))?,
        );
        let correct_opt = value_to_opt_string(
            row.get_value(4)
                .map_err(|e| AppError::Internal(format!("finish: read q.correct_option: {e}")))?,
        );
        let topic_id = value_to_opt_i64(
            row.get_value(5)
                .map_err(|e| AppError::Internal(format!("finish: read q.topic_id: {e}")))?,
        );
        let topic_name = value_to_opt_string(
            row.get_value(6)
                .map_err(|e| AppError::Internal(format!("finish: read topic_name: {e}")))?,
        );
        all.push(Resp {
            question_id: qid,
            selected: sel,
            correct_opt,
            time_spent_sec: time,
            topic_id,
            topic_name,
        });
    }

    let total = all.len() as i64;
    let mut correct: i64 = 0;
    let mut wrong: i64 = 0;
    let mut unanswered: i64 = 0;
    let mut time_taken: f64 = 0.0;

    for r in &all {
        time_taken += r.time_spent_sec.unwrap_or(0.0);
        match (r.selected.as_deref(), r.correct_opt.as_deref()) {
            (None, _) | (Some(""), _) => unanswered += 1,
            (Some(s), Some(c)) if s == c => correct += 1,
            (Some(_), _) => wrong += 1,
        }
    }

    let test_mode = test.test_mode.clone().unwrap_or_else(|| "practice".into());
    let stored_ratio = test.negative_ratio.unwrap_or(0.0);
    let effective_ratio = if test_mode == "exam" { stored_ratio } else { 0.0 };
    let raw_marks = correct as f64 - (wrong as f64) * effective_ratio;
    // Edge cases:
    //   * total == 0  → score_pct = 0 (avoid divide-by-zero).
    //   * All unanswered → correct = 0, wrong = 0 → raw_marks = 0 → score_pct = 0.
    //   * Practice mode → effective_ratio = 0, so raw = correct.
    let score_pct = if total > 0 {
        (raw_marks.max(0.0) / total as f64) * 100.0
    } else {
        0.0
    };

    // Persist to mock_tests. We save the rounded value for `score` to
    // match Flask (`round(..., 1)`); the raw value is kept two decimal
    // places to preserve arithmetic sanity across finish/results calls.
    let score_pct_rounded = round1(score_pct);
    let raw_marks_rounded = round2(raw_marks);
    let now = Utc::now().to_rfc3339();
    state
        .db
        .conn()
        .execute(
            "UPDATE mock_tests \
             SET completed_at = ?1, score = ?2, time_taken_sec = ?3, \
                 raw_marks = ?4, wrong_count = ?5, unanswered_count = ?6, \
                 status = 'completed' \
             WHERE id = ?7 AND user_id = ?8",
            params![
                now,
                score_pct_rounded,
                time_taken as i64,
                raw_marks_rounded,
                wrong,
                unanswered,
                test.id,
                auth.id,
            ],
        )
        .await?;

    // Update in-memory copy so return-path uses fresh values.
    test.status = Some("completed".into());
    test.score = Some(score_pct_rounded);
    test.raw_marks = Some(raw_marks_rounded);
    test.wrong_count = Some(wrong);
    test.unanswered_count = Some(unanswered);
    test.time_taken_sec = Some(time_taken as i64);
    test.completed_at = Some(now.clone());

    // Insert an error_log row for every wrong answer. INSERT OR IGNORE
    // + the UNIQUE(user_id, test_id, question_id) index makes this
    // safe to call on a re-finish (idempotent seed).
    let (sr_box, sr_due) = sr::initial_box_and_due();
    for r in &all {
        let is_wrong = match (r.selected.as_deref(), r.correct_opt.as_deref()) {
            (Some(""), _) | (None, _) => false, // unanswered ≠ wrong
            (Some(s), Some(c)) => s != c,
            _ => false,
        };
        if !is_wrong {
            continue;
        }
        let error_type = classify_error(r.time_spent_sec);
        state
            .db
            .conn()
            .execute(
                "INSERT OR IGNORE INTO error_log \
                    (test_id, question_id, topic_id, selected_option, \
                     correct_option, error_type, created_at, \
                     sr_box, sr_due_at, user_id) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                params![
                    test.id,
                    r.question_id,
                    r.topic_id,
                    r.selected.clone(),
                    r.correct_opt.clone(),
                    error_type,
                    now.clone(),
                    sr_box,
                    sr_due.clone(),
                    auth.id,
                ],
            )
            .await?;
    }

    // Topic mastery: aggregate this test's answers per topic, then
    // UPSERT with a 60/40 EMA on `current_score`.
    let mut per_topic: HashMap<i64, (i64, i64)> = HashMap::new(); // topic_id -> (correct, total)
    for r in &all {
        let Some(tid) = r.topic_id else { continue };
        let entry = per_topic.entry(tid).or_insert((0, 0));
        entry.1 += 1;
        let is_correct = match (r.selected.as_deref(), r.correct_opt.as_deref()) {
            (Some(s), Some(c)) => s == c,
            _ => false,
        };
        if is_correct {
            entry.0 += 1;
        }
    }
    for (tid, (c, t)) in &per_topic {
        if *t == 0 {
            continue;
        }
        let pct = (*c as f64 / *t as f64) * 100.0;
        upsert_topic_mastery(state, auth.id, *tid, pct).await?;
    }

    let triples: Vec<(Option<i64>, Option<String>, bool)> = all
        .iter()
        .map(|r| {
            let is_correct = match (r.selected.as_deref(), r.correct_opt.as_deref()) {
                (Some(s), Some(c)) => s == c,
                _ => false,
            };
            (r.topic_id, r.topic_name.clone(), is_correct)
        })
        .collect();
    let breakdown = breakdown_from_triples(&triples);
    Ok(FinishResponse {
        test_id: test.id,
        correct,
        wrong,
        unanswered,
        score_pct: score_pct_rounded,
        raw_marks: raw_marks_rounded,
        negative_ratio: effective_ratio,
        breakdown_by_topic: breakdown,
    })
}

/// Derive `correct` from the persisted mock_tests row on the idempotent
/// return path. `total_questions - wrong_count - unanswered_count`
/// covers every attempted-and-right response.
fn correct_from(t: &TestRow) -> i64 {
    let total = t.total_questions.unwrap_or(0);
    let wrong = t.wrong_count.unwrap_or(0);
    let un = t.unanswered_count.unwrap_or(0);
    (total - wrong - un).max(0)
}

fn round1(x: f64) -> f64 {
    (x * 10.0).round() / 10.0
}
fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

/// Cheap error-type heuristic (matches `bp_tests.py::finish`).
fn classify_error(time_spent_sec: Option<f64>) -> &'static str {
    match time_spent_sec {
        Some(t) if t < 10.0 => "time_pressure",
        _ => "concept_gap",
    }
}

/// UPSERT topic_mastery via a 60/40 EMA. New rows initialise directly
/// with the current test's percentage.
async fn upsert_topic_mastery(
    state: &AppState,
    user_id: i64,
    topic_id: i64,
    this_pct: f64,
) -> Result<(), AppError> {
    // Try to load the existing row. Note: after v3 migration the
    // effective UNIQUE key is (user_id, topic_id) — the legacy
    // (topic_id) UNIQUE still exists on the table but we only ever
    // wrote user 1 into it, so multi-user inserts collide there. On
    // that collision we fall back to UPDATE by (user_id, topic_id).
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT current_score FROM topic_mastery \
             WHERE user_id = ?1 AND topic_id = ?2 LIMIT 1",
            params![user_id, topic_id],
        )
        .await?;
    let existing = match rows.next().await? {
        Some(row) => value_to_opt_f64(
            row.get_value(0)
                .map_err(|e| AppError::Internal(format!("read topic_mastery.current_score: {e}")))?,
        ),
        None => None,
    };

    let now = Utc::now().to_rfc3339();
    match existing {
        Some(old) => {
            let new_score = round1(0.6 * old + 0.4 * this_pct);
            let status = if new_score < 70.0 {
                "in_progress"
            } else {
                "stable"
            };
            state
                .db
                .conn()
                .execute(
                    "UPDATE topic_mastery \
                     SET current_score = ?1, \
                         test_count = COALESCE(test_count, 0) + 1, \
                         last_studied = ?2, status = ?3 \
                     WHERE user_id = ?4 AND topic_id = ?5",
                    params![new_score, now, status, user_id, topic_id],
                )
                .await?;
        }
        None => {
            let new_score = round1(this_pct);
            let status = if new_score < 70.0 {
                "in_progress"
            } else {
                "stable"
            };
            // Try insert; if the legacy UNIQUE(topic_id) trips we
            // silently fall back to UPDATE by (user_id, topic_id).
            let res = state
                .db
                .conn()
                .execute(
                    "INSERT INTO topic_mastery \
                        (topic_id, current_score, test_count, status, last_studied, user_id) \
                     VALUES (?1, ?2, 1, ?3, ?4, ?5)",
                    params![topic_id, new_score, status, now.clone(), user_id],
                )
                .await;
            if res.is_err() {
                state
                    .db
                    .conn()
                    .execute(
                        "UPDATE topic_mastery \
                         SET current_score = ?1, \
                             test_count = COALESCE(test_count, 0) + 1, \
                             last_studied = ?2, status = ?3 \
                         WHERE user_id = ?4 AND topic_id = ?5",
                        params![new_score, now, status, user_id, topic_id],
                    )
                    .await?;
            }
        }
    }
    Ok(())
}

/// Load per-topic breakdown from persisted rows (used on idempotent
/// return path).
async fn load_topic_breakdown(
    state: &AppState,
    auth: &AuthUser,
    test_id: i64,
) -> Result<Vec<TopicBreakdownRow>, AppError> {
    let sql = "SELECT tr.selected_option, q.correct_option, q.topic_id, t.name \
               FROM test_responses tr \
               JOIN questions q ON q.id = tr.question_id \
               LEFT JOIN topics t ON t.id = q.topic_id \
               WHERE tr.test_id = ?1 AND tr.user_id = ?2";
    let mut rows = state
        .db
        .conn()
        .query(sql, params![test_id, auth.id])
        .await?;

    #[derive(Default)]
    struct Agg {
        name: Option<String>,
        correct: i64,
        total: i64,
    }
    let mut map: HashMap<Option<i64>, Agg> = HashMap::new();
    while let Some(row) = rows.next().await? {
        let sel = value_to_opt_string(
            row.get_value(0)
                .map_err(|e| AppError::Internal(format!("read breakdown selected: {e}")))?,
        );
        let correct = value_to_opt_string(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("read breakdown correct: {e}")))?,
        );
        let topic_id = value_to_opt_i64(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("read breakdown topic_id: {e}")))?,
        );
        let tname = value_to_opt_string(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("read breakdown topic_name: {e}")))?,
        );
        let entry = map.entry(topic_id).or_default();
        entry.name = tname.or(entry.name.clone());
        entry.total += 1;
        if let (Some(s), Some(c)) = (sel.as_deref(), correct.as_deref()) {
            if s == c {
                entry.correct += 1;
            }
        }
    }

    let mut out: Vec<TopicBreakdownRow> = map
        .into_iter()
        .map(|(topic_id, agg)| {
            let acc = if agg.total > 0 {
                round1((agg.correct as f64 / agg.total as f64) * 100.0)
            } else {
                0.0
            };
            TopicBreakdownRow {
                topic_id,
                topic_name: agg.name,
                correct: agg.correct,
                total: agg.total,
                accuracy_pct: acc,
            }
        })
        .collect();
    // Deterministic order: by topic_id ASC (None last).
    out.sort_by(|a, b| match (a.topic_id, b.topic_id) {
        (Some(x), Some(y)) => x.cmp(&y),
        (Some(_), None) => std::cmp::Ordering::Less,
        (None, Some(_)) => std::cmp::Ordering::Greater,
        (None, None) => std::cmp::Ordering::Equal,
    });
    Ok(out)
}

/// Compute per-topic breakdown from a slice of `(topic_id, topic_name,
/// is_correct)` triples. Kept broad so both the fresh-finish path (where
/// we already have the raw response list in memory) and future
/// consumers can call it without an extra DB round-trip.
fn breakdown_from_triples(
    triples: &[(Option<i64>, Option<String>, bool)],
) -> Vec<TopicBreakdownRow> {
    #[derive(Default)]
    struct Agg {
        name: Option<String>,
        correct: i64,
        total: i64,
    }
    let mut map: HashMap<Option<i64>, Agg> = HashMap::new();
    for (topic_id, topic_name, is_correct) in triples {
        let entry = map.entry(*topic_id).or_default();
        if entry.name.is_none() {
            entry.name = topic_name.clone();
        }
        entry.total += 1;
        if *is_correct {
            entry.correct += 1;
        }
    }
    let mut out: Vec<TopicBreakdownRow> = map
        .into_iter()
        .map(|(topic_id, agg)| {
            let acc = if agg.total > 0 {
                round1((agg.correct as f64 / agg.total as f64) * 100.0)
            } else {
                0.0
            };
            TopicBreakdownRow {
                topic_id,
                topic_name: agg.name,
                correct: agg.correct,
                total: agg.total,
                accuracy_pct: acc,
            }
        })
        .collect();
    out.sort_by(|a, b| match (a.topic_id, b.topic_id) {
        (Some(x), Some(y)) => x.cmp(&y),
        (Some(_), None) => std::cmp::Ordering::Less,
        (None, Some(_)) => std::cmp::Ordering::Greater,
        (None, None) => std::cmp::Ordering::Equal,
    });
    out
}

// --- Public handlers ------------------------------------------------------

pub async fn finish(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Path(test_id): Path<i64>,
) -> Result<Json<FinishResponse>, AppError> {
    let out = finish_impl(&state, &auth, test_id).await?;
    Ok(Json(out))
}

pub async fn get_results(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Path(test_id): Path<i64>,
) -> Result<Json<ResultsResponse>, AppError> {
    // Ownership check happens inside finish_impl (through load_test_for_user).
    let finish = finish_impl(&state, &auth, test_id).await?;

    // Per-question breakdown for the review UI.
    let sql = "SELECT tr.question_id, q.question_text, tr.selected_option, \
                      q.correct_option, q.explanation, tr.time_spent_sec, \
                      t.name AS topic_name \
               FROM test_responses tr \
               JOIN questions q ON q.id = tr.question_id \
               LEFT JOIN topics t ON t.id = q.topic_id \
               WHERE tr.test_id = ?1 AND tr.user_id = ?2 \
               ORDER BY tr.id ASC";
    let mut rows = state
        .db
        .conn()
        .query(sql, params![test_id, auth.id])
        .await?;
    let mut questions: Vec<ResultsQuestionRow> = Vec::new();
    while let Some(row) = rows.next().await? {
        let qid: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("results: read qid: {e}")))?;
        let q_text = value_to_opt_string(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("results: read q_text: {e}")))?,
        );
        let selected = value_to_opt_string(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("results: read selected: {e}")))?,
        );
        let correct = value_to_opt_string(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("results: read correct: {e}")))?,
        );
        let explanation = value_to_opt_string(
            row.get_value(4)
                .map_err(|e| AppError::Internal(format!("results: read explanation: {e}")))?,
        );
        let time = value_to_opt_f64(
            row.get_value(5)
                .map_err(|e| AppError::Internal(format!("results: read time: {e}")))?,
        );
        let topic_name = value_to_opt_string(
            row.get_value(6)
                .map_err(|e| AppError::Internal(format!("results: read topic_name: {e}")))?,
        );
        let is_correct = match (selected.as_deref(), correct.as_deref()) {
            (Some(s), Some(c)) => s == c,
            _ => false,
        };
        questions.push(ResultsQuestionRow {
            question_id: qid,
            question_text: q_text,
            selected_option: selected,
            correct_option: correct,
            is_correct,
            explanation,
            time_spent_sec: time,
            topic_name,
        });
    }

    Ok(Json(ResultsResponse { finish, questions }))
}

// ---------- GET /tests (history) ------------------------------------------

pub async fn list_tests(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Query(q): Query<TestListQuery>,
) -> Result<Json<TestListResponse>, AppError> {
    let limit = clamp_limit(q.limit);
    let after_id = decode_cursor(q.cursor.as_deref())?;

    let mut clauses: Vec<String> = vec!["user_id = ?".into()];
    let mut vals: Vec<libsql::Value> = vec![libsql::Value::Integer(auth.id)];

    if let Some(s) = q.status.as_deref() {
        // Whitelist to prevent injection through a bogus query value.
        let allowed: HashSet<&str> = ["in_progress", "completed", "abandoned"]
            .into_iter()
            .collect();
        if !allowed.contains(s) {
            return Err(AppError::BadRequest(format!(
                "invalid status: {s} (expected in_progress|completed|abandoned)"
            )));
        }
        clauses.push("status = ?".into());
        vals.push(libsql::Value::Text(s.to_string()));
    }
    if let Some(id) = after_id {
        // Cursor semantics: `id < ?` because we're ordering DESC.
        clauses.push("id < ?".into());
        vals.push(libsql::Value::Integer(id));
    }

    let where_sql = clauses.join(" AND ");
    let sql = format!(
        "SELECT id, test_mode, status, total_questions, score, raw_marks, \
                wrong_count, unanswered_count, negative_ratio, started_at, \
                completed_at, time_taken_sec \
         FROM mock_tests \
         WHERE {where_sql} \
         ORDER BY id DESC \
         LIMIT ?"
    );
    vals.push(libsql::Value::Integer(limit as i64));

    let mut rows = state.db.conn().query(&sql, vals).await?;
    let mut items: Vec<TestHistoryItem> = Vec::new();
    while let Some(row) = rows.next().await? {
        let id: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("list: read id: {e}")))?;
        let test_mode = value_to_opt_string(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("list: read test_mode: {e}")))?,
        );
        let status = value_to_opt_string(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("list: read status: {e}")))?,
        );
        let total = value_to_opt_i64(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("list: read total: {e}")))?,
        );
        let score = value_to_opt_f64(
            row.get_value(4)
                .map_err(|e| AppError::Internal(format!("list: read score: {e}")))?,
        );
        let raw_marks = value_to_opt_f64(
            row.get_value(5)
                .map_err(|e| AppError::Internal(format!("list: read raw_marks: {e}")))?,
        );
        let wrong = value_to_opt_i64(
            row.get_value(6)
                .map_err(|e| AppError::Internal(format!("list: read wrong: {e}")))?,
        );
        let unanswered = value_to_opt_i64(
            row.get_value(7)
                .map_err(|e| AppError::Internal(format!("list: read unanswered: {e}")))?,
        );
        let neg = value_to_opt_f64(
            row.get_value(8)
                .map_err(|e| AppError::Internal(format!("list: read neg: {e}")))?,
        );
        let started = value_to_opt_string(
            row.get_value(9)
                .map_err(|e| AppError::Internal(format!("list: read started: {e}")))?,
        );
        let completed = value_to_opt_string(
            row.get_value(10)
                .map_err(|e| AppError::Internal(format!("list: read completed: {e}")))?,
        );
        let time_taken = value_to_opt_i64(
            row.get_value(11)
                .map_err(|e| AppError::Internal(format!("list: read time_taken: {e}")))?,
        );
        let grade = status
            .as_deref()
            .filter(|s| *s == "completed")
            .and_then(|_| score.map(grade_of));
        items.push(TestHistoryItem {
            id,
            test_mode,
            status,
            total_questions: total,
            score,
            raw_marks,
            wrong_count: wrong,
            unanswered_count: unanswered,
            negative_ratio: neg,
            started_at: started,
            completed_at: completed,
            time_taken_sec: time_taken,
            computed_grade: grade,
        });
    }
    let last_id = items.last().map(|it| it.id);
    let next = next_cursor(last_id, items.len(), limit);
    Ok(Json(TestListResponse {
        items,
        next_cursor: next,
    }))
}

/// Simple letter-grade mapping. Matches the buckets the FE cards use.
fn grade_of(pct: f64) -> &'static str {
    if pct >= 90.0 {
        "A"
    } else if pct >= 75.0 {
        "B"
    } else if pct >= 60.0 {
        "C"
    } else if pct >= 40.0 {
        "D"
    } else {
        "F"
    }
}

