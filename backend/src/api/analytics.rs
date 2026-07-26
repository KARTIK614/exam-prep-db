//! `/api/v1/analytics/*` — dashboard analytics API surface.
//!
//! Endpoints (all require `RequireAuth`, all scope by user_id):
//!
//!   GET /analytics/mastery         — 18-tile mastery grid
//!   GET /analytics/heatmap         — topic × difficulty | recency grid
//!   GET /analytics/consistency     — 28-day activity strip + score
//!   GET /analytics/next-weak-topic — ranked next topic + 2 alternatives
//!   GET /analytics/pacing          — pacing dashboard
//!   GET /analytics/error-dist      — error distribution (by topic + type)
//!
//! Semantics ported from the Flask blueprints:
//!   * `bp_main.py::_mastery_tiles`  → `/mastery`
//!   * `bp_main.py::_rank_next_topic` → `/next-weak-topic`
//!   * `bp_main.py::_consistency`    → `/consistency`
//!   * `bp_analytics.py::_heatmap_by_difficulty` + `_heatmap_by_recency`
//!                                   → `/heatmap`
//!   * `bp_analytics.py::dashboard`  → `/pacing` (ma_pace + slow_wrong)
//!   * `bp_main.py::index`           → `/error-dist`
//!
//! User-scoping notes:
//!   * `topic_mastery`, `test_responses`, `mock_tests`, `error_log`,
//!     `study_sessions` all carry `user_id` after the v3 migration
//!     (see `scripts/migrate_v3_add_user_id.py`).
//!   * `topics` and `questions` are global — no user filter on them.
//!   * `settings` is still global today (R2 §9 notes multi-tenancy is
//!     deferred). We treat `target_seconds_per_q` as a shared read.

use std::collections::{BTreeMap, HashMap, HashSet};

use axum::extract::{Query, State};
use axum::Json;
use chrono::{Duration, NaiveDate, Utc};
use libsql::params;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::models::{value_to_opt_f64, value_to_opt_i64, value_to_opt_string};
use crate::schemas::analytics::{
    ConsistencyResponse, ErrorByTopic, ErrorByType, ErrorDistResponse, HeatmapCell,
    HeatmapQuery, HeatmapResponse, HeatmapRow, MasteryResponse, MasteryTile,
    NextTopicEntry, NextWeakTopicResponse, PacingByDifficulty, PacingByDifficultyMap,
    PacingResponse, PacingTestRow, SlowAndWrongRow,
};

// ---------- shared helpers ------------------------------------------------

/// Read a single settings row, returning the parsed integer value or the
/// supplied default. `settings` is global today (see module doc).
async fn settings_int(state: &AppState, key: &str, default: i64) -> i64 {
    let sql = "SELECT value FROM settings WHERE key = ?1 LIMIT 1";
    let mut rows = match state.db.conn().query(sql, params![key.to_string()]).await {
        Ok(r) => r,
        Err(_) => return default,
    };
    let Some(row) = rows.next().await.ok().flatten() else {
        return default;
    };
    let raw = match row.get_value(0) {
        Ok(v) => value_to_opt_string(v),
        Err(_) => None,
    };
    raw.and_then(|s| s.trim().parse::<f64>().ok())
        .map(|f| f as i64)
        .unwrap_or(default)
}

/// Round to 1 decimal place (mirrors Flask `round(x, 1)`).
fn round1(x: f64) -> f64 {
    (x * 10.0).round() / 10.0
}

/// Parse an ISO timestamp head (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS...`)
/// into a NaiveDate. Returns `None` on any parse failure.
fn parse_iso_date_head(s: &str) -> Option<NaiveDate> {
    let head = &s[..s.len().min(10)];
    NaiveDate::parse_from_str(head, "%Y-%m-%d").ok()
}

// ================================================================
// GET /analytics/mastery
// ================================================================

