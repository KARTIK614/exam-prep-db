//! `/api/v1/bookmarks/*` — user-scoped question bookmarks.
//!
//! Endpoints wired by `api::mod::router`:
//!   GET  /bookmarks             — cursor-paginated list of current user's stars
//!   POST /bookmarks/{qid}       — idempotent toggle (star / unstar)
//!
//! Ownership: every SELECT/INSERT/DELETE carries `WHERE user_id = ?` — the
//! DB has a UNIQUE INDEX on (user_id, question_id) so `INSERT OR IGNORE`
//! is a lossless no-op when the row already exists.
//!
//! Cursor: base64url(bookmark_id.to_string()) — see `api::pagination`.

use axum::extract::{Path, Query, State};
use axum::Json;
use libsql::params;

use crate::api::pagination::{clamp_limit, decode_cursor, next_cursor};
use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::models::{value_to_opt_string, value_to_opt_i64};
use crate::schemas::bookmarks::{
    BookmarkListQuery, BookmarkListResponse, BookmarkRow, BookmarkToggleResponse,
};

// ---------- GET /bookmarks -------------------------------------------------

pub async fn list_bookmarks(
    State(state): State<AppState>,
    RequireAuth(caller): RequireAuth,
    Query(q): Query<BookmarkListQuery>,
) -> Result<Json<BookmarkListResponse>, AppError> {
    let limit = clamp_limit(q.limit);
    let after_id = decode_cursor(q.cursor.as_deref())?;

    // Bookmark id, question payload, topic name, timestamps.
    // Left-joined topic so a stale question still renders.
    let mut sql = String::from(
        "SELECT b.id, b.question_id, q.question_text, q.option_a, q.option_b, \
                q.option_c, q.option_d, q.correct_option, q.difficulty, \
                t.name AS topic_name, b.created_at, b.note \
           FROM bookmarks b \
           JOIN questions q ON q.id = b.question_id \
           LEFT JOIN topics t ON t.id = q.topic_id \
          WHERE b.user_id = ? \
            AND (q.disabled = 0 OR q.disabled IS NULL) ",
    );
    let mut vals: Vec<libsql::Value> = vec![libsql::Value::Integer(caller.id)];
    if let Some(id) = after_id {
        sql.push_str(" AND b.id > ? ");
        vals.push(libsql::Value::Integer(id));
    }
    sql.push_str(" ORDER BY b.id ASC LIMIT ?");
    vals.push(libsql::Value::Integer(limit as i64));

    let mut rows = state.db.conn().query(&sql, vals).await?;
    let mut items: Vec<BookmarkRow> = Vec::with_capacity(limit as usize);
    while let Some(row) = rows.next().await? {
        items.push(BookmarkRow {
            bookmark_id: row.get::<i64>(0)?,
            question_id: row.get::<i64>(1)?,
            question_text: value_to_opt_string(row.get_value(2)?),
            option_a: value_to_opt_string(row.get_value(3)?),
            option_b: value_to_opt_string(row.get_value(4)?),
            option_c: value_to_opt_string(row.get_value(5)?),
            option_d: value_to_opt_string(row.get_value(6)?),
            correct_option: value_to_opt_string(row.get_value(7)?),
            difficulty: value_to_opt_string(row.get_value(8)?),
            topic_name: value_to_opt_string(row.get_value(9)?),
            created_at: value_to_opt_string(row.get_value(10)?),
            note: value_to_opt_string(row.get_value(11)?),
        });
    }

    let last_id = items.last().map(|b| b.bookmark_id);
    Ok(Json(BookmarkListResponse {
        next_cursor: next_cursor(last_id, items.len(), limit),
        items,
    }))
}

// ---------- POST /bookmarks/{qid} ------------------------------------------

/// Idempotent star/unstar. Returns the *new* state.
///
/// Two-round-trip design (SELECT-then-INSERT-or-DELETE) rather than a
/// single `INSERT OR IGNORE` + delta check, because libsql's remote
/// transport doesn't surface "rowcount" per-statement in a portable way.
pub async fn toggle_bookmark(
    State(state): State<AppState>,
    RequireAuth(caller): RequireAuth,
    Path(qid): Path<i64>,
) -> Result<Json<BookmarkToggleResponse>, AppError> {
    // Confirm the question exists + isn't disabled — 404 rather than a
    // stale bookmark that never resolves.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT 1 FROM questions \
              WHERE id = ? AND (disabled = 0 OR disabled IS NULL) LIMIT 1",
            params![qid],
        )
        .await?;
    if rows.next().await?.is_none() {
        return Err(AppError::NotFound("question"));
    }

    // Currently bookmarked?
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT id FROM bookmarks WHERE user_id = ? AND question_id = ? LIMIT 1",
            params![caller.id, qid],
        )
        .await?;
    let existing_id: Option<i64> = match rows.next().await? {
        Some(row) => value_to_opt_i64(row.get_value(0)?),
        None => None,
    };

    if let Some(bid) = existing_id {
        state
            .db
            .conn()
            .execute(
                "DELETE FROM bookmarks WHERE id = ? AND user_id = ?",
                params![bid, caller.id],
            )
            .await?;
        Ok(Json(BookmarkToggleResponse { bookmarked: false }))
    } else {
        state
            .db
            .conn()
            .execute(
                "INSERT OR IGNORE INTO bookmarks (user_id, question_id, created_at) \
                 VALUES (?, ?, CURRENT_TIMESTAMP)",
                params![caller.id, qid],
            )
            .await?;
        Ok(Json(BookmarkToggleResponse { bookmarked: true }))
    }
}
