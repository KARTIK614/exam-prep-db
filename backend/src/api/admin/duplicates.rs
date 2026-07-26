//! Admin duplicate-question detection.
//!
//! Endpoints:
//!   GET  /api/v1/admin/duplicates
//!   POST /api/v1/admin/duplicates/resolve
//!
//! Detection uses the precomputed `question_trigrams` table + a Jaccard
//! self-join. The keeper heuristic prefers PYQ > confidence=high > longer
//! explanation > newer updated_at.

use axum::extract::{Query, State};
use axum::Json;
use chrono::Utc;
use libsql::params;
use std::collections::HashMap;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAdmin;
use crate::models::{value_to_opt_i64, value_to_opt_string, Question};
use crate::schemas::admin::{
    AdminDuplicateListResponse, AdminDuplicateQuery, AdminDuplicateResolveRequest,
    AdminDuplicateResolveResponse, DuplicatePair,
};

// ---------- GET /admin/duplicates ------------------------------------------

pub async fn list_duplicates(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Query(q): Query<AdminDuplicateQuery>,
) -> Result<Json<AdminDuplicateListResponse>, AppError> {
    let limit = q.limit.unwrap_or(50).min(200) as i64;
    let threshold = q.threshold.unwrap_or(0.7).clamp(0.5, 1.0);

    // Total trigram-row count — useful sanity for the FE header.
    let mut rows = state
        .db
        .conn()
        .query("SELECT COUNT(*) FROM question_trigrams", ())
        .await?;
    let total_trigrams: i64 = match rows.next().await? {
        Some(row) => row.get::<i64>(0)?,
        None => 0,
    };

    // Per-question trigram count map: needed for Jaccard denominator.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT question_id, COUNT(*) FROM question_trigrams GROUP BY question_id",
            (),
        )
        .await?;
    let mut counts: HashMap<i64, i64> = HashMap::new();
    while let Some(row) = rows.next().await? {
        let qid: i64 = row.get::<i64>(0)?;
        let c: i64 = row.get::<i64>(1)?;
        counts.insert(qid, c);
    }

    // Intersection sizes for each unordered pair (a<b).
    let inter_sql =
        "SELECT a.question_id AS q1, b.question_id AS q2, COUNT(*) AS isize \
           FROM question_trigrams a \
           JOIN question_trigrams b \
             ON a.trigram = b.trigram AND a.question_id < b.question_id \
          GROUP BY a.question_id, b.question_id \
          HAVING isize >= 5 \
          ORDER BY isize DESC \
          LIMIT ?";
    let mut rows = state
        .db
        .conn()
        .query(inter_sql, params![limit * 4]) // over-fetch, filter by threshold below
        .await?;

    let mut candidates: Vec<(i64, i64, i64, f64)> = Vec::new();
    while let Some(row) = rows.next().await? {
        let q1: i64 = row.get::<i64>(0)?;
        let q2: i64 = row.get::<i64>(1)?;
        let isize_v: i64 = row.get::<i64>(2)?;
        let n1 = *counts.get(&q1).unwrap_or(&0);
        let n2 = *counts.get(&q2).unwrap_or(&0);
        let union = n1 + n2 - isize_v;
        if union <= 0 {
            continue;
        }
        let jacc = isize_v as f64 / union as f64;
        if jacc >= threshold {
            candidates.push((q1, q2, isize_v, jacc));
        }
        if candidates.len() as i64 >= limit {
            break;
        }
    }

    // Load the actual question rows for each candidate id (dedup + one round-trip).
    let mut ids: Vec<i64> = candidates
        .iter()
        .flat_map(|(a, b, _, _)| [*a, *b])
        .collect();
    ids.sort_unstable();
    ids.dedup();

    let questions = load_questions(&state, &ids).await?;
    let by_id: HashMap<i64, Question> = questions.into_iter().map(|q| (q.id, q)).collect();

    // Reference-count map: how many test_responses / error_log / bookmarks
    // rows refer to this question. Higher refs → prefer as keeper.
    let refs = load_refs(&state, &ids).await?;

    let mut pairs: Vec<DuplicatePair> = Vec::new();
    for (q1_id, q2_id, isize_v, jacc) in candidates {
        let (Some(q1), Some(q2)) = (by_id.get(&q1_id).cloned(), by_id.get(&q2_id).cloned()) else {
            continue;
        };
        let n1 = *counts.get(&q1_id).unwrap_or(&0);
        let n2 = *counts.get(&q2_id).unwrap_or(&0);
        let q1_refs = *refs.get(&q1_id).unwrap_or(&0);
        let q2_refs = *refs.get(&q2_id).unwrap_or(&0);
        let (keep, drop) = keep_better_of(&q1, &q2);
        pairs.push(DuplicatePair {
            q1,
            q2,
            jaccard: jacc,
            isize: isize_v,
            n1,
            n2,
            suggested_keep: keep,
            suggested_disable: drop,
            q1_refs,
            q2_refs,
        });
    }

    Ok(Json(AdminDuplicateListResponse {
        pairs,
        threshold,
        total_trigrams,
    }))
}

