//! Request / response DTOs for the content endpoints (topics, questions,
//! search). See `docs/plans/v3-R4-api-auth.md` §3.3.
//!
//! These types are intentionally serde-only (no `validator::Validate`) —
//! query-string parsing does its own coercion, and every field is optional
//! at the wire level. Handlers translate invalid enum strings to
//! `AppError::BadRequest`.

use serde::{Deserialize, Serialize};

use crate::models::{Question, Topic};

// ------------- PublicQuestion ---------------------------------------------
//
// F01 (V3 critic, CRITICAL): the underlying `Question` model includes
// `correct_option` and `explanation` — fields that MUST NOT reach the
// end-user before they answer, otherwise `GET /questions/{id}` becomes a
// free answer-key dump for any authenticated user.  Every user-facing
// content endpoint (`/questions`, `/questions/{id}`, `/search`) returns
// `PublicQuestion` instead. Admin endpoints keep using `Question` directly
// via `admin::questions` etc.
#[derive(Debug, Clone, Serialize)]
pub struct PublicQuestion {
    pub id: i64,
    pub topic_id: Option<i64>,
    pub question_text: Option<String>,
    pub option_a: Option<String>,
    pub option_b: Option<String>,
    pub option_c: Option<String>,
    pub option_d: Option<String>,
    pub difficulty: Option<String>,
    pub source: Option<String>,
    pub language: Option<String>,
    pub disabled: bool,
    pub updated_at: Option<String>,
    pub confidence: Option<String>,
    pub section: Option<String>,
    pub sub_topic: Option<String>,
    pub pyq_exam: Option<String>,
    pub pyq_year: Option<i64>,
    // review_notes + confidence_reviewed_at intentionally omitted — they
    // may contain internal grader remarks.
}

impl From<Question> for PublicQuestion {
    fn from(q: Question) -> Self {
        PublicQuestion {
            id: q.id,
            topic_id: q.topic_id,
            question_text: q.question_text,
            option_a: q.option_a,
            option_b: q.option_b,
            option_c: q.option_c,
            option_d: q.option_d,
            difficulty: q.difficulty,
            source: q.source,
            language: q.language,
            disabled: q.disabled,
            updated_at: q.updated_at,
            confidence: q.confidence,
            section: q.section,
            sub_topic: q.sub_topic,
            pyq_exam: q.pyq_exam,
            pyq_year: q.pyq_year,
        }
    }
}

impl From<&Question> for PublicQuestion {
    fn from(q: &Question) -> Self {
        PublicQuestion::from(q.clone())
    }
}

// ------------- Topics ------------------------------------------------------

/// Response shape for `GET /topics/{id}`.
#[derive(Debug, Serialize)]
pub struct TopicWithCount {
    #[serde(flatten)]
    pub topic: Topic,
    /// Live question count (`disabled = 0`) — recomputed on each request.
    pub question_count: i64,
}

// ------------- Questions ---------------------------------------------------

/// Query parameters for `GET /questions`.
///
/// `topic_ids` accepts either repeated `topic_ids=1&topic_ids=2` (via the
/// `Vec<i64>` deserialiser) or a comma-separated string. Rather than fight
/// axum's `serde_urlencoded` on repeated keys, we accept a single
/// comma-separated form `topic_ids=1,2,3` here; the handler splits it. This
/// keeps the schema uniform across clients that can't emit multi-valued
/// query keys.
#[derive(Debug, Default, Deserialize)]
pub struct QuestionListQuery {
    pub topic_id: Option<i64>,
    /// Comma-separated list of topic ids, e.g. `1,2,3`. Empty / absent =
    /// no topic filter.
    pub topic_ids: Option<String>,
    /// One of `easy` | `medium` | `hard`.
    pub difficulty: Option<String>,
    /// Truthy → restrict to previous-year questions (`pyq_exam IS NOT NULL`).
    pub pyq_only: Option<bool>,
    pub pyq_year_min: Option<i64>,
    pub pyq_year_max: Option<i64>,
    /// Exact PYQ exam identifier (e.g. `"UPSC-2019"`).
    pub pyq_exam: Option<String>,
    /// One of `high` | `medium` | `low`.
    pub confidence: Option<String>,
    /// Free-text search — when present the handler routes to the FTS5
    /// query path (still returns the plain `QuestionListResponse`; use
    /// `/search` for snippet + rank).
    pub search: Option<String>,
    /// Opaque cursor from a previous response's `next_cursor`.
    pub cursor: Option<String>,
    /// Page size. Default 20, hard cap 100 (enforced server-side).
    pub limit: Option<u32>,
}

#[derive(Debug, Serialize)]
pub struct QuestionListResponse {
    // F01 (V3 critic): PublicQuestion, not Question — see PublicQuestion
    // docstring above. correct_option + explanation stripped from wire.
    pub items: Vec<PublicQuestion>,
    /// Opaque cursor for the next page, or `null` at end-of-list.
    pub next_cursor: Option<String>,
}

// ------------- Search ------------------------------------------------------

/// Query parameters for `GET /search`. Superset of `QuestionListQuery`
/// with an additional required `q`.
#[derive(Debug, Default, Deserialize)]
pub struct SearchQuery {
    pub q: String,
    pub topic_id: Option<i64>,
    pub topic_ids: Option<String>,
    pub difficulty: Option<String>,
    pub pyq_only: Option<bool>,
    pub pyq_year_min: Option<i64>,
    pub pyq_year_max: Option<i64>,
    pub pyq_exam: Option<String>,
    pub confidence: Option<String>,
    pub cursor: Option<String>,
    pub limit: Option<u32>,
}

/// One row of `/search` results — question payload (public) plus the
/// FTS5 snippet and bm25 rank. `rank` is `null` on the LIKE fallback path.
///
/// F01 (V3 critic): `question` was `Question` (leaked correct_option +
/// explanation). Now `PublicQuestion`.
#[derive(Debug, Serialize)]
pub struct SearchHit {
    #[serde(flatten)]
    pub question: PublicQuestion,
    pub snippet: String,
    pub rank: Option<f64>,
}

#[derive(Debug, Serialize)]
pub struct SearchResponse {
    pub items: Vec<SearchHit>,
    pub next_cursor: Option<String>,
    /// `"fts5"` when the FTS5 virtual table was used, `"like"` on the
    /// fallback path. Callers can surface this for debugging or feature
    /// gating.
    pub backend: &'static str,
}
