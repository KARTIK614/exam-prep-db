//! `/api/v1/errors` — recent wrong answers for the current user.
//!
//! Reads `error_log` joined to `questions` + `topics`, ordered by
//! newest-first. Cursor pagination via `error_log.id`.
//!
//! Cross-user safety: every query is scoped by `user_id`.

use axum::extract::{Query, State};
use axum::Json;
use libsql::Value;
use serde::{Deserialize, Serialize};

use crate::api::pagination::{clamp_limit, decode_cursor, next_cursor};
use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::models::{value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Deserialize)]
pub struct ErrorsQuery {
    pub cursor: Option<String>,
    pub limit: Option<u32>,
}

#[derive(Debug, Serialize)]
pub struct ErrorItem {
    pub id: i64,
    pub question_id: i64,
    pub test_id: Option<i64>,
    pub topic_id: Option<i64>,
    pub topic_name: Option<String>,
    pub question_text: String,
    pub selected_option: Option<String>,
    pub correct_option: Option<String>,
    pub explanation: Option<String>,
    pub created_at: Option<String>,
    pub sr_box: Option<i64>,
    pub sr_due_at: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ErrorsResponse {
    pub items: Vec<ErrorItem>,
    pub next_cursor: Option<String>,
}

pub async fn list_errors(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Query(q): Query<ErrorsQuery>,
) -> Result<Json<ErrorsResponse>, AppError> {
    let limit = clamp_limit(q.limit);
    let after_id = decode_cursor(q.cursor.as_deref())?;

    let mut clauses = vec!["el.user_id = ?".to_string()];
    let mut vals: Vec<Value> = vec![Value::Integer(auth.id)];
    if let Some(id) = after_id {
        clauses.push("el.id < ?".into());
        vals.push(Value::Integer(id));
    }
    let where_sql = clauses.join(" AND ");
    let sql = format!(
        "SELECT el.id, el.question_id, el.test_id, q.topic_id, t.name, \
                q.question_text, el.selected_option, el.correct_option, \
                q.explanation, el.created_at, el.sr_box, el.sr_due_at \
         FROM error_log el \
         LEFT JOIN questions q ON q.id = el.question_id \
         LEFT JOIN topics t ON t.id = q.topic_id \
         WHERE {where_sql} \
         ORDER BY el.id DESC \
         LIMIT ?"
    );
    vals.push(Value::Integer(limit as i64 + 1));

    let mut rows = state.db.conn().query(&sql, vals).await?;
    let mut items = Vec::new();
    let mut last_id: Option<i64> = None;
    while let Some(row) = rows.next().await? {
        let id: i64 = row.get(0)?;
        last_id = Some(id);
        items.push(ErrorItem {
            id,
            question_id: row.get(1)?,
            test_id: value_to_opt_i64(row.get_value(2).unwrap_or(Value::Null)),
            topic_id: value_to_opt_i64(row.get_value(3).unwrap_or(Value::Null)),
            topic_name: value_to_opt_string(row.get_value(4).unwrap_or(Value::Null)),
            question_text: row.get::<String>(5).unwrap_or_default(),
            selected_option: value_to_opt_string(row.get_value(6).unwrap_or(Value::Null)),
            correct_option: value_to_opt_string(row.get_value(7).unwrap_or(Value::Null)),
            explanation: value_to_opt_string(row.get_value(8).unwrap_or(Value::Null)),
            created_at: value_to_opt_string(row.get_value(9).unwrap_or(Value::Null)),
            sr_box: value_to_opt_i64(row.get_value(10).unwrap_or(Value::Null)),
            sr_due_at: value_to_opt_string(row.get_value(11).unwrap_or(Value::Null)),
        });
    }

    let limit_us = limit as usize;
    let has_more = items.len() > limit_us;
    if has_more {
        items.truncate(limit_us);
    }
    let next = next_cursor(last_id, items.len(), limit);

    Ok(Json(ErrorsResponse {
        items,
        next_cursor: next,
    }))
}