/// Full mastery grid for the calling user.
///
/// Weak <60, on_track 60..80, mastered ≥80, untested (no attempts).
/// Sorted by (tier priority, weightage DESC, name) — weak/high-value
/// tiles float to the top just like the Flask dashboard.
pub async fn mastery(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
) -> Result<Json<MasteryResponse>, AppError> {
    // Fixed thresholds per spec: 60 / 80.
    let weak_threshold: f64 = 60.0;
    let mastered_threshold: f64 = 80.0;

    // LEFT JOIN so untested topics still appear on the grid.
    let sql = "SELECT t.id, t.name, t.subject, t.paper, \
                      COALESCE(t.weightage, 5) AS weightage, \
                      tm.current_score, tm.last_studied, \
                      COALESCE(tm.test_count, 0) AS test_count \
               FROM topics t \
               LEFT JOIN topic_mastery tm \
                      ON tm.topic_id = t.id AND tm.user_id = ?1 \
               ORDER BY t.paper, t.name";
    let mut rows = state.db.conn().query(sql, params![auth.id]).await?;

    let today = Utc::now().date_naive();
    let mut tiles: Vec<MasteryTile> = Vec::new();
    while let Some(row) = rows.next().await? {
        let topic_id: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("mastery: read topic_id: {e}")))?;
        let topic_name = value_to_opt_string(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("mastery: read name: {e}")))?,
        );
        let subject = value_to_opt_string(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("mastery: read subject: {e}")))?,
        );
        let paper = value_to_opt_string(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("mastery: read paper: {e}")))?,
        );
        let weightage = value_to_opt_i64(
            row.get_value(4)
                .map_err(|e| AppError::Internal(format!("mastery: read weightage: {e}")))?,
        )
        .unwrap_or(5);
        let current_score = value_to_opt_f64(
            row.get_value(5)
                .map_err(|e| AppError::Internal(format!("mastery: read current_score: {e}")))?,
        );
        let last_studied = value_to_opt_string(
            row.get_value(6)
                .map_err(|e| AppError::Internal(format!("mastery: read last_studied: {e}")))?,
        );
        let test_count = value_to_opt_i64(
            row.get_value(7)
                .map_err(|e| AppError::Internal(format!("mastery: read test_count: {e}")))?,
        )
        .unwrap_or(0);

        let days_since_studied = last_studied
            .as_deref()
            .and_then(parse_iso_date_head)
            .map(|d| (today - d).num_days());

        let tier: &'static str = if test_count == 0 || current_score.is_none() {
            "untested"
        } else {
            let cur = current_score.unwrap_or(0.0);
            if cur < weak_threshold {
                "weak"
            } else if cur < mastered_threshold {
                "on_track"
            } else {
                "mastered"
            }
        };

        tiles.push(MasteryTile {
            topic_id,
            topic_name,
            subject,
            paper,
            weightage,
            current_score,
            tier,
            days_since_studied,
            test_count,
        });
    }

    // Sort: weak(0) → on_track(1) → untested(2) → mastered(3), then
    // weightage DESC, then name ASC.
    let tier_priority = |t: &str| -> i32 {
        match t {
            "weak" => 0,
            "on_track" => 1,
            "untested" => 2,
            "mastered" => 3,
            _ => 9,
        }
    };
    tiles.sort_by(|a, b| {
        tier_priority(a.tier)
            .cmp(&tier_priority(b.tier))
            .then_with(|| b.weightage.cmp(&a.weightage))
            .then_with(|| a.topic_name.cmp(&b.topic_name))
    });

    Ok(Json(MasteryResponse { tiles }))
}

// ================================================================
// GET /analytics/heatmap
// ================================================================

/// Topic × difficulty (default) or Topic × recency heatmap. Only counts
/// the caller's own test_responses.
pub async fn heatmap(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Query(q): Query<HeatmapQuery>,
) -> Result<Json<HeatmapResponse>, AppError> {
    // Empty-string `?dim=` (rather than missing) should degrade to the
    // difficulty default, so filter blanks out before we branch.
    let dim = q
        .dim
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("difficulty");
    match dim {
        "difficulty" => heatmap_by_difficulty(&state, auth.id).await,
        "recency" => heatmap_by_recency(&state, auth.id).await,
        _ => Err(AppError::BadRequest(format!(
            "invalid dim: {dim} (expected difficulty|recency)"
        ))),
    }
}

