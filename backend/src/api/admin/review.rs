//! Admin mid-confidence review queue.
//!
//! Endpoints:
//!   GET  /api/v1/admin/review?filter=all|medium|has_notes|synthetic|deferred
//!   POST /api/v1/admin/review/{question_id}
//!        {action: confirm|edit|disable|defer, patch?: AdminQuestionPatchRequest}
//!
//! Actions:
//!   confirm — sets confidence='high' + confidence_reviewed_at=now.
//!   edit    — applies the caller-supplied field patch, then confirms.
//!   disable — sets disabled=1.
//!   defer   — appends "[deferred @ts]" to review_notes so it drops out of
//!             the default queue but stays discoverable.

use axum::extract::{Path, Query, State};
use axum::Json;
use chrono::Utc;
use libsql::params;

use crate::api::pagination::{clamp_limit, decode_cursor, next_cursor};
use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAdmin;
use crate::models::{value_to_opt_string, Question};
use crate::schemas::admin::{
    AdminQuestionPatchRequest, AdminReviewActionRequest, AdminReviewActionResponse,
    AdminReviewCounts, AdminReviewListResponse, AdminReviewQuery,
};

use super::bool_to_int;

// ---------- GET /admin/review ----------------------------------------------

pub async fn list_review(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Query(q): Query<AdminReviewQuery>,
) -> Result<Json<AdminReviewListResponse>, AppError> {
    let limit = clamp_limit(q.limit);
    let after_id = decode_cursor(q.cursor.as_deref())?;
    let filter = q.filter.as_deref().unwrap_or("medium");

    let mut wheres: Vec<String> =
        vec!["(q.disabled = 0 OR q.disabled IS NULL)".to_string()];
    match filter {
        "medium" => wheres.push("q.confidence = 'medium'".into()),
        "has_notes" => wheres.push("q.review_notes IS NOT NULL AND q.review_notes <> ''".into()),
        "synthetic" => wheres.push("q.source LIKE 'synthetic-v%'".into()),
        "deferred" => wheres.push("q.review_notes LIKE '%[deferred%'".into()),
        "non_high" => wheres.push("(q.confidence IS NULL OR q.confidence <> 'high')".into()),
        "all" => {}
        other => {
            return Err(AppError::BadRequest(format!(
                "unknown filter '{other}' — expected all|medium|has_notes|synthetic|deferred|non_high"
            )));
        }
    }

    let counts = compute_counts(&state).await?;
    let mut vals: Vec<libsql::Value> = Vec::new();
    if let Some(id) = after_id {
        wheres.push("q.id > ?".into());
        vals.push(libsql::Value::Integer(id));
    }

    let cols = Question::COLUMNS
        .iter()
        .map(|c| format!("q.{c}"))
        .collect::<Vec<_>>()
        .join(", ");
    let sql = format!(
        "SELECT {cols} FROM questions q \
          WHERE {} \
          ORDER BY q.id ASC LIMIT ?",
        wheres.join(" AND ")
    );
    vals.push(libsql::Value::Integer(limit as i64));

    let mut rows = state.db.conn().query(&sql, vals).await?;
    let mut items: Vec<Question> = Vec::with_capacity(limit as usize);
    while let Some(row) = rows.next().await? {
        items.push(Question::from_row(&row)?);
    }
    let last_id = items.last().map(|q| q.id);
    Ok(Json(AdminReviewListResponse {
        next_cursor: next_cursor(last_id, items.len(), limit),
        items,
        counts,
    }))
}

async fn compute_counts(state: &AppState) -> Result<AdminReviewCounts, AppError> {
    // Inline helper — closure-returning-async-move had a lifetime issue with
    // the borrowed &str; simpler to call inline per query.
    async fn count(state: &AppState, sql: &str) -> Result<i64, AppError> {
        let mut rows = state.db.conn().query(sql, ()).await?;
        Ok(match rows.next().await? {
            Some(row) => row.get::<i64>(0)?,
            None => 0,
        })
    }

    let mut c = AdminReviewCounts::default();
    c.medium = count(
        state,
        "SELECT COUNT(*) FROM questions \
          WHERE (disabled=0 OR disabled IS NULL) AND confidence = 'medium'",
    )
    .await?;
    c.has_notes = count(
        state,
        "SELECT COUNT(*) FROM questions \
          WHERE (disabled=0 OR disabled IS NULL) \
            AND review_notes IS NOT NULL AND review_notes <> ''",
    )
    .await?;
    c.synthetic = count(
        state,
        "SELECT COUNT(*) FROM questions \
          WHERE (disabled=0 OR disabled IS NULL) AND source LIKE 'synthetic-v%'",
    )
    .await?;
    c.deferred = count(
        state,
        "SELECT COUNT(*) FROM questions \
          WHERE (disabled=0 OR disabled IS NULL) AND review_notes LIKE '%[deferred%'",
    )
    .await?;
    c.non_high = count(
        state,
        "SELECT COUNT(*) FROM questions \
          WHERE (disabled=0 OR disabled IS NULL) \
            AND (confidence IS NULL OR confidence <> 'high')",
    )
    .await?;
    Ok(c)
}

// ---------- POST /admin/review/{question_id} -------------------------------

