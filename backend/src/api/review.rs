//! `/api/v1/review/*` — SRS review API surface.
//!
//! Endpoints (all require `RequireAuth`, all scope by user_id):
//!
//!   GET  /review/queue                — cards due today + queue summary
//!   POST /review/answers/{card_id}    — advance one card via Leitner rules
//!
//! Semantics ported from `bp_review.py` (Flask) + `sr.py`:
//!   * `card_id` = `error_log.id`.
//!   * Queue filter: `date(sr_due_at) <= date('now')`, disabled questions
//!     excluded (`disabled = 0 OR disabled IS NULL`).
//!   * Order: `sr_due_at ASC, sr_box ASC` (oldest-due first, box-1 before
//!     box-5 within the same due date).
//!   * On answer: `sr_box` is advanced via `services::sr::next_box`,
//!     `sr_due_at` via `services::sr::next_due`, and `sr_last_reviewed`
//!     is stamped with the current UTC time.
//!
//! Cross-user safety: every query filters `error_log.user_id = caller`;
//! `POST /answers/{card_id}` also re-verifies ownership before mutating.

use axum::extract::{Path, Query, State};
use axum::Json;
use chrono::{NaiveDate, Utc};
use libsql::params;

use crate::api::pagination::clamp_limit;
use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::models::{value_to_opt_i64, value_to_opt_string};
use crate::schemas::review::{
    ReviewAnswerRequest, ReviewAnswerResponse, ReviewCard, ReviewQuestion,
    ReviewQueueQuery, ReviewQueueResponse,
};
use crate::services::sr;

// ---------- GET /review/queue --------------------------------------------

/// Return cards due today plus a summary of what's in each Leitner box.
pub async fn get_queue(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Query(q): Query<ReviewQueueQuery>,
) -> Result<Json<ReviewQueueResponse>, AppError> {
    let limit = clamp_limit(q.limit);

    // ---- due_today count ------------------------------------------------
    // Cheap COUNT so the FE can show a "N cards due" pill even when it
    // doesn't render the full list.
    let due_today_sql = "SELECT COUNT(*) FROM error_log el \
                         JOIN questions q ON q.id = el.question_id \
                         WHERE el.user_id = ?1 \
                           AND (q.disabled IS NULL OR q.disabled = 0) \
                           AND date(el.sr_due_at) <= date('now')";
    let due_today: i64 = match state
        .db
        .conn()
        .query(due_today_sql, params![auth.id])
        .await
    {
        Ok(mut rows) => match rows.next().await {
            Ok(Some(row)) => row.get::<i64>(0).unwrap_or(0),
            _ => 0,
        },
        Err(_) => 0,
    };

    // ---- by_box counts --------------------------------------------------
    // COALESCE(sr_box, 1) so a row with a NULL box still lands in bucket 1.
    let by_box_sql = "SELECT COALESCE(sr_box, 1) AS b, COUNT(*) \
                      FROM error_log \
                      WHERE user_id = ?1 \
                      GROUP BY b";
    let mut by_box: [i64; 5] = [0; 5];
    if let Ok(mut rows) = state
        .db
        .conn()
        .query(by_box_sql, params![auth.id])
        .await
    {
        while let Ok(Some(row)) = rows.next().await {
            let b = row.get::<i64>(0).unwrap_or(1);
            let c = row.get::<i64>(1).unwrap_or(0);
            if (1..=5).contains(&b) {
                by_box[(b - 1) as usize] = c;
            }
        }
    }

    // ---- due-today card list -------------------------------------------
    // Preserves the SELECT list from `sr.py::get_due_reviews` — same
    // columns so the FE contract mirrors the Flask template hydration.
    let list_sql = "SELECT el.id AS card_id, \
                           el.sr_box, el.sr_due_at, el.sr_last_reviewed, \
                           q.id AS question_id, q.question_text, \
                           q.option_a, q.option_b, q.option_c, q.option_d, \
                           q.correct_option, q.explanation, q.difficulty, \
                           t.id AS topic_id, t.name AS topic_name \
                    FROM error_log el \
                    JOIN questions q ON q.id = el.question_id \
                    JOIN topics t ON t.id = el.topic_id \
                    WHERE el.user_id = ?1 \
                      AND (q.disabled IS NULL OR q.disabled = 0) \
                      AND date(el.sr_due_at) <= date('now') \
                    ORDER BY el.sr_due_at ASC, el.sr_box ASC \
                    LIMIT ?2";
    let mut rows = state
        .db
        .conn()
        .query(list_sql, params![auth.id, limit as i64])
        .await?;
    let mut cards: Vec<ReviewCard> = Vec::new();
    while let Some(row) = rows.next().await? {
        let card_id: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("queue: read card_id: {e}")))?;
        let box_num = value_to_opt_i64(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("queue: read sr_box: {e}")))?,
        )
        .unwrap_or(1);
        let due_at = value_to_opt_string(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("queue: read sr_due_at: {e}")))?,
        );
        let last_reviewed_at = value_to_opt_string(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("queue: read sr_last_reviewed: {e}")))?,
        );

        let question_id: i64 = row
            .get::<i64>(4)
            .map_err(|e| AppError::Internal(format!("queue: read question_id: {e}")))?;
        let question_text = value_to_opt_string(
            row.get_value(5)
                .map_err(|e| AppError::Internal(format!("queue: read q_text: {e}")))?,
        );
        let option_a = value_to_opt_string(
            row.get_value(6)
                .map_err(|e| AppError::Internal(format!("queue: read option_a: {e}")))?,
        );
        let option_b = value_to_opt_string(
            row.get_value(7)
                .map_err(|e| AppError::Internal(format!("queue: read option_b: {e}")))?,
        );
        let option_c = value_to_opt_string(
            row.get_value(8)
                .map_err(|e| AppError::Internal(format!("queue: read option_c: {e}")))?,
        );
        let option_d = value_to_opt_string(
            row.get_value(9)
                .map_err(|e| AppError::Internal(format!("queue: read option_d: {e}")))?,
        );
        let correct_option = value_to_opt_string(
            row.get_value(10)
                .map_err(|e| AppError::Internal(format!("queue: read correct_option: {e}")))?,
        );
        let explanation = value_to_opt_string(
            row.get_value(11)
                .map_err(|e| AppError::Internal(format!("queue: read explanation: {e}")))?,
        );
        let difficulty = value_to_opt_string(
            row.get_value(12)
                .map_err(|e| AppError::Internal(format!("queue: read difficulty: {e}")))?,
        );
        let topic_id = value_to_opt_i64(
            row.get_value(13)
                .map_err(|e| AppError::Internal(format!("queue: read topic_id: {e}")))?,
        );
        let topic_name = value_to_opt_string(
            row.get_value(14)
                .map_err(|e| AppError::Internal(format!("queue: read topic_name: {e}")))?,
        );

        cards.push(ReviewCard {
            card_id,
            question: ReviewQuestion {
                id: question_id,
                question_text,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_option,
                explanation,
                difficulty,
                topic_id,
                topic_name,
            },
            box_num,
            due_at,
            last_reviewed_at,
        });
    }

    // due_tomorrow: cards with date(sr_due_at) = date('now', '+1 day').
    let due_tomorrow_sql = "SELECT COUNT(*) FROM error_log el \
                            JOIN questions q ON q.id = el.question_id \
                            WHERE el.user_id = ?1 \
                              AND (q.disabled IS NULL OR q.disabled = 0) \
                              AND date(el.sr_due_at) = date('now', '+1 day')";
    let due_tomorrow: i64 = match state
        .db
        .conn()
        .query(due_tomorrow_sql, params![auth.id])
        .await
    {
        Ok(mut rows) => match rows.next().await {
            Ok(Some(row)) => row.get::<i64>(0).unwrap_or(0),
            _ => 0,
        },
        Err(_) => 0,
    };

    let mut by_box_map = std::collections::BTreeMap::new();
    for (i, count) in by_box.iter().enumerate() {
        by_box_map.insert((i + 1).to_string(), *count);
    }

    Ok(Json(ReviewQueueResponse {
        summary: crate::schemas::review::ReviewQueueSummary {
            due_today,
            due_tomorrow,
            by_box: by_box_map,
        },
        cards,
    }))
}

