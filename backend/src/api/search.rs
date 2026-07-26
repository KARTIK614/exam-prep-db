//! `/api/v1/search` handler + FTS5 helpers.
//!
//! Endpoint (per plan doc §3.3):
//!   GET /search?q=...&topic_id=...&...&cursor=...&limit=...
//!
//! Behaviour summary:
//!   1. Sanitize the raw query (see `sanitize_fts_query`): drop FTS5
//!      operators, quote each token, append `*` to the last one so
//!      partial typeahead-style matches work.
//!   2. Try the FTS5 virtual table (`questions_fts MATCH ?`) with the
//!      full filter set + snippet + bm25 rank + `LIMIT` cursor.
//!   3. On any FTS5 failure (table missing, syntax error, degraded
//!      libSQL build) fall back to a `LIKE '%q%'` scan over
//!      question_text / options / explanation.
//!
//! FTS5 quirks worth documenting for future readers:
//!   * `bm25()` returns SMALLER numbers for BETTER matches. Ordering
//!     is naturally ASC — we surface the raw value in `rank`.
//!   * Cursor-based pagination is done by `bm25` -> we can't do "id >
//!     ?" because ranking isn't monotonic in id. Instead we use OFFSET
//!     under the hood, where the "cursor" is the offset count.
//!     Kept opaque so we can revisit.
//!   * The FTS content columns are (question_text, option_a..d,
//!     explanation) — see `db.py::FTS5_DDL`. `snippet(fts, 0, ...)`
//!     targets column 0 (question_text) which is the primary field
//!     users search.
//!   * Turso's remote libSQL currently ships FTS5 on new databases;
//!     older Turso instances may not have `questions_fts` yet. The
//!     `_fts5_available` probe uses `sqlite_master` and matches the
//!     Flask probe.

use axum::extract::{Query, State};
use axum::Json;

use crate::api::pagination::{clamp_limit, next_cursor};
use crate::api::questions::{
    build_filter_clauses, parse_topic_ids, validate_confidence, validate_difficulty,
    FilterFragment,
};
use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::models::Question;
use crate::schemas::content::{SearchHit, SearchQuery, SearchResponse};

// ---------- query sanitiser ------------------------------------------------

