//! Admin-side flag queue.
//!
//! Endpoints:
//!   GET  /api/v1/admin/flags?status=open|resolved|dismissed|all
//!   POST /api/v1/admin/flags/{id}/{action}
//!        where action ∈ resolve | reject | disable_question
//!
//! Query joins `question_flags × questions × topics` so the FE can render
//! a card without extra round-trips.

use axum::extract::{Path, Query, State};
use axum::Json;
use chrono::Utc;
use libsql::params;

use crate::api::pagination::{clamp_limit, decode_cursor, next_cursor};
use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAdmin;
use crate::models::{int_to_bool, value_to_opt_i64, value_to_opt_string};
use crate::schemas::admin::{
    AdminFlagActionResponse, AdminFlagListQuery, AdminFlagListResponse, AdminFlagRow,
};

// ---------- GET /admin/flags -----------------------------------------------

pub async fn list_flags(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Query(q): Query<AdminFlagListQuery>,
) -> Result<Json<AdminFlagListResponse>, AppError> {
    let limit = clamp_limit(q.limit);
    let after_id = decode_cursor(q.cursor.as_deref())?;
    let status = q.status.as_deref().unwrap_or("open");

    let mut sql = String::from(
        "SELECT f.id, f.question_id, f.test_id, f.reporter, f.user_id, \
                f.category, f.note, f.status, f.created_at, f.resolved_at, \
                q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, \
                q.correct_option, q.disabled, t.name AS topic_name \
           FROM question_flags f \
           LEFT JOIN questions q ON q.id = f.question_id \
           LEFT JOIN topics t ON t.id = q.topic_id ",
    );
    let mut vals: Vec<libsql::Value> = Vec::new();
    let mut wheres: Vec<&'static str> = Vec::new();
    let status_string;
    if status != "all" {
        wheres.push("f.status = ?");
        status_string = status.to_string();
        vals.push(libsql::Value::Text(status_string));
    }
    if let Some(id) = after_id {
        wheres.push("f.id > ?");
        vals.push(libsql::Value::Integer(id));
    }
    if !wheres.is_empty() {
        sql.push_str(" WHERE ");
        sql.push_str(&wheres.join(" AND "));
    }
    sql.push_str(" ORDER BY f.id ASC LIMIT ?");
    vals.push(libsql::Value::Integer(limit as i64));

    let mut rows = state.db.conn().query(&sql, vals).await?;
    let mut items: Vec<AdminFlagRow> = Vec::with_capacity(limit as usize);
    while let Some(row) = rows.next().await? {
        items.push(AdminFlagRow {
            id: row.get::<i64>(0)?,
            question_id: value_to_opt_i64(row.get_value(1)?),
            test_id: value_to_opt_i64(row.get_value(2)?),
            reporter: value_to_opt_string(row.get_value(3)?),
            user_id: value_to_opt_i64(row.get_value(4)?),
            category: value_to_opt_string(row.get_value(5)?),
            note: value_to_opt_string(row.get_value(6)?),
            status: value_to_opt_string(row.get_value(7)?),
            created_at: value_to_opt_string(row.get_value(8)?),
            resolved_at: value_to_opt_string(row.get_value(9)?),
            question_text: value_to_opt_string(row.get_value(10)?),
            option_a: value_to_opt_string(row.get_value(11)?),
            option_b: value_to_opt_string(row.get_value(12)?),
            option_c: value_to_opt_string(row.get_value(13)?),
            option_d: value_to_opt_string(row.get_value(14)?),
            correct_option: value_to_opt_string(row.get_value(15)?),
            question_disabled: int_to_bool(value_to_opt_i64(row.get_value(16)?)),
            topic_name: value_to_opt_string(row.get_value(17)?),
        });
    }
    let last_id = items.last().map(|f| f.id);
    Ok(Json(AdminFlagListResponse {
        next_cursor: next_cursor(last_id, items.len(), limit),
        items,
    }))
}

// ---------- POST /admin/flags/{id}/{action} --------------------------------

pub async fn flag_action(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Path((flag_id, action)): Path<(i64, String)>,
) -> Result<Json<AdminFlagActionResponse>, AppError> {
    let now = Utc::now().to_rfc3339();
    // Load the flag so we can address side-effects (e.g. disable-question).
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT question_id FROM question_flags WHERE id = ? LIMIT 1",
            params![flag_id],
        )
        .await?;
    let qid: Option<i64> = match rows.next().await? {
        Some(row) => value_to_opt_i64(row.get_value(0)?),
        None => return Err(AppError::NotFound("flag")),
    };

    match action.as_str() {
        "resolve" => {
            state
                .db
                .conn()
                .execute(
                    "UPDATE question_flags SET status = 'resolved', resolved_at = ? WHERE id = ?",
                    params![now.clone(), flag_id],
                )
                .await?;
            Ok(Json(AdminFlagActionResponse {
                ok: true,
                question_id_disabled: None,
            }))
        }
        "reject" => {
            state
                .db
                .conn()
                .execute(
                    "UPDATE question_flags SET status = 'dismissed', resolved_at = ? WHERE id = ?",
                    params![now.clone(), flag_id],
                )
                .await?;
            Ok(Json(AdminFlagActionResponse {
                ok: true,
                question_id_disabled: None,
            }))
        }
        "disable_question" => {
            let Some(question_id) = qid else {
                return Err(AppError::BadRequest(
                    "flag has no question_id — cannot disable".into(),
                ));
            };
            // Disable the question + mark the flag resolved in one logical
            // step. If the second UPDATE fails the first is still fine —
            // the question is disabled which is the safer of the two.
            state
                .db
                .conn()
                .execute(
                    "UPDATE questions SET disabled = 1, updated_at = ? WHERE id = ?",
                    params![now.clone(), question_id],
                )
                .await?;
            state
                .db
                .conn()
                .execute(
                    "UPDATE question_flags SET status = 'resolved', resolved_at = ? WHERE id = ?",
                    params![now.clone(), flag_id],
                )
                .await?;
            Ok(Json(AdminFlagActionResponse {
                ok: true,
                question_id_disabled: Some(question_id),
            }))
        }
        other => Err(AppError::BadRequest(format!(
            "unknown action '{other}' — expected resolve|reject|disable_question"
        ))),
    }
}
