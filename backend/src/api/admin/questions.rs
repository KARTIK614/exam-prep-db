//! Admin CRUD over `questions`.
//!
//! Endpoints:
//!   POST   /api/v1/admin/questions
//!   PATCH  /api/v1/admin/questions/{id}
//!   DELETE /api/v1/admin/questions/{id}         (soft-delete: disabled=1)
//!   POST   /api/v1/admin/questions/bulk-toggle-disabled
//!
//! `updated_at` is stamped by the handler (not by a trigger) so writers
//! don't rely on Turso trigger semantics.

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::Json;
use chrono::Utc;
use libsql::params;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAdmin;
use crate::models::Question;
use crate::schemas::admin::{
    AdminQuestionCreateRequest, AdminQuestionPatchRequest, AdminQuestionResponse,
    BulkToggleDisabledRequest, BulkToggleDisabledResponse,
};

use super::bool_to_int;

// ---------- POST /admin/questions ------------------------------------------

pub async fn create_question(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Json(req): Json<AdminQuestionCreateRequest>,
) -> Result<(StatusCode, Json<AdminQuestionResponse>), AppError> {
    let correct = req.correct_option.trim().to_ascii_uppercase();
    if correct.len() != 1 || !matches!(correct.as_str(), "A" | "B" | "C" | "D") {
        return Err(AppError::BadRequest(
            "correct_option must be one of A|B|C|D".into(),
        ));
    }
    let now = Utc::now().to_rfc3339();

    let sql = "INSERT INTO questions \
        (topic_id, question_text, option_a, option_b, option_c, option_d, \
         correct_option, explanation, difficulty, source, confidence, \
         section, sub_topic, pyq_exam, pyq_year, review_notes, \
         disabled, updated_at) \
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?) \
        RETURNING id";

    let mut rows = state
        .db
        .conn()
        .query(
            sql,
            params![
                req.topic_id,
                req.question_text,
                req.option_a,
                req.option_b,
                req.option_c,
                req.option_d,
                correct,
                req.explanation,
                req.difficulty,
                req.source,
                req.confidence,
                req.section,
                req.sub_topic,
                req.pyq_exam,
                req.pyq_year,
                req.review_notes,
                now,
            ],
        )
        .await?;
    let new_id: i64 = match rows.next().await? {
        Some(row) => row.get::<i64>(0)?,
        None => return Err(AppError::Internal("INSERT ... RETURNING produced no row".into())),
    };
    let question = load_question(&state, new_id).await?;
    Ok((StatusCode::CREATED, Json(AdminQuestionResponse { question })))
}

// ---------- PATCH /admin/questions/{id} ------------------------------------

pub async fn patch_question(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Path(id): Path<i64>,
    Json(patch): Json<AdminQuestionPatchRequest>,
) -> Result<Json<AdminQuestionResponse>, AppError> {
    let mut set: Vec<String> = Vec::new();
    let mut vals: Vec<libsql::Value> = Vec::new();

    macro_rules! push_str {
        ($field:expr, $col:literal) => {
            if let Some(v) = $field {
                set.push(format!("{} = ?", $col));
                vals.push(libsql::Value::Text(v));
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
    if let Some(v) = patch.correct_option {
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
    push_str!(patch.confidence, "confidence");
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
        return Err(AppError::BadRequest("empty patch: nothing to update".into()));
    }
    set.push("updated_at = ?".into());
    vals.push(libsql::Value::Text(Utc::now().to_rfc3339()));

    let sql = format!("UPDATE questions SET {} WHERE id = ?", set.join(", "));
    vals.push(libsql::Value::Integer(id));

    state.db.conn().execute(&sql, vals).await?;
    let question = load_question(&state, id).await?;
    Ok(Json(AdminQuestionResponse { question }))
}

// ---------- DELETE /admin/questions/{id} -----------------------------------

/// Soft-delete: set `disabled = 1`. Preserves referential integrity for
/// past mock_tests + error_log rows that reference this question.
pub async fn delete_question(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Path(id): Path<i64>,
) -> Result<Json<AdminQuestionResponse>, AppError> {
    state
        .db
        .conn()
        .execute(
            "UPDATE questions SET disabled = 1, updated_at = ? WHERE id = ?",
            params![Utc::now().to_rfc3339(), id],
        )
        .await?;
    let question = load_question(&state, id).await?;
    Ok(Json(AdminQuestionResponse { question }))
}

// ---------- POST /admin/questions/bulk-toggle-disabled ---------------------

pub async fn bulk_toggle_disabled(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Json(req): Json<BulkToggleDisabledRequest>,
) -> Result<Json<BulkToggleDisabledResponse>, AppError> {
    if req.ids.is_empty() {
        return Ok(Json(BulkToggleDisabledResponse {
            updated: 0,
            disabled: req.disabled,
        }));
    }
    // VAPT M-4: hard-cap the input so a runaway admin script (or a
    // compromised admin token) can't lock the DB behind a 1M-row IN().
    const MAX_BULK_IDS: usize = 5_000;
    if req.ids.len() > MAX_BULK_IDS {
        return Err(AppError::BadRequest(format!(
            "too many ids: {} (limit {})",
            req.ids.len(),
            MAX_BULK_IDS
        )));
    }
    // Chunk into batches of 200 to stay under the parameter-count limit.
    let disabled_int = bool_to_int(req.disabled);
    let now = Utc::now().to_rfc3339();
    let mut total = 0usize;
    for chunk in req.ids.chunks(200) {
        let placeholders = std::iter::repeat("?")
            .take(chunk.len())
            .collect::<Vec<_>>()
            .join(",");
        let sql = format!(
            "UPDATE questions SET disabled = ?, updated_at = ? WHERE id IN ({placeholders})"
        );
        let mut vals: Vec<libsql::Value> = Vec::with_capacity(chunk.len() + 2);
        vals.push(libsql::Value::Integer(disabled_int));
        vals.push(libsql::Value::Text(now.clone()));
        for id in chunk {
            vals.push(libsql::Value::Integer(*id));
        }
        state.db.conn().execute(&sql, vals).await?;
        total += chunk.len();
    }
    Ok(Json(BulkToggleDisabledResponse {
        updated: total,
        disabled: req.disabled,
    }))
}

// ---------- helpers --------------------------------------------------------

async fn load_question(state: &AppState, id: i64) -> Result<Question, AppError> {
    let cols = Question::COLUMNS
        .iter()
        .map(|c| format!("q.{c}"))
        .collect::<Vec<_>>()
        .join(", ");
    let sql = format!("SELECT {cols} FROM questions q WHERE q.id = ? LIMIT 1");
    let mut rows = state.db.conn().query(&sql, params![id]).await?;
    match rows.next().await? {
        Some(row) => Ok(Question::from_row(&row)?),
        None => Err(AppError::NotFound("question")),
    }
}
