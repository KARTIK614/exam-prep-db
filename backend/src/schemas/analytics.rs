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
    pub topic_name: Option<String>,
    pub subject: Option<String>,
    pub paper: Option<String>,
    pub weightage: i64,
    pub current_score: Option<f64>,
    pub tier: &'static str,
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
    pub attempts: i64,
    pub correct: i64,
    pub accuracy_pct: f64,
}

/// One row in the heatmap = one topic × N buckets.
///
/// For `dim=difficulty` bucket keys are `easy | medium | hard`.
/// For `dim=recency`    bucket keys are `last_7d | last_30d | older`.
#[derive(Debug, Serialize)]
pub struct HeatmapRow {
    pub topic_id: i64,
    pub topic_name: Option<String>,
    pub weightage: i64,
    pub cells: std::collections::BTreeMap<String, Option<HeatmapCell>>,
}

#[derive(Debug, Serialize)]
pub struct HeatmapResponse {
    /// Echoed back so the FE can tell which dim it received (a stale FE
    /// hitting the endpoint without `dim` gets the `difficulty` default).
    pub dim: String,
    /// Ordered list of the bucket keys present on every row (in display
    /// order). Callers can iterate this rather than sniffing map keys.
    pub buckets: Vec<String>,
    pub rows: Vec<HeatmapRow>,
}

// ---------- GET /analytics/consistency ------------------------------------

/// Mirrors `_consistency` in `bp_main.py` but exposes the raw fields
/// instead of the pre-rendered activity dict. Active day = a completed
/// `mock_test` OR a `study_session` with `duration_min >= 10`.
#[derive(Debug, Serialize)]
pub struct ConsistencyResponse {
    /// 0..100. `min(100, round(active_days_28 * (100 / denominator)))`.
    pub score_pct: i64,
    /// Number of unique dates in the last 28 days with any qualifying
    /// activity.
    pub active_days_28: i64,
    /// Fixed at 20 — 5 study days/week hits 100 %.
    pub denominator: i64,
    /// Longest tail of consecutive active days ending "today". `0` if
    /// today itself is inactive.
    pub streak_days: i64,
    /// 28-length array of booleans, one per date in the window. Index 0
    /// = 27 days ago, index 27 = today.
    pub activity_strip: Vec<bool>,
}

// ---------- GET /analytics/next-weak-topic --------------------------------

/// One entry in the next-weak-topic recommendation list.
#[derive(Debug, Serialize)]
pub struct NextTopicEntry {
    pub topic_id: i64,
    pub name: Option<String>,
    pub weightage: i64,
    /// Human-readable "why this topic" string (matches `_score_topic`'s
    /// `reason` field in `bp_main.py`).
    pub reason_str: String,
    /// Rough "exam points if you master this" estimate. For untested
    /// topics this is `weightage` (full weightage on the table); for
    /// scored topics it's `(gap / 100) * weightage` rounded to 1 dp.
    pub exam_points_at_stake: f64,
}

#[derive(Debug, Serialize)]
pub struct NextWeakTopicResponse {
    /// Highest-scoring topic. `None` when every topic is already at or
    /// above target and studied recently.
    pub top_topic: Option<NextTopicEntry>,
    /// Up to 2 more entries after `top_topic`, ranked by score DESC.
    pub alternatives: Vec<NextTopicEntry>,
}

// ---------- GET /analytics/pacing -----------------------------------------

/// Per-test pacing row for the trend chart.
#[derive(Debug, Serialize)]
pub struct PacingTestRow {
    pub test_id: i64,
    pub avg_sec_per_q: f64,
}

/// One difficulty bucket in the pacing block.
#[derive(Debug, Serialize)]
pub struct PacingByDifficulty {
    /// `target_sec_per_q`, same across buckets today (kept per-bucket so
    /// future per-difficulty targets can slot in without a wire break).
    pub target: i64,
    /// Mean seconds/question actually observed in this bucket.
    pub actual: f64,
}

#[derive(Debug, Serialize)]
pub struct PacingByDifficultyMap {
    pub easy: PacingByDifficulty,
    pub medium: PacingByDifficulty,
    pub hard: PacingByDifficulty,
}

/// One "slow and wrong" row — questions where the user spent more than
/// 2× the target and still got it wrong.
#[derive(Debug, Serialize)]
pub struct SlowAndWrongRow {
    pub question_id: i64,
    pub topic_name: Option<String>,
    pub question_text: Option<String>,
    pub time_spent: f64,
    pub difficulty: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct PacingResponse {
    pub tests: Vec<PacingTestRow>,
    /// Target seconds per question. Sourced from `settings.target_seconds_per_q`
    /// (default 72). Settings are global today (per R2 §9); v4 will
    /// namespace per-user.
    pub target_sec_per_q: i64,
    /// 5-test trailing moving average of `avg_sec_per_q`. Same length as
    /// `tests`. `None` at any index where the window is empty (only
    /// possible when there are zero tests). Matches the Flask
    /// `bp_analytics.py::dashboard` `ma_pace` computation, which always
    /// emits a value when the window has at least one observation.
    pub moving_avg_5: Vec<Option<f64>>,
    pub by_difficulty: PacingByDifficultyMap,
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