async fn heatmap_by_difficulty(
    state: &AppState,
    user_id: i64,
) -> Result<Json<HeatmapResponse>, AppError> {
    // JOIN questions/topics — filter disabled + user_id on responses.
    let sql = "SELECT t.id, t.name, COALESCE(t.weightage, 5) AS weightage, \
                      COALESCE(q.difficulty, 'medium') AS difficulty, \
                      COUNT(*) AS attempts, \
                      SUM(CASE WHEN tr.is_correct = 1 THEN 1 ELSE 0 END) AS correct \
               FROM test_responses tr \
               JOIN questions q ON tr.question_id = q.id \
               JOIN topics t ON q.topic_id = t.id \
               WHERE tr.user_id = ?1 \
                 AND (q.disabled IS NULL OR q.disabled = 0) \
               GROUP BY t.id, difficulty";
    let mut rows = state.db.conn().query(sql, params![user_id]).await?;

    let buckets: Vec<String> = vec!["easy".into(), "medium".into(), "hard".into()];
    let mut by_topic: HashMap<i64, HeatmapRow> = HashMap::new();

    while let Some(row) = rows.next().await? {
        let topic_id: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("heatmap-diff: read topic_id: {e}")))?;
        let name = value_to_opt_string(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("heatmap-diff: read name: {e}")))?,
        );
        let weightage = value_to_opt_i64(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("heatmap-diff: read weightage: {e}")))?,
        )
        .unwrap_or(5);
        let difficulty = value_to_opt_string(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("heatmap-diff: read difficulty: {e}")))?,
        )
        .unwrap_or_else(|| "medium".to_string());
        let attempts = value_to_opt_i64(
            row.get_value(4)
                .map_err(|e| AppError::Internal(format!("heatmap-diff: read attempts: {e}")))?,
        )
        .unwrap_or(0);
        let correct = value_to_opt_i64(
            row.get_value(5)
                .map_err(|e| AppError::Internal(format!("heatmap-diff: read correct: {e}")))?,
        )
        .unwrap_or(0);

        let entry = by_topic
            .entry(topic_id)
            .or_insert_with(|| new_row(topic_id, name.clone(), weightage, &buckets));
        // Fill in the cell for this difficulty bucket.
        if buckets.contains(&difficulty) {
            let acc = if attempts > 0 {
                round1((correct as f64 / attempts as f64) * 100.0)
            } else {
                0.0
            };
            entry.cells.insert(
                difficulty,
                Some(HeatmapCell {
                    attempts,
                    correct,
                    accuracy_pct: acc,
                }),
            );
        }
    }

    Ok(Json(HeatmapResponse {
        dim: "difficulty".into(),
        buckets,
        rows: sort_heatmap_rows(by_topic.into_values().collect()),
    }))
}

async fn heatmap_by_recency(
    state: &AppState,
    user_id: i64,
) -> Result<Json<HeatmapResponse>, AppError> {
    // Recency = days since the test's `completed_at`. Bucketed 0..7,
    // 8..30, older. Matches the intent of `_heatmap_by_recency` in
    // `bp_analytics.py` but collapses to a 3-bucket layout per spec.
    let sql = "SELECT t.id, t.name, COALESCE(t.weightage, 5) AS weightage, \
                      CASE \
                        WHEN julianday('now') - julianday(mt.completed_at) <= 7  THEN 'last_7d' \
                        WHEN julianday('now') - julianday(mt.completed_at) <= 30 THEN 'last_30d' \
                        ELSE 'older' \
                      END AS bucket, \
                      COUNT(*) AS attempts, \
                      SUM(CASE WHEN tr.is_correct = 1 THEN 1 ELSE 0 END) AS correct \
               FROM test_responses tr \
               JOIN mock_tests mt ON tr.test_id = mt.id \
               JOIN questions q  ON tr.question_id = q.id \
               JOIN topics t     ON q.topic_id = t.id \
               WHERE tr.user_id = ?1 AND mt.user_id = ?1 \
                 AND mt.status = 'completed' \
                 AND (q.disabled IS NULL OR q.disabled = 0) \
               GROUP BY t.id, bucket";
    let mut rows = state.db.conn().query(sql, params![user_id]).await?;

    let buckets: Vec<String> = vec!["last_7d".into(), "last_30d".into(), "older".into()];
    let mut by_topic: HashMap<i64, HeatmapRow> = HashMap::new();

    while let Some(row) = rows.next().await? {
        let topic_id: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("heatmap-rec: read topic_id: {e}")))?;
        let name = value_to_opt_string(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("heatmap-rec: read name: {e}")))?,
        );
        let weightage = value_to_opt_i64(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("heatmap-rec: read weightage: {e}")))?,
        )
        .unwrap_or(5);
        let bucket = value_to_opt_string(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("heatmap-rec: read bucket: {e}")))?,
        )
        .unwrap_or_else(|| "older".into());
        let attempts = value_to_opt_i64(
            row.get_value(4)
                .map_err(|e| AppError::Internal(format!("heatmap-rec: read attempts: {e}")))?,
        )
        .unwrap_or(0);
        let correct = value_to_opt_i64(
            row.get_value(5)
                .map_err(|e| AppError::Internal(format!("heatmap-rec: read correct: {e}")))?,
        )
        .unwrap_or(0);

        let entry = by_topic
            .entry(topic_id)
            .or_insert_with(|| new_row(topic_id, name.clone(), weightage, &buckets));
        if buckets.contains(&bucket) {
            let acc = if attempts > 0 {
                round1((correct as f64 / attempts as f64) * 100.0)
            } else {
                0.0
            };
            entry.cells.insert(
                bucket,
                Some(HeatmapCell {
                    attempts,
                    correct,
                    accuracy_pct: acc,
                }),
            );
        }
    }

    Ok(Json(HeatmapResponse {
        dim: "recency".into(),
        buckets,
        rows: sort_heatmap_rows(by_topic.into_values().collect()),
    }))
}

