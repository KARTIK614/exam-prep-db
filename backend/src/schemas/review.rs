//! Request / response DTOs for the SRS review endpoints
//! (`/api/v1/review/*`).
//!
//! Semantics preserved from `bp_review.py` (Flask) — see
//! `docs/plans/v3-R4-api-auth.md` §3.6 for the wire contract.

use serde::{Deserialize, Serialize};

// ---------- GET /review/queue ---------------------------------------------

/// One card in the review queue.
///
/// `card_id` is `error_log.id`. The client posts back to
/// `POST /review/answers/{card_id}` when the user finishes recalling it.
#[derive(Debug, Serialize)]
pub struct ReviewCard {
    pub card_id: i64,
    pub question: ReviewQuestion,
    /// Leitner box (1..=5). Serialised as `box` on the wire (renamed
    /// because `box` is a reserved keyword in Rust).
    #[serde(rename = "box")]
    pub box_num: i64,
    pub due_at: Option<String>,
    pub last_reviewed_at: Option<String>,
}

/// Minimal question projection carried on a review card.
#[derive(Debug, Serialize)]
pub struct ReviewQuestion {
    pub id: i64,
    pub question_text: Option<String>,
    pub option_a: Option<String>,
    pub option_b: Option<String>,
    pub option_c: Option<String>,
    pub option_d: Option<String>,
    pub correct_option: Option<String>,
    pub explanation: Option<String>,
    pub difficulty: Option<String>,
    pub topic_id: Option<i64>,
    pub topic_name: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
pub struct ReviewQueueQuery {
    /// Page size — clamped to 1..=100. Default 20.
    #[serde(default)]
    pub limit: Option<u32>,
}

#[derive(Debug, Serialize)]
pub struct ReviewQueueSummary {
    pub due_today: i64,
    pub due_tomorrow: i64,
    /// Card counts per Leitner box, keyed by the box number as a string
    /// ("1".."5") so it fits the FE `Record<string, number>` contract.
    pub by_box: std::collections::BTreeMap<String, i64>,
}

#[derive(Debug, Serialize)]
pub struct ReviewQueueResponse {
    pub summary: ReviewQueueSummary,
    pub cards: Vec<ReviewCard>,
}

// ---------- POST /review/answers/{card_id} --------------------------------

#[derive(Debug, Deserialize)]
pub struct ReviewAnswerRequest {
    pub correct: bool,
}

#[derive(Debug, Serialize)]
pub struct ReviewAnswerResponse {
    /// New Leitner box (1..=5). Serialised as `box` on the wire.
    #[serde(rename = "box")]
    pub box_num: i64,
    pub next_due_at: String,
    pub days_until_due: i64,
}
