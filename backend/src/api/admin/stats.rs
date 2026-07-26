//! GET /api/v1/admin/stats
//!
//! Small dashboard rollup — one row per widget on the admin landing page.
//! Every count is a scalar `COUNT(*)`; we run them serially rather than in
//! parallel because the libsql remote connection is single-lane.

use axum::extract::State;
use axum::Json;
use libsql::params;
use serde::Serialize;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAdmin;
use crate::models::{value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Serialize)]
pub struct RecentFlag {
    pub id: i64,
    pub question_id: i64,
    pub category: Option<String>,
    pub note: Option<String>,
    pub created_at: Option<String>,
    pub question_text: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct AdminStatsResponse {
    pub flags_open: i64,
    pub flags_total: i64,
    pub questions: i64,
    pub questions_disabled: i64,
    pub topics: i64,
    pub users: i64,
    pub uploads: i64,
    pub review_medium: i64,
    pub review_synthetic: i64,
    pub deficit_topics: i64,
    pub recent_flags: Vec<RecentFlag>,
}

async fn count(state: &AppState, sql: &str) -> Result<i64, AppError> {
    let mut rows = state.db.conn().query(sql, ()).await?;
    match rows.next().await? {
        Some(row) => Ok(row.get::<i64>(0).unwrap_or(0)),
        None => Ok(0),
    }
}

pub async fn get_stats(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
) -> Result<Json<AdminStatsResponse>, AppError> {
    // NB: table is `question_flags` (matches the FE flag-submit path
    // and every other admin query). The earlier `flags` alias in this
    // file 500'd the dashboard the moment an admin loaded it.
    let flags_open = count(
        &state,
        "SELECT COUNT(*) FROM question_flags WHERE status = 'open'",
    )
    .await?;
    let flags_total = count(&state, "SELECT COUNT(*) FROM question_flags").await?;
    let questions = count(
        &state,
        "SELECT COUNT(*) FROM questions WHERE (disabled IS NULL OR disabled = 0)",
    )
    .await?;
    let questions_disabled =
        count(&state, "SELECT COUNT(*) FROM questions WHERE disabled = 1").await?;
    let topics = count(&state, "SELECT COUNT(*) FROM topics").await?;
    let users = count(&state, "SELECT COUNT(*) FROM users").await?;
    let uploads = count(&state, "SELECT COUNT(*) FROM pdf_uploads").await.unwrap_or(0);
    let review_medium = count(
        &state,
        "SELECT COUNT(*) FROM questions WHERE confidence = 'medium' \
         AND (disabled IS NULL OR disabled = 0)",
    )
    .await?;
    let review_synthetic = count(
        &state,
        "SELECT COUNT(*) FROM questions WHERE source = 'synthetic' \
         AND (disabled IS NULL OR disabled = 0)",
    )
    .await
    .unwrap_or(0);
    // Topics with fewer than 20 active questions — the "we need more content
    // here" signal on the admin landing page.
    let deficit_topics = count(
        &state,
        "SELECT COUNT(*) FROM ( \
           SELECT t.id FROM topics t \
           LEFT JOIN questions q ON q.topic_id = t.id \
             AND (q.disabled IS NULL OR q.disabled = 0) \
           GROUP BY t.id HAVING COUNT(q.id) < 20 \
         )",
    )
    .await?;

    // recent_flags — join to questions for the FE preview snippet.
    let flag_sql = "SELECT f.id, f.question_id, f.category, f.note, f.created_at, \
                           q.question_text \
                    FROM question_flags f \
                    LEFT JOIN questions q ON q.id = f.question_id \
                    ORDER BY f.created_at DESC \
                    LIMIT 5";
    let mut rows = state.db.conn().query(flag_sql, params![]).await?;
    let mut recent_flags: Vec<RecentFlag> = Vec::new();
    while let Some(row) = rows.next().await? {
        recent_flags.push(RecentFlag {
            id: row.get::<i64>(0).unwrap_or(0),
            question_id: value_to_opt_i64(row.get_value(1).unwrap_or(libsql::Value::Null))
                .unwrap_or(0),
            category: value_to_opt_string(row.get_value(2).unwrap_or(libsql::Value::Null)),
            note: value_to_opt_string(row.get_value(3).unwrap_or(libsql::Value::Null)),
            created_at: value_to_opt_string(row.get_value(4).unwrap_or(libsql::Value::Null)),
            question_text: value_to_opt_string(row.get_value(5).unwrap_or(libsql::Value::Null)),
        });
    }

    Ok(Json(AdminStatsResponse {
        flags_open,
        flags_total,
        questions,
        questions_disabled,
        topics,
        users,
        uploads,
        review_medium,
        review_synthetic,
        deficit_topics,
        recent_flags,
    }))
}