// ---------- POST /review/answers/{card_id} --------------------------------

/// Advance one card: promote/demote via Leitner rules, stamp
/// `sr_last_reviewed`, and return the new box + due date so the FE can
/// show "next review in N days" before moving on.
///
/// Ownership: we SELECT `sr_box` filtered by `(id = ?, user_id = ?)`. A
/// mismatched user_id returns 404 (not 403) per R4 §2.7 — no enumeration
/// of other users' error_log ids.
pub async fn answer(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Path(card_id): Path<i64>,
    Json(req): Json<ReviewAnswerRequest>,
) -> Result<Json<ReviewAnswerResponse>, AppError> {
    // Load current box + verify ownership in one round-trip.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT sr_box FROM error_log WHERE id = ?1 AND user_id = ?2 LIMIT 1",
            params![card_id, auth.id],
        )
        .await?;
    let Some(row) = rows.next().await? else {
        return Err(AppError::NotFound("review card"));
    };
    let current_box = value_to_opt_i64(
        row.get_value(0)
            .map_err(|e| AppError::Internal(format!("answer: read sr_box: {e}")))?,
    )
    .unwrap_or(1);

    // Compute the new box + due date via the pure services::sr helpers.
    // `next_due` internally uses today's UTC date as the anchor.
    let new_box = sr::next_box(current_box, req.correct);
    let new_due = sr::next_due(new_box);
    let now_iso = Utc::now().to_rfc3339();

    state
        .db
        .conn()
        .execute(
            "UPDATE error_log \
             SET sr_box = ?1, sr_due_at = ?2, sr_last_reviewed = ?3 \
             WHERE id = ?4 AND user_id = ?5",
            params![new_box, new_due.clone(), now_iso, card_id, auth.id],
        )
        .await?;

    // days_until_due: parse the new_due back into a NaiveDate and diff
    // against today. Since `next_due` produces `YYYY-MM-DD` off of UTC
    // today, this is functionally `box_interval_days(new_box)` — but we
    // recompute so the field lines up with what would render on a
    // subsequent /review/queue call.
    let today = Utc::now().date_naive();
    let days_until_due = NaiveDate::parse_from_str(&new_due, "%Y-%m-%d")
        .map(|d| (d - today).num_days())
        .unwrap_or_else(|_| sr::box_interval_days(new_box));

    Ok(Json(ReviewAnswerResponse {
        box_num: new_box,
        next_due_at: new_due,
        days_until_due,
    }))
}
