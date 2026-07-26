//! `/api/v1/questions` handlers.
//!
//! Endpoints wired by `api::mod::router`:
//!   GET  /questions          — filterable, cursor-paginated list
//!   GET  /questions/{id}     — single question detail
//!
//! Filter set (per plan doc §3.3):
//!   topic_id, topic_ids (CSV), difficulty, pyq_only, pyq_year_min,
//!   pyq_year_max, pyq_exam, confidence, search (FTS5), cursor, limit.
//!
//! `disabled` is always filtered out (`disabled = 0 OR disabled IS NULL`)
//! — the admin surface (Phase 5+) will expose a separate endpoint that
//! opts back in.
//!
//! Ordering: `id ASC` — matches the cursor-pagination direction used by
//! `api::pagination`. The plan doc §5.4 lists `id DESC` for questions;
//! we deviate here so the cursor comparator is a straightforward
//! `WHERE id > ?`. Callers that need a fixed most-recent-first view can
//! reverse client-side; this endpoint is primarily a scan for
//! test-generation and search fallbacks.

use axum::extract::{Path, Query, State};
use axum::Json;
use libsql::params;

use crate::api::pagination::{clamp_limit, decode_cursor, next_cursor};
use crate::api::search::sanitize_fts_query;
use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::models::Question;
use crate::schemas::content::{QuestionListQuery, QuestionListResponse};

// ---------- helpers --------------------------------------------------------

/// Validate/whitelist a difficulty query value. Returns `Ok(None)` when
/// the caller omitted the field.
pub(crate) fn validate_difficulty(v: Option<&str>) -> Result<Option<String>, AppError> {
    match v {
        None => Ok(None),
        Some(d) => match d {
            "easy" | "medium" | "hard" => Ok(Some(d.to_string())),
            _ => Err(AppError::BadRequest(format!(
                "invalid difficulty: {d} (expected easy|medium|hard)"
            ))),
        },
    }
}

/// Same for `confidence` (Plan D column: high|medium|low).
pub(crate) fn validate_confidence(v: Option<&str>) -> Result<Option<String>, AppError> {
    match v {
        None => Ok(None),
        Some(c) => match c {
            "high" | "medium" | "low" => Ok(Some(c.to_string())),
            _ => Err(AppError::BadRequest(format!(
                "invalid confidence: {c} (expected high|medium|low)"
            ))),
        },
    }
}

/// Parse a comma-separated `1,2,3` string into a Vec<i64>. Silently
/// drops non-numeric tokens (rather than 400ing) so a stale FE with a
/// bad `topic_ids=all` value degrades gracefully.
pub(crate) fn parse_topic_ids(csv: Option<&str>) -> Vec<i64> {
    let Some(s) = csv else { return Vec::new() };
    s.split(',')
        .map(str::trim)
        .filter(|t| !t.is_empty())
        .filter_map(|t| t.parse::<i64>().ok())
        .collect()
}

/// Common filter-clause builder. Returns (`AND ...` fragment ready to
/// splice into a WHERE, plus the parameter values in bind order).
///
/// Every returned clause references the aliased `q.` table so it works
/// both for the plain `/questions` list and the FTS5 join in `/search`.
pub(crate) struct FilterFragment {
    pub sql: String,
    pub values: Vec<libsql::Value>,
}

pub(crate) fn build_filter_clauses(
    topic_id: Option<i64>,
    topic_ids: &[i64],
    difficulty: Option<&str>,
    pyq_only: Option<bool>,
    pyq_year_min: Option<i64>,
    pyq_year_max: Option<i64>,
    pyq_exam: Option<&str>,
    confidence: Option<&str>,
) -> FilterFragment {
    let mut clauses: Vec<String> = Vec::new();
    let mut vals: Vec<libsql::Value> = Vec::new();

    // Always: exclude disabled rows.
    clauses.push("(q.disabled = 0 OR q.disabled IS NULL)".into());

    if let Some(tid) = topic_id {
        clauses.push("q.topic_id = ?".into());
        vals.push(libsql::Value::Integer(tid));
    }
    if !topic_ids.is_empty() {
        // Build `q.topic_id IN (?,?,?)` with the exact placeholder count.
        let placeholders = std::iter::repeat("?")
            .take(topic_ids.len())
            .collect::<Vec<_>>()
            .join(",");
        clauses.push(format!("q.topic_id IN ({placeholders})"));
        for tid in topic_ids {
            vals.push(libsql::Value::Integer(*tid));
        }
    }
    if let Some(d) = difficulty {
        clauses.push("q.difficulty = ?".into());
        vals.push(libsql::Value::Text(d.to_string()));
    }
    if matches!(pyq_only, Some(true)) {
        // Restrict to previous-year rows: pyq_exam must be non-null and
        // non-empty.
        clauses.push("(q.pyq_exam IS NOT NULL AND q.pyq_exam <> '')".into());
    }
    if let Some(y) = pyq_year_min {
        clauses.push("COALESCE(q.pyq_year, 0) >= ?".into());
        vals.push(libsql::Value::Integer(y));
    }
    if let Some(y) = pyq_year_max {
        clauses.push("COALESCE(q.pyq_year, 0) <= ?".into());
        vals.push(libsql::Value::Integer(y));
    }
    if let Some(pe) = pyq_exam {
        clauses.push("COALESCE(q.pyq_exam, '') = ?".into());
        vals.push(libsql::Value::Text(pe.to_string()));
    }
    if let Some(c) = confidence {
        clauses.push("COALESCE(q.confidence, '') = ?".into());
        vals.push(libsql::Value::Text(c.to_string()));
    }

    FilterFragment {
        sql: clauses.join(" AND "),
        values: vals,
    }
}