pub async fn act_on_review(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Path(qid): Path<i64>,
    Json(req): Json<AdminReviewActionRequest>,
) -> Result<Json<AdminReviewActionResponse>, AppError> {
    let now = Utc::now().to_rfc3339();
    match req.action.as_str() {
        "confirm" => {
            state
                .db
                .conn()
                .execute(
                    "UPDATE questions SET confidence = 'high', \
                        confidence_reviewed_at = ?, updated_at = ? WHERE id = ?",
                    params![now.clone(), now.clone(), qid],
                )
                .await?;
            Ok(Json(AdminReviewActionResponse {
                ok: true,
                confidence: Some("high".into()),
                disabled: None,
            }))
        }
        "edit" => {
            let patch = req.patch.unwrap_or_else(AdminQuestionPatchRequest::default);
            apply_patch(&state, qid, &patch, &now).await?;
            state
                .db
                .conn()
                .execute(
                    "UPDATE questions SET confidence = 'high', \
                        confidence_reviewed_at = ?, updated_at = ? WHERE id = ?",
                    params![now.clone(), now.clone(), qid],
                )
                .await?;
            Ok(Json(AdminReviewActionResponse {
                ok: true,
                confidence: Some("high".into()),
                disabled: None,
            }))
        }
        "disable" => {
            state
                .db
                .conn()
                .execute(
                    "UPDATE questions SET disabled = 1, updated_at = ? WHERE id = ?",
                    params![now.clone(), qid],
                )
                .await?;
            Ok(Json(AdminReviewActionResponse {
                ok: true,
                confidence: None,
                disabled: Some(true),
            }))
        }
        "defer" => {
            // Append a marker to review_notes so the deferred filter picks it up.
            let mut rows = state
                .db
                .conn()
                .query(
                    "SELECT review_notes FROM questions WHERE id = ? LIMIT 1",
                    params![qid],
                )
                .await?;
            let existing = match rows.next().await? {
                Some(row) => value_to_opt_string(row.get_value(0)?),
                None => return Err(AppError::NotFound("question")),
            };
            let mut next_note = existing.unwrap_or_default();
            if !next_note.is_empty() {
                next_note.push_str("\n");
            }
            next_note.push_str(&format!("[deferred @{now}]"));
            state
                .db
                .conn()
                .execute(
                    "UPDATE questions SET review_notes = ?, updated_at = ? WHERE id = ?",
                    params![next_note, now.clone(), qid],
                )
                .await?;
            Ok(Json(AdminReviewActionResponse {
                ok: true,
                confidence: None,
                disabled: None,
            }))
        }
        other => Err(AppError::BadRequest(format!(
            "unknown action '{other}' — expected confirm|edit|disable|defer"
        ))),
    }
}

async fn apply_patch(
    state: &AppState,
    qid: i64,
    patch: &AdminQuestionPatchRequest,
    now: &str,
) -> Result<(), AppError> {
    let mut set: Vec<String> = Vec::new();
    let mut vals: Vec<libsql::Value> = Vec::new();

    macro_rules! push_str {
        ($field:expr, $col:literal) => {
            if let Some(v) = $field.as_ref() {
                set.push(format!("{} = ?", $col));
                vals.push(libsql::Value::Text(v.clone()));
            }
        };
    }
    macro_rules! push_int {
        ($field:expr, $col:literal) => {
            if let Some(v) = $field {
                set.push(format!("{} = ?", $col));
                vals.push(libsql::Value::Integer(v));
            }
        };
    }

    push_int!(patch.topic_id, "topic_id");
    push_str!(patch.question_text, "question_text");
    push_str!(patch.option_a, "option_a");
    push_str!(patch.option_b, "option_b");
    push_str!(patch.option_c, "option_c");
    push_str!(patch.option_d, "option_d");
    if let Some(v) = patch.correct_option.as_ref() {
        let up = v.trim().to_ascii_uppercase();
        if up.len() != 1 || !matches!(up.as_str(), "A" | "B" | "C" | "D") {
            return Err(AppError::BadRequest(
                "correct_option must be one of A|B|C|D".into(),
            ));
        }
        set.push("correct_option = ?".into());
        vals.push(libsql::Value::Text(up));
    }
    push_str!(patch.explanation, "explanation");
    push_str!(patch.difficulty, "difficulty");
    push_str!(patch.source, "source");
    // Deliberately skip patch.confidence — the review action decides that.
    push_str!(patch.section, "section");
    push_str!(patch.sub_topic, "sub_topic");
    push_str!(patch.pyq_exam, "pyq_exam");
    push_int!(patch.pyq_year, "pyq_year");
    push_str!(patch.review_notes, "review_notes");
    if let Some(v) = patch.disabled {
        set.push("disabled = ?".into());
        vals.push(libsql::Value::Integer(bool_to_int(v)));
    }
    if set.is_empty() {
        return Ok(());
    }
    set.push("updated_at = ?".into());
    vals.push(libsql::Value::Text(now.to_string()));
    let sql = format!("UPDATE questions SET {} WHERE id = ?", set.join(", "));
    vals.push(libsql::Value::Integer(qid));
    state.db.conn().execute(&sql, vals).await?;
    Ok(())
}