fn new_row(
    topic_id: i64,
    name: Option<String>,
    weightage: i64,
    buckets: &[String],
) -> HeatmapRow {
    let mut cells: BTreeMap<String, Option<HeatmapCell>> = BTreeMap::new();
    for b in buckets {
        cells.insert(b.clone(), None);
    }
    HeatmapRow {
        topic_id,
        topic_name: name,
        weightage,
        cells,
    }
}

/// Deterministic ordering — by weightage DESC then name ASC. Matches
/// `bp_analytics.py::_heatmap_by_difficulty`'s sort tuple.
fn sort_heatmap_rows(mut rows: Vec<HeatmapRow>) -> Vec<HeatmapRow> {
    rows.sort_by(|a, b| {
        b.weightage
            .cmp(&a.weightage)
            .then_with(|| a.topic_name.cmp(&b.topic_name))
    });
    rows
}

// ================================================================
// GET /analytics/consistency
// ================================================================

/// 28-day activity strip + consistency score.
///
/// Definition of an "active day" (matches `bp_main.py::_consistency`):
///   * ≥1 mock_test with `status='completed'` on that date, OR
///   * ≥1 study_session with `duration_min >= 10` on that date.
///
/// `score_pct = min(100, round(active_days_28 * 100 / 20))` — the 20-day
/// denominator makes 5 study days/week hit 100%.
pub async fn consistency(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
) -> Result<Json<ConsistencyResponse>, AppError> {
    let days_window: i64 = 28;
    let denominator: i64 = 20;

    let today = Utc::now().date_naive();
    let start = today - Duration::days(days_window - 1);
    let start_iso = start.format("%Y-%m-%d").to_string();

    let mut active: HashSet<String> = HashSet::new();

    // Mock tests: date(completed_at) within window, completed, this user.
    let mt_sql = "SELECT DISTINCT date(completed_at) AS d \
                  FROM mock_tests \
                  WHERE user_id = ?1 \
                    AND status = 'completed' \
                    AND date(completed_at) >= ?2";
    if let Ok(mut rows) = state
        .db
        .conn()
        .query(mt_sql, params![auth.id, start_iso.clone()])
        .await
    {
        while let Ok(Some(row)) = rows.next().await {
            if let Some(d) = value_to_opt_string(
                row.get_value(0)
                    .unwrap_or(libsql::Value::Null),
            ) {
                active.insert(d);
            }
        }
    }

    // Study sessions: date(date), duration_min >= 10, this user.
    let ss_sql = "SELECT DISTINCT date(date) AS d \
                  FROM study_sessions \
                  WHERE user_id = ?1 \
                    AND date(date) >= ?2 \
                    AND COALESCE(duration_min, 0) >= 10";
    if let Ok(mut rows) = state
        .db
        .conn()
        .query(ss_sql, params![auth.id, start_iso])
        .await
    {
        while let Ok(Some(row)) = rows.next().await {
            if let Some(d) = value_to_opt_string(
                row.get_value(0)
                    .unwrap_or(libsql::Value::Null),
            ) {
                active.insert(d);
            }
        }
    }

    let active_days_28 = active.len() as i64;
    let score_pct = ((active_days_28 as f64) * (100.0 / denominator as f64))
        .round()
        .min(100.0) as i64;

    // Activity strip: index 0 = 27 days ago, index 27 = today.
    let mut strip: Vec<bool> = Vec::with_capacity(days_window as usize);
    for i in 0..days_window {
        let d = start + Duration::days(i);
        let key = d.format("%Y-%m-%d").to_string();
        strip.push(active.contains(&key));
    }

    // Streak: consecutive active days ending TODAY (walk back from the
    // tail; stop at the first inactive slot).
    let mut streak_days: i64 = 0;
    for is_active in strip.iter().rev() {
        if *is_active {
            streak_days += 1;
        } else {
            break;
        }
    }

    Ok(Json(ConsistencyResponse {
        score_pct,
        active_days_28,
        denominator,
        streak_days,
        activity_strip: strip,
    }))
}