/// Turn a raw user query into an FTS5 `MATCH` expression.
///
/// Rules (mirror `bp_main.py::_sanitize_fts_query`):
///   * Split on non-alphanumeric characters — anything else is treated
///     as a separator.
///   * Wrap each surviving token in double-quotes so operator-like
///     characters inside a token (rare after the strip, but possible)
///     are treated as literal text.
///   * Append `*` to the *last* token only, giving prefix-match
///     behaviour for the partial word the user is still typing.
///
/// Returns an empty string when no usable tokens remain — callers
/// short-circuit to "no results" without hitting the DB.
pub fn sanitize_fts_query(raw: &str) -> String {
    let mut tokens: Vec<String> = Vec::new();
    let mut current = String::new();
    for ch in raw.chars() {
        if ch.is_ascii_alphanumeric() {
            current.push(ch);
        } else if !current.is_empty() {
            tokens.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        tokens.push(current);
    }
    if tokens.is_empty() {
        return String::new();
    }
    let last_idx = tokens.len() - 1;
    tokens
        .iter()
        .enumerate()
        .map(|(i, tok)| {
            if i == last_idx {
                format!("\"{tok}\"*")
            } else {
                format!("\"{tok}\"")
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

// ---------- fts5 availability probe ---------------------------------------

/// Cheap probe: does the `questions_fts` virtual table exist? Mirrors
/// the Flask probe in `bp_main.py`. We swallow errors on the assumption
/// that "sqlite_master unavailable" also means "no FTS5".
async fn fts5_available(state: &AppState) -> bool {
    let sql = "SELECT name FROM sqlite_master \
               WHERE type IN ('table','view') AND name = 'questions_fts' \
               LIMIT 1";
    match state.db.conn().query(sql, ()).await {
        Ok(mut rows) => rows.next().await.ok().flatten().is_some(),
        Err(_) => false,
    }
}

// ---------- shared FTS5 fetch (used by /search and /questions?search=) ----

/// Run the FTS5 query with the given `MATCH` expression and filter clauses.
///
/// Cursor is treated as an OFFSET (see the module-doc quirk on why
/// id-based cursors don't work with bm25 ordering). `after_id` is
/// interpreted as "skip this many prior rows" — callers get an opaque
/// cursor either way.
pub async fn fetch_matches(
    state: &AppState,
    fts_expr: &str,
    filter: &FilterFragment,
    after_id: Option<i64>,
    limit: u32,
) -> Result<Vec<SearchHit>, AppError> {
    let cols = Question::COLUMNS
        .iter()
        .map(|c| format!("q.{c}"))
        .collect::<Vec<_>>()
        .join(", ");

    let sql = format!(
        "SELECT {cols}, \
                snippet(questions_fts, 0, '<mark>', '</mark>', ' … ', 12) AS snippet, \
                bm25(questions_fts) AS rank \
         FROM questions_fts \
         JOIN questions q ON q.id = questions_fts.rowid \
         WHERE questions_fts MATCH ? AND {} \
         ORDER BY rank ASC \
         LIMIT ? OFFSET ?",
        filter.sql
    );

    let mut values: Vec<libsql::Value> = Vec::with_capacity(filter.values.len() + 3);
    values.push(libsql::Value::Text(fts_expr.to_string()));
    values.extend(filter.values.iter().cloned());
    values.push(libsql::Value::Integer(limit as i64));
    values.push(libsql::Value::Integer(after_id.unwrap_or(0)));

    let mut rows = state.db.conn().query(&sql, values).await?;
    let mut out: Vec<SearchHit> = Vec::with_capacity(limit as usize);
    while let Some(row) = rows.next().await? {
        // Question::from_row indexes 0..COLUMNS.len(); snippet + rank
        // are the two trailing columns.
        let question = Question::from_row(&row)?;
        let snippet_idx = Question::COLUMNS.len();
        let rank_idx = snippet_idx + 1;
        let snippet = match row.get_value(snippet_idx as i32) {
            Ok(libsql::Value::Text(s)) => s,
            _ => String::new(),
        };
        let rank = match row.get_value(rank_idx as i32) {
            Ok(libsql::Value::Real(f)) => Some(f),
            Ok(libsql::Value::Integer(i)) => Some(i as f64),
            _ => None,
        };
        // F01 (V3 critic): strip correct_option + explanation before wire.
        out.push(SearchHit {
            question: crate::schemas::content::PublicQuestion::from(question),
            snippet,
            rank,
        });
    }
    Ok(out)
}

// ---------- LIKE fallback --------------------------------------------------

/// Naive LIKE-based fallback used when FTS5 is unavailable. Case-
/// insensitive `%q%` scan across question_text + options + explanation.
/// Snippet is a cheap window around the first occurrence in
/// question_text; rank is always `None`.
async fn fetch_like_fallback(
    state: &AppState,
    raw_q: &str,
    filter: &FilterFragment,
    after_id: Option<i64>,
    limit: u32,
) -> Result<Vec<SearchHit>, AppError> {
    let like = format!("%{}%", raw_q);

    let cols = Question::COLUMNS
        .iter()
        .map(|c| format!("q.{c}"))
        .collect::<Vec<_>>()
        .join(", ");

    let sql = format!(
        "SELECT {cols} FROM questions q \
         WHERE ( \
             q.question_text LIKE ? OR \
             q.option_a LIKE ? OR q.option_b LIKE ? OR \
             q.option_c LIKE ? OR q.option_d LIKE ? OR \
             COALESCE(q.explanation, '') LIKE ? \
         ) AND {} AND q.id > ? \
         ORDER BY q.id ASC \
         LIMIT ?",
        filter.sql
    );

    let mut values: Vec<libsql::Value> = Vec::with_capacity(filter.values.len() + 8);
    // 6 LIKE placeholders
    for _ in 0..6 {
        values.push(libsql::Value::Text(like.clone()));
    }
    values.extend(filter.values.iter().cloned());
    values.push(libsql::Value::Integer(after_id.unwrap_or(0)));
    values.push(libsql::Value::Integer(limit as i64));

    let mut rows = state.db.conn().query(&sql, values).await?;
    let mut out: Vec<SearchHit> = Vec::with_capacity(limit as usize);
    while let Some(row) = rows.next().await? {
        let question = Question::from_row(&row)?;
        let snippet = compute_like_snippet(question.question_text.as_deref(), raw_q);
        // F01 (V3 critic): PublicQuestion strips correct_option + explanation.
        out.push(SearchHit {
            question: crate::schemas::content::PublicQuestion::from(question),
            snippet,
            rank: None,
        });
    }
    Ok(out)
}

/// Produce a small window around the first case-insensitive occurrence
/// of `needle` in `text`, wrapping the match in `<mark>` tags. Falls
/// back to the leading 220 chars if the needle isn't present in the
/// primary field.
///
/// Uses ASCII-only case folding (`to_ascii_lowercase`) so byte offsets
/// stay in sync with the original string — safe with mixed Devanagari
/// + Latin content because case folding is a no-op for non-ASCII code
/// points. This means a needle typed in ALL-CAPS Hindi won't match
/// lowercase Hindi text, but the app's search UI enters exactly what
/// the user typed and Devanagari has no case, so it's a non-issue in
/// practice.
fn compute_like_snippet(text: Option<&str>, needle: &str) -> String {
    let Some(text) = text else {
        return String::new();
    };
    let lower_text = text.to_ascii_lowercase();
    let lower_needle = needle.to_ascii_lowercase();
    if let Some(pos) = lower_text.find(&lower_needle) {
        // `find` returns byte offsets. Snap to char boundaries before
        // slicing to avoid a panic mid-codepoint.
        let match_end = pos + needle.len();

        // Walk backwards from `pos` to find a boundary at ~40 bytes back.
        let start_target = pos.saturating_sub(40);
        let start = (0..=start_target)
            .rev()
            .find(|i| text.is_char_boundary(*i))
            .unwrap_or(0);

        // Walk forwards from `match_end` to a boundary at ~120 bytes on.
        let end_target = (match_end + 120).min(text.len());
        let end = (end_target..=text.len())
            .find(|i| text.is_char_boundary(*i))
            .unwrap_or(text.len());

        let mut buf = String::new();
        if start > 0 {
            buf.push_str("… ");
        }
        buf.push_str(&text[start..pos]);
        buf.push_str("<mark>");
        buf.push_str(&text[pos..match_end]);
        buf.push_str("</mark>");
        buf.push_str(&text[match_end..end]);
        if end < text.len() {
            buf.push_str(" …");
        }
        buf
    } else {
        let cap = text
            .char_indices()
            .nth(220)
            .map(|(i, _)| i)
            .unwrap_or(text.len());
        text[..cap].to_string()
    }
}

// ---------- GET /search ----------------------------------------------------

pub async fn search(
    State(state): State<AppState>,
    RequireAuth(_): RequireAuth,
    Query(q): Query<SearchQuery>,
) -> Result<Json<SearchResponse>, AppError> {
    let raw_q = q.q.trim().to_string();
    if raw_q.is_empty() {
        return Err(AppError::BadRequest("q is required".into()));
    }

    let limit = clamp_limit(q.limit);
    // Reuse the id-based cursor decoder — its raw i64 is interpreted as
    // an OFFSET in the FTS5 path (see quirk in the module doc).
    let cursor_value = crate::api::pagination::decode_cursor(q.cursor.as_deref())?;

    let difficulty = validate_difficulty(q.difficulty.as_deref())?;
    let confidence = validate_confidence(q.confidence.as_deref())?;
    let topic_ids = parse_topic_ids(q.topic_ids.as_deref());

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

    // First-pass: FTS5 if available.
    if fts5_available(&state).await {
        let expr = sanitize_fts_query(&raw_q);
        if expr.is_empty() {
            return Ok(Json(SearchResponse {
                items: Vec::new(),
                next_cursor: None,
                backend: "fts5",
            }));
        }
        match fetch_matches(&state, &expr, &filter, cursor_value, limit).await {
            Ok(items) => {
                // Cursor = next OFFSET (previous offset + rows returned)
                // when we filled the page.
                let next = if items.len() as u32 == limit {
                    let next_offset = cursor_value.unwrap_or(0) + items.len() as i64;
                    Some(crate::api::pagination::encode_cursor(next_offset))
                } else {
                    None
                };
                return Ok(Json(SearchResponse {
                    items,
                    next_cursor: next,
                    backend: "fts5",
                }));
            }
            Err(err) => {
                tracing::warn!(error = %err, "FTS5 search failed — falling back to LIKE");
                // fall through to LIKE
            }
        }
    }

    // Fallback path — id-based cursor semantics apply here.
    let items = fetch_like_fallback(&state, &raw_q, &filter, cursor_value, limit).await?;
    let last_id = items.last().map(|hit| hit.question.id);
    let next = next_cursor(last_id, items.len(), limit);
    Ok(Json(SearchResponse {
        items,
        next_cursor: next,
        backend: "like",
    }))
}
