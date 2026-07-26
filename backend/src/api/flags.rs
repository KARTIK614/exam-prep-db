//! `POST /api/v1/questions/{qid}/flag` — structured user-side flagging.
//!
//! Category whitelist matches `bp_api.FLAG_CATEGORIES` exactly:
//!   wrong_answer | ambiguous | typo_question | typo_options |
//!   explanation_missing | duplicate | other
//!
//! Unknown categories are rejected with 400 (no silent coercion — the FE
//! ships the whitelist too, so any drift is a bug not a user typo).
//!
//! `note` is required when `category == "other"`; truncated to 1000 chars
//! for anything else (matches Flask's `note[:1000]` slice).

use axum::extract::{Path, State};
use axum::Json;
use libsql::params;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::schemas::flags::{FlagCreateRequest, FlagCreateResponse};

const CATEGORIES: &[&str] = &[
    "wrong_answer",
    "ambiguous",
    "typo_question",
    "typo_options",
    "explanation_missing",
    "duplicate",
    "other",
];

pub async fn flag_question(
    State(state): State<AppState>,
    RequireAuth(caller): RequireAuth,
    Path(qid): Path<i64>,
    Json(req): Json<FlagCreateRequest>,
) -> Result<Json<FlagCreateResponse>, AppError> {
    let category = req.category.trim();
    if !CATEGORIES.contains(&category) {
        return Err(AppError::BadRequest(format!(
            "invalid category '{category}'; expected one of: {}",
            CATEGORIES.join(", ")
        )));
    }

    let note_owned = req.note.map(|s| s.chars().take(1000).collect::<String>());
    let note = note_owned.as_deref().map(str::trim).map(str::to_string);

    if category == "other" {
        if note.as_deref().map(str::is_empty).unwrap_or(true) {
            return Err(AppError::BadRequest(
                "note is required when category='other'".into(),
            ));
        }
    }

    // Confirm the question exists (regardless of disabled state — an admin
    // may already have flagged-and-disabled it, but users don't need to
    // race for that).
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT 1 FROM questions WHERE id = ? LIMIT 1",
            params![qid],
        )
        .await?;
    if rows.next().await?.is_none() {
        return Err(AppError::NotFound("question"));
    }

    // VAPT H-2: if the caller supplied a test_id, verify they own the
    // test. Without this check any authed user could spam flags against
    // arbitrary tests, corrupting admin analytics.
    if let Some(test_id) = req.test_id {
        let mut rows = state
            .db
            .conn()
            .query(
                "SELECT 1 FROM mock_tests WHERE id = ?1 AND user_id = ?2 LIMIT 1",
                params![test_id, caller.id],
            )
            .await?;
        if rows.next().await?.is_none() {
            return Err(AppError::Forbidden);
        }
    }

    // Look up reporter username so admin UI can attribute without a join.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT username FROM users WHERE id = ? LIMIT 1",
            params![caller.id],
        )
        .await?;
    let reporter: Option<String> = match rows.next().await? {
        Some(row) => Some(row.get::<String>(0)?),
        None => None,
    };

    let insert_sql = "INSERT INTO question_flags \
        (question_id, test_id, reporter, category, note, status, created_at, user_id) \
        VALUES (?, ?, ?, ?, ?, 'open', CURRENT_TIMESTAMP, ?) \
        RETURNING id";
    let mut rows = state
        .db
        .conn()
        .query(
            insert_sql,
            params![
                qid,
                req.test_id,
                reporter,
                category.to_string(),
                note,
                caller.id,
            ],
        )
        .await?;
    let flag_id: i64 = match rows.next().await? {
        Some(row) => row.get::<i64>(0)?,
        None => return Err(AppError::Internal("INSERT ... RETURNING produced no row".into())),
    };

    Ok(Json(FlagCreateResponse { flag_id }))
}