// ================================================================
// GET /analytics/next-weak-topic
// ================================================================

/// Rank topics for the "study this next" recommendation.
///
/// Mirrors `bp_main.py::_rank_next_topic`:
///   score = gap × weightage × recency × confidence
///   gap        = max(0, target - current_score)
///   recency    = 0.3 (<3 days), 0.7 (<7), 1.0 (>=7)
///   confidence = min(1.0, test_count / 5)
///
/// Untested topics jump to `weightage * 2` and use the reason string
/// `untested · <weightage> exam pts if mastered`.
pub async fn next_weak_topic(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
) -> Result<Json<NextWeakTopicResponse>, AppError> {
    // Read the target score first — settings_int borrows the connection
    // for its own round-trip, so we get that out of the way before we
    // start iterating rows below.
    let target: f64 = settings_int(&state, "target_score", 75).await as f64;
    let today = Utc::now().date_naive();

    // Pull the same shape `mastery()` reads: topic + optional mastery.
    let sql = "SELECT t.id, t.name, COALESCE(t.weightage, 5) AS weightage, \
                      tm.current_score, tm.last_studied, \
                      COALESCE(tm.test_count, 0) AS test_count \
               FROM topics t \
               LEFT JOIN topic_mastery tm \
                      ON tm.topic_id = t.id AND tm.user_id = ?1";
    let mut rows = state.db.conn().query(sql, params![auth.id]).await?;

    // Pull the topic list first — we score in-Rust so we can preserve
    // the branch structure of `_score_topic` verbatim.
    let mut topics: Vec<TopicScoringRow> = Vec::new();
    while let Some(row) = rows.next().await? {
        let id: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("next-weak: read id: {e}")))?;
        let name = value_to_opt_string(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("next-weak: read name: {e}")))?,
        );
        let weightage = value_to_opt_i64(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("next-weak: read weightage: {e}")))?,
        )
        .unwrap_or(5);
        let current = value_to_opt_f64(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("next-weak: read current: {e}")))?,
        );
        let last_studied = value_to_opt_string(
            row.get_value(4)
                .map_err(|e| AppError::Internal(format!("next-weak: read last: {e}")))?,
        );
        let test_count = value_to_opt_i64(
            row.get_value(5)
                .map_err(|e| AppError::Internal(format!("next-weak: read tc: {e}")))?,
        )
        .unwrap_or(0);

        let days = last_studied
            .as_deref()
            .and_then(parse_iso_date_head)
            .map(|d| (today - d).num_days());
        topics.push(TopicScoringRow {
            id,
            name,
            weightage,
            current,
            days,
            test_count,
        });
    }

    // Score each topic.
    let mut scored: Vec<(f64, NextTopicEntry)> = Vec::new();
    for t in &topics {
        let (score, entry) = score_topic(t, target);
        if score > 0.0 {
            scored.push((score, entry));
        }
    }
    // DESC by score.
    scored.sort_by(|a, b| {
        b.0.partial_cmp(&a.0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut iter = scored.into_iter().map(|(_, e)| e);
    let top_topic = iter.next();
    let alternatives: Vec<NextTopicEntry> = iter.take(2).collect();

    Ok(Json(NextWeakTopicResponse {
        top_topic,
        alternatives,
    }))
}

/// Row fed to `score_topic`. Not on the wire — pure in-memory shape.
struct TopicScoringRow {
    id: i64,
    name: Option<String>,
    weightage: i64,
    current: Option<f64>,
    days: Option<i64>,
    test_count: i64,
}

/// Compute `(score, entry)` for one topic. `score == 0.0` = skip.
///
/// Mirrors `bp_main.py::_score_topic` line-for-line:
///   * untested (`test_count == 0`) → score = `weightage * 2.0`, reason
///     "untested · N exam pts if mastered".
///   * studied within 24h → skip (score 0).
///   * otherwise recency ∈ {0.3, 0.7, 1.0} depending on days-since,
///     confidence ∈ [0, 1] capped at `test_count / 5`, and
///     score = gap × weightage × recency × confidence.
fn score_topic(t: &TopicScoringRow, target: f64) -> (f64, NextTopicEntry) {
    let weightage = t.weightage;
    let test_count = t.test_count;
    let current = t.current.unwrap_or(0.0);
    let days = t.days.unwrap_or(9999);

    // Untested boost — matches `bp_main.py::_score_topic`.
    if test_count == 0 {
        let score = (weightage as f64) * 2.0;
        return (
            score,
            NextTopicEntry {
                topic_id: t.id,
                name: t.name.clone(),
                weightage,
                reason_str: format!("untested · {weightage} exam pts if mastered"),
                exam_points_at_stake: weightage as f64,
            },
        );
    }

    // Recency skip: studied in the last day → don't recommend.
    if days < 1 {
        return (
            0.0,
            NextTopicEntry {
                topic_id: t.id,
                name: t.name.clone(),
                weightage,
                reason_str: String::new(),
                exam_points_at_stake: 0.0,
            },
        );
    }
    let recency: f64 = if days < 3 {
        0.3
    } else if days < 7 {
        0.7
    } else {
        1.0
    };

    let gap = (target - current).max(0.0);
    if gap <= 0.0 {
        return (
            0.0,
            NextTopicEntry {
                topic_id: t.id,
                name: t.name.clone(),
                weightage,
                reason_str: String::new(),
                exam_points_at_stake: 0.0,
            },
        );
    }

    let confidence = (test_count as f64 / 5.0).min(1.0);
    let score = gap * (weightage as f64) * recency * confidence;
    let est_points = round1((gap / 100.0) * weightage as f64);
    let reason = format!(
        "current {}% · weight {} · studied {}d ago · could gain +{} exam pts",
        current as i64, weightage, days, est_points
    );

    (
        score,
        NextTopicEntry {
            topic_id: t.id,
            name: t.name.clone(),
            weightage,
            reason_str: reason,
            exam_points_at_stake: est_points,
        },
    )
}

// ================================================================
// GET /analytics/pacing
// ================================================================

/// Pacing dashboard.
///
///   * `tests` — per-test avg_sec_per_q from `test_responses`
///   * `target_sec_per_q` — from `settings.target_seconds_per_q` (default 72)
///   * `moving_avg_5` — 5-test trailing mean of `avg_sec_per_q`
///   * `by_difficulty` — mean sec/question grouped by difficulty
///   * `slow_and_wrong` — top 10 questions where the user was slow AND wrong
pub async fn pacing(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
) -> Result<Json<PacingResponse>, AppError> {
    let target_sec_per_q = settings_int(&state, "target_seconds_per_q", 72).await;

    // Per-test avg_sec_per_q. Only completed tests for the caller.
    let sql = "SELECT mt.id, AVG(tr.time_spent_sec) AS avg_time \
               FROM mock_tests mt \
               JOIN test_responses tr ON mt.id = tr.test_id \
               WHERE mt.user_id = ?1 AND tr.user_id = ?1 \
                 AND mt.status = 'completed' \
               GROUP BY mt.id \
               ORDER BY mt.completed_at";
    let mut rows = state.db.conn().query(sql, params![auth.id]).await?;
    let mut tests: Vec<PacingTestRow> = Vec::new();
    while let Some(row) = rows.next().await? {
        let test_id: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("pacing: read test_id: {e}")))?;
        let avg = value_to_opt_f64(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("pacing: read avg_time: {e}")))?,
        )
        .unwrap_or(0.0);
        tests.push(PacingTestRow {
            test_id,
            avg_sec_per_q: round1(avg),
        });
    }

    // 5-test trailing moving average.
    let mut moving_avg_5: Vec<Option<f64>> = Vec::with_capacity(tests.len());
    let window: usize = 5;
    for i in 0..tests.len() {
        let lo = if i + 1 > window { i + 1 - window } else { 0 };
        let chunk = &tests[lo..=i];
        if chunk.is_empty() {
            moving_avg_5.push(None);
        } else {
            let sum: f64 = chunk.iter().map(|t| t.avg_sec_per_q).sum();
            moving_avg_5.push(Some(round1(sum / chunk.len() as f64)));
        }
    }

    // by_difficulty
    let diff_sql = "SELECT COALESCE(q.difficulty, 'medium') AS difficulty, \
                           AVG(tr.time_spent_sec) AS avg_time \
                    FROM test_responses tr \
                    JOIN questions q ON tr.question_id = q.id \
                    JOIN mock_tests mt ON tr.test_id = mt.id \
                    WHERE tr.user_id = ?1 AND mt.user_id = ?1 \
                      AND mt.status = 'completed' \
                    GROUP BY difficulty";
    let mut rows = state.db.conn().query(diff_sql, params![auth.id]).await?;
    let mut easy_actual = 0.0f64;
    let mut medium_actual = 0.0f64;
    let mut hard_actual = 0.0f64;
    while let Some(row) = rows.next().await? {
        let d = value_to_opt_string(
            row.get_value(0)
                .map_err(|e| AppError::Internal(format!("pacing-diff: read d: {e}")))?,
        )
        .unwrap_or_default();
        let avg = value_to_opt_f64(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("pacing-diff: read avg: {e}")))?,
        )
        .unwrap_or(0.0);
        match d.as_str() {
            "easy" => easy_actual = round1(avg),
            "medium" => medium_actual = round1(avg),
            "hard" => hard_actual = round1(avg),
            _ => {}
        }
    }
    let by_difficulty = PacingByDifficultyMap {
        easy: PacingByDifficulty {
            target: target_sec_per_q,
            actual: easy_actual,
        },
        medium: PacingByDifficulty {
            target: target_sec_per_q,
            actual: medium_actual,
        },
        hard: PacingByDifficulty {
            target: target_sec_per_q,
            actual: hard_actual,
        },
    };

    // slow_and_wrong: is_correct=0 AND time_spent_sec > 2 * target. Top 10.
    let sw_sql = "SELECT q.id, q.question_text, q.difficulty, \
                         tr.time_spent_sec, t.name AS topic \
                  FROM test_responses tr \
                  JOIN questions q ON tr.question_id = q.id \
                  JOIN topics t   ON q.topic_id = t.id \
                  JOIN mock_tests mt ON tr.test_id = mt.id \
                  WHERE tr.user_id = ?1 AND mt.user_id = ?1 \
                    AND tr.is_correct = 0 \
                    AND tr.time_spent_sec > (2.0 * ?2) \
                  ORDER BY tr.time_spent_sec DESC \
                  LIMIT 10";
    let mut rows = state
        .db
        .conn()
        .query(sw_sql, params![auth.id, target_sec_per_q])
        .await?;
    let mut slow_and_wrong: Vec<SlowAndWrongRow> = Vec::new();
    while let Some(row) = rows.next().await? {
        let question_id: i64 = row
            .get::<i64>(0)
            .map_err(|e| AppError::Internal(format!("slow-wrong: read qid: {e}")))?;
        let question_text = value_to_opt_string(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("slow-wrong: read qtext: {e}")))?,
        );
        let difficulty = value_to_opt_string(
            row.get_value(2)
                .map_err(|e| AppError::Internal(format!("slow-wrong: read diff: {e}")))?,
        );
        let time_spent = value_to_opt_f64(
            row.get_value(3)
                .map_err(|e| AppError::Internal(format!("slow-wrong: read time: {e}")))?,
        )
        .unwrap_or(0.0);
        let topic_name = value_to_opt_string(
            row.get_value(4)
                .map_err(|e| AppError::Internal(format!("slow-wrong: read topic: {e}")))?,
        );
        slow_and_wrong.push(SlowAndWrongRow {
            question_id,
            topic_name,
            question_text,
            time_spent: round1(time_spent),
            difficulty,
        });
    }

    Ok(Json(PacingResponse {
        tests,
        target_sec_per_q,
        moving_avg_5,
        by_difficulty,
        slow_and_wrong,
    }))
}