// ---------- GET /questions -------------------------------------------------

/// List questions with filters + cursor pagination.
///
/// When `search` is present the handler routes through the FTS5 path
/// via `api::search::search_questions_fts`, so callers hitting
/// `/questions?search=foo` get the same ranked behaviour as `/search`
/// (minus the snippet field).
pub async fn list_questions(
    State(state): State<AppState>,
    RequireAuth(_): RequireAuth,
    Query(q): Query<QuestionListQuery>,
) -> Result<Json<QuestionListResponse>, AppError> {
    let limit = clamp_limit(q.limit);
    let after_id = decode_cursor(q.cursor.as_deref())?;

    let difficulty = validate_difficulty(q.difficulty.as_deref())?;
    let confidence = validate_confidence(q.confidence.as_deref())?;
    let topic_ids = parse_topic_ids(q.topic_ids.as_deref());

    // Optional FTS5 search short-circuit: reuse the search helper so we
    // keep a single query path per backend flavour.
    if let Some(raw) = q.search.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        let fts_q = sanitize_fts_query(raw);
        if !fts_q.is_empty() {
            let filter = build_filter_clauses(
                q.topic_id,
                &topic_ids,
                difficulty.as_deref(),
                q.pyq_only,
                q.pyq_year_min,
                q.pyq_year_max,
                q.pyq_exam.as_deref(),
                confidence.as_deref(),
            );
            let items =
                crate::api::search::fetch_matches(&state, &fts_q, &filter, after_id, limit).await?;
            let last_id = items.last().map(|hit| hit.question.id);
            let next = next_cursor(last_id, items.len(), limit);
            let items = items.into_iter().map(|hit| hit.question).collect();
            return Ok(Json(QuestionListResponse {
                items,
                next_cursor: next,
            }));
        }
    }

    // Plain filtered list — no FTS, ordered by id ASC.
    let filter = build_filter_clauses(
        q.topic_id,
        &topic_ids,
        difficulty.as_deref(),
        q.pyq_only,
        q.pyq_year_min,
        q.pyq_year_max,
        q.pyq_exam.as_deref(),
        confidence.as_deref(),
    );

    // Compose WHERE. `filter.sql` always has at least the disabled clause.
    let mut where_sql = filter.sql.clone();
    let mut values = filter.values.clone();
    if let Some(id) = after_id {
        where_sql.push_str(" AND q.id > ?");
        values.push(libsql::Value::Integer(id));
    }

    let cols = Question::COLUMNS
        .iter()
        .map(|c| format!("q.{c}"))
        .collect::<Vec<_>>()
        .join(", ");
    let sql = format!(
        "SELECT {cols} FROM questions q \
         WHERE {where_sql} \
         ORDER BY q.id ASC \
         LIMIT ?"
    );
    values.push(libsql::Value::Integer(limit as i64));

    let mut rows = state.db.conn().query(&sql, values).await?;
    let mut items = Vec::with_capacity(limit as usize);
    while let Some(row) = rows.next().await? {
        items.push(Question::from_row(&row)?);
    }

    let last_id = items.last().map(|q| q.id);
    let next = next_cursor(last_id, items.len(), limit);
    Ok(Json(QuestionListResponse {
        items,
        next_cursor: next,
    }))
}

// ---------- GET /questions/{id} -------------------------------------------

pub async fn get_question(
    State(state): State<AppState>,
    RequireAuth(_): RequireAuth,
    Path(id): Path<i64>,
) -> Result<Json<Question>, AppError> {
    let cols = Question::COLUMNS
        .iter()
        .map(|c| format!("q.{c}"))
        .collect::<Vec<_>>()
        .join(", ");
    let sql = format!(
        "SELECT {cols} FROM questions q \
         WHERE q.id = ?1 AND (q.disabled = 0 OR q.disabled IS NULL) \
         LIMIT 1"
    );
    let mut rows = state.db.conn().query(&sql, params![id]).await?;
    match rows.next().await? {
        Some(row) => Ok(Json(Question::from_row(&row)?)),
        None => Err(AppError::NotFound("question")),
    }
}
