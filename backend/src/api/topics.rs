//! `/api/v1/topics` handlers.
//!
//! Endpoints wired by `api::mod::router`:
//!   GET  /topics         — list all topics (ordered by paper, id)
//!   GET  /topics/{id}    — single topic + live question count
//!
//! Both handlers require any authenticated user via `RequireAuth`.
//! No admin gating, no pagination — the topics list is small (~30 rows)
//! so a full read is cheap.

use axum::extract::{Path, State};
use axum::Json;
use libsql::params;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::models::Topic;
use crate::schemas::content::TopicWithCount;

/// GET /topics — return every topic ordered by (paper, id).
pub async fn list_topics(
    State(state): State<AppState>,
    RequireAuth(_): RequireAuth,
) -> Result<Json<Vec<Topic>>, AppError> {
    let sql = format!(
        "SELECT {} FROM topics ORDER BY COALESCE(paper, ''), id",
        Topic::COLUMNS.join(", ")
    );
    let mut rows = state.db.conn().query(&sql, ()).await?;
    let mut out = Vec::new();
    while let Some(row) = rows.next().await? {
        out.push(Topic::from_row(&row)?);
    }
    Ok(Json(out))
}

/// GET /topics/{id} — one topic with a live `question_count`.
///
/// 404 if the topic doesn't exist. `question_count` excludes disabled
/// rows (matches the filter used everywhere else in this module).
pub async fn get_topic(
    State(state): State<AppState>,
    RequireAuth(_): RequireAuth,
    Path(id): Path<i64>,
) -> Result<Json<TopicWithCount>, AppError> {
    let sql = format!(
        "SELECT {} FROM topics WHERE id = ?1 LIMIT 1",
        Topic::COLUMNS.join(", ")
    );
    let mut rows = state.db.conn().query(&sql, params![id]).await?;
    let topic = match rows.next().await? {
        Some(row) => Topic::from_row(&row)?,
        None => return Err(AppError::NotFound("topic")),
    };

    // Second round-trip for the count. Cheap on an indexed column, and
    // keeping it separate lets the topic detail endpoint remain a plain
    // read even if this ever becomes a subquery-heavy join.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT COUNT(*) FROM questions \
             WHERE topic_id = ?1 AND (disabled = 0 OR disabled IS NULL)",
            params![id],
        )
        .await?;
    let question_count = match rows.next().await? {
        Some(row) => row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("read topic count: {e}")))?,
        None => 0,
    };

    Ok(Json(TopicWithCount {
        topic,
        question_count,
    }))
}