// ================================================================
// GET /analytics/error-dist
// ================================================================

/// Error distribution used by the dashboard.
///
///   * `by_topic` — one row per topic with an error count DESC
///   * `by_type`  — one row per `error_type` (concept_gap / time_pressure / …)
pub async fn error_dist(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
) -> Result<Json<ErrorDistResponse>, AppError> {
    let by_topic_sql = "SELECT t.name, COUNT(*) AS cnt \
                        FROM error_log el \
                        JOIN topics t ON el.topic_id = t.id \
                        WHERE el.user_id = ?1 \
                        GROUP BY t.id \
                        ORDER BY cnt DESC";
    let mut by_topic: Vec<ErrorByTopic> = Vec::new();
    let mut rows = state.db.conn().query(by_topic_sql, params![auth.id]).await?;
    while let Some(row) = rows.next().await? {
        let topic_name = value_to_opt_string(
            row.get_value(0)
                .map_err(|e| AppError::Internal(format!("edist-topic: read name: {e}")))?,
        );
        let error_count = value_to_opt_i64(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("edist-topic: read cnt: {e}")))?,
        )
        .unwrap_or(0);
        by_topic.push(ErrorByTopic {
            topic_name,
            error_count,
        });
    }

    let by_type_sql = "SELECT error_type, COUNT(*) AS cnt \
                       FROM error_log \
                       WHERE user_id = ?1 \
                       GROUP BY error_type \
                       ORDER BY cnt DESC";
    let mut by_type: Vec<ErrorByType> = Vec::new();
    let mut rows = state.db.conn().query(by_type_sql, params![auth.id]).await?;
    while let Some(row) = rows.next().await? {
        let error_type = value_to_opt_string(
            row.get_value(0)
                .map_err(|e| AppError::Internal(format!("edist-type: read t: {e}")))?,
        );
        let count = value_to_opt_i64(
            row.get_value(1)
                .map_err(|e| AppError::Internal(format!("edist-type: read cnt: {e}")))?,
        )
        .unwrap_or(0);
        by_type.push(ErrorByType { error_type, count });
    }

    Ok(Json(ErrorDistResponse { by_topic, by_type }))
}

