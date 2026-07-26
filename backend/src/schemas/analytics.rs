//! Request / response DTOs for the analytics endpoints
//! (`/api/v1/analytics/*`).
//!
//! Semantics preserved from the Flask blueprints `bp_analytics.py` and
//! `bp_main.py` (the mastery-tile + next-topic + consistency helpers
//! live in `bp_main.py`, the heatmaps + pacing in `bp_analytics.py`).
//! See `docs/plans/v3-R4-api-auth.md` §3.9 for the wire contract.

use serde::Serialize;

// ---------- GET /analytics/mastery ----------------------------------------

/// One tile in the mastery grid.
///
/// `tier` classification (matches `_mastery_tiles` in `bp_main.py`):
///   * `untested` — no attempts recorded
///   * `weak`     — `current_score < 60`
///   * `on_track` — `60 <= current_score < 80` (weak_threshold..target)
///   * `mastered` — `current_score >= 80`
#[derive(Debug, Serialize)]
pub struct MasteryTile {
    pub topic_id: i64,
    #[serde(rename = "name")]
    pub topic_name: Option<String>,
    pub subject: Option<String>,
    pub paper: Option<String>,
    pub weightage: i64,
    pub current_score: f64,
    pub tier: &'static str,
    #[serde(rename = "days_since")]
    pub days_since_studied: Option<i64>,
    pub test_count: i64,
}

#[derive(Debug, Serialize)]
pub struct MasteryResponse {
    pub tiles: Vec<MasteryTile>,
}

// ---------- GET /analytics/heatmap ----------------------------------------

/// One cell in the heatmap grid. `None` cell = no attempts in that bucket.
#[derive(Debug, Serialize, Clone)]
pub struct HeatmapCell {
    #[serde(rename = "attempted")]
    pub attempts: i64,
    pub correct: i64,
    #[serde(rename = "accuracy")]
    pub accuracy_pct: f64,
}

/// One row in the heatmap = one topic × N buckets.
///
/// For `dim=difficulty` bucket keys are `easy | medium | hard`.
/// For `dim=recency`    bucket keys are `last_7d | last_30d | older`.
#[derive(Debug, Serialize)]
pub struct HeatmapRow {
    pub topic_id: i64,
    #[serde(rename = "name")]
    pub topic_name: Option<String>,
    pub weightage: i64,
    pub cells: std::collections::BTreeMap<String, Option<HeatmapCell>>,
}

#[derive(Debug, Serialize)]
pub struct HeatmapResponse {
    pub dim: String,
    pub buckets: Vec<String>,
    #[serde(rename = "topics")]
    pub rows: Vec<HeatmapRow>,
}

// ---------- GET /analytics/consistency ------------------------------------

/// Mirrors `_consistency` in `bp_main.py` but exposes the raw fields
/// instead of the pre-rendered activity dict. Active day = a completed
/// `mock_test` OR a `study_session` with `duration_min >= 10`.
#[derive(Debug, Serialize)]
pub struct ActivityCell {
    pub date: String,
    pub has_activity: bool,
}

#[derive(Debug, Serialize)]
pub struct ConsistencyResponse {
    #[serde(rename = "score")]
    pub score_pct: i64,
    #[serde(rename = "active_days")]
    pub active_days_28: i64,
    pub denominator: i64,
    pub streak_days: i64,
    pub activity: Vec<ActivityCell>,
}

// ---------- GET /analytics/next-weak-topic --------------------------------

/// One entry in the next-weak-topic recommendation list.
#[derive(Debug, Serialize)]
pub struct NextTopicEntry {
    pub topic_id: i64,
    pub name: Option<String>,
    pub weightage: i64,
    #[serde(rename = "reason")]
    pub reason_str: String,
    pub exam_points_at_stake: f64,
    pub next_score: Option<f64>,
}

#[derive(Debug, Serialize)]
pub struct NextWeakTopicResponse {
    pub next_topics: Vec<NextTopicEntry>,
}

// ---------- GET /analytics/pacing -----------------------------------------

/// Per-test pacing row for the trend chart. `paper`, `score`, `date` are
/// carried through so the FE hover tooltip can render context without a
/// second round-trip.
#[derive(Debug, Serialize)]
pub struct PacingTestRow {
    pub test_id: i64,
    #[serde(rename = "avg_time")]
    pub avg_sec_per_q: f64,
    pub paper: Option<String>,
    pub score: Option<f64>,
    pub date: Option<String>,
}

/// One row in the FE's pace-by-difficulty array. Shape chosen to match
/// the FE type: `{difficulty, avg_time, n}`.
#[derive(Debug, Serialize)]
pub struct PacingByDifficultyEntry {
    pub difficulty: String,
    pub avg_time: f64,
    pub n: i64,
}

/// One "slow and wrong" row — questions where the user spent more than
/// 2× the target and still got it wrong.
#[derive(Debug, Serialize)]
pub struct SlowAndWrongRow {
    pub question_id: i64,
    #[serde(rename = "topic")]
    pub topic_name: Option<String>,
    pub question_text: Option<String>,
    #[serde(rename = "time_spent_sec")]
    pub time_spent: f64,
    pub difficulty: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct PacingResponse {
    #[serde(rename = "time_trend")]
    pub tests: Vec<PacingTestRow>,
    #[serde(rename = "target_sec")]
    pub target_sec_per_q: i64,
    #[serde(rename = "ma_pace")]
    pub moving_avg_5: Vec<Option<f64>>,
    #[serde(rename = "pace_by_difficulty")]
    pub by_difficulty: Vec<PacingByDifficultyEntry>,
    #[serde(rename = "slow_wrong")]
    pub slow_and_wrong: Vec<SlowAndWrongRow>,
}

// ---------- GET /analytics/error-dist -------------------------------------

#[derive(Debug, Serialize)]
pub struct ErrorByTopic {
    pub topic_name: Option<String>,
    pub error_count: i64,
}

#[derive(Debug, Serialize)]
pub struct ErrorByType {
    pub error_type: Option<String>,
    pub count: i64,
}

#[derive(Debug, Serialize)]
pub struct ErrorDistResponse {
    pub by_topic: Vec<ErrorByTopic>,
    pub by_type: Vec<ErrorByType>,
}

// ---------- Query params --------------------------------------------------

#[derive(Debug, Default, serde::Deserialize)]
pub struct HeatmapQuery {
    /// `difficulty` (default) or `recency`.
    #[serde(default)]
    pub dim: Option<String>,
}