// ---------- POST /admin/duplicates/resolve ---------------------------------

pub async fn resolve_duplicate(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Json(req): Json<AdminDuplicateResolveRequest>,
) -> Result<Json<AdminDuplicateResolveResponse>, AppError> {
    if req.keeper_id == req.loser_id {
        return Err(AppError::BadRequest(
            "keeper_id and loser_id must differ".into(),
        ));
    }
    // Verify both exist so we don't leave stale rows around.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT id FROM questions WHERE id IN (?, ?)",
            params![req.keeper_id, req.loser_id],
        )
        .await?;
    let mut found = 0;
    while (rows.next().await?).is_some() {
        found += 1;
    }
    if found != 2 {
        return Err(AppError::NotFound("question pair"));
    }

    state
        .db
        .conn()
        .execute(
            "UPDATE questions SET disabled = 1, updated_at = ? WHERE id = ?",
            params![Utc::now().to_rfc3339(), req.loser_id],
        )
        .await?;

    Ok(Json(AdminDuplicateResolveResponse {
        keeper_id: req.keeper_id,
        loser_id: req.loser_id,
        disabled: true,
    }))
}

// ---------- helpers --------------------------------------------------------

async fn load_questions(state: &AppState, ids: &[i64]) -> Result<Vec<Question>, AppError> {
    if ids.is_empty() {
        return Ok(Vec::new());
    }
    let cols = Question::COLUMNS
        .iter()
        .map(|c| format!("q.{c}"))
        .collect::<Vec<_>>()
        .join(", ");
    let placeholders = std::iter::repeat("?")
        .take(ids.len())
        .collect::<Vec<_>>()
        .join(",");
    let sql = format!("SELECT {cols} FROM questions q WHERE q.id IN ({placeholders})");
    let vals: Vec<libsql::Value> = ids.iter().map(|i| libsql::Value::Integer(*i)).collect();
    let mut rows = state.db.conn().query(&sql, vals).await?;
    let mut out: Vec<Question> = Vec::with_capacity(ids.len());
    while let Some(row) = rows.next().await? {
        out.push(Question::from_row(&row)?);
    }
    Ok(out)
}

/// Count references (test_responses + error_log + bookmarks) per qid so
/// the FE can warn admins before disabling a heavily-used question.
async fn load_refs(state: &AppState, ids: &[i64]) -> Result<HashMap<i64, i64>, AppError> {
    let mut out: HashMap<i64, i64> = HashMap::new();
    if ids.is_empty() {
        return Ok(out);
    }
    let placeholders = std::iter::repeat("?")
        .take(ids.len())
        .collect::<Vec<_>>()
        .join(",");
    let sql = format!(
        "SELECT question_id, COUNT(*) FROM ( \
           SELECT question_id FROM test_responses WHERE question_id IN ({placeholders}) \
           UNION ALL \
           SELECT question_id FROM error_log WHERE question_id IN ({placeholders}) \
           UNION ALL \
           SELECT question_id FROM bookmarks WHERE question_id IN ({placeholders}) \
         ) \
         GROUP BY question_id"
    );
    let mut vals: Vec<libsql::Value> = Vec::with_capacity(ids.len() * 3);
    for _ in 0..3 {
        for id in ids {
            vals.push(libsql::Value::Integer(*id));
        }
    }
    let mut rows = state.db.conn().query(&sql, vals).await?;
    while let Some(row) = rows.next().await? {
        let qid = value_to_opt_i64(row.get_value(0)?).unwrap_or(0);
        let c: i64 = row.get::<i64>(1)?;
        out.insert(qid, c);
    }
    Ok(out)
}

/// Heuristic: PYQ > confidence=high > longer explanation > newer updated_at.
/// Returns `(keeper_id, loser_id)`.
fn keep_better_of(a: &Question, b: &Question) -> (i64, i64) {
    let a_score = quality_score(a);
    let b_score = quality_score(b);
    if a_score >= b_score {
        (a.id, b.id)
    } else {
        (b.id, a.id)
    }
}

fn quality_score(q: &Question) -> i64 {
    let mut score = 0i64;
    if q.pyq_exam.as_deref().map(|s| !s.is_empty()).unwrap_or(false) {
        score += 1_000_000;
    }
    if q.confidence.as_deref() == Some("high") {
        score += 100_000;
    }
    if let Some(expl) = q.explanation.as_deref() {
        score += expl.len().min(50_000) as i64;
    }
    if let Some(ts) = q.updated_at.as_deref() {
        // Recent timestamps ISO-sort correctly; hash first 10 bytes to
        // reduce collision noise. Simpler: bake in an epoch-day estimate.
        // We just use lexicographic ordering: the raw string sorts fine
        // for ISO-8601 so add its byte-sum modulo something small.
        score += ts.bytes().map(|b| b as i64).sum::<i64>().min(10_000);
    }
    score
}