// ---------- GET /api/v1/analytics/paper-performance ------------------------

/// Per-paper average score + test count for the current user.
///
/// Frontend Dashboard renders a small "Paper I / Paper II" card. If the
/// user has no completed tests yet the response is `{ items: [] }` and
/// the FE shows an empty-state.
#[derive(Debug, serde::Serialize)]
pub struct PaperPerfItem {
    pub paper: String,
    pub avg_score: f64,
    pub test_count: i64,
}

#[derive(Debug, serde::Serialize)]
pub struct PaperPerfResponse {
    pub items: Vec<PaperPerfItem>,
}

pub async fn paper_performance(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
) -> Result<Json<PaperPerfResponse>, AppError> {
    let sql = "SELECT paper, AVG(score) AS avg_score, COUNT(*) AS n \
               FROM mock_tests \
               WHERE user_id = ?1 AND status = 'completed' AND paper IS NOT NULL \
               GROUP BY paper \
               ORDER BY paper";
    let mut rows = state.db.conn().query(sql, params![auth.id]).await?;
    let mut items = Vec::new();
    while let Some(row) = rows.next().await? {
        let paper = value_to_opt_string(row.get_value(0).unwrap_or(libsql::Value::Null))
            .unwrap_or_else(|| "?".into());
        let avg_score = row.get::<f64>(1).unwrap_or(0.0);
        let test_count = row.get::<i64>(2).unwrap_or(0);
        items.push(PaperPerfItem { paper, avg_score, test_count });
    }
    Ok(Json(PaperPerfResponse { items }))
}
