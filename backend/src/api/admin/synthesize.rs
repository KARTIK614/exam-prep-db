//! Admin question synthesis via DeepSeek.
//!
//! Endpoints:
//!   POST /api/v1/admin/synthesize
//!   GET  /api/v1/admin/synthesize/{batch_id}
//!   POST /api/v1/admin/synthesize/{batch_id}/commit
//!
//! Pre-flight: refuse when `n_requested` would push the topic past
//! 40 % synthetic content (per Plan D §4 quality cap).
//!
//! Generated rows are inserted with `source='synthetic-v1'` and
//! `confidence='medium'` so they surface in the admin review queue
//! before being served to end users.

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::Json;
use chrono::Utc;
use libsql::params;
use secrecy::ExposeSecret;
use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAdmin;
use crate::models::{value_to_opt_i64, value_to_opt_string, Question};
use crate::schemas::admin::{
    AdminSynthesizeCommitResponse, AdminSynthesizeRequest, AdminSynthesizeResponse,
    AdminSynthesizeStatusResponse,
};

const SYNTHETIC_CAP_RATIO: f64 = 0.40;
const MODEL_NAME: &str = "deepseek-chat";

// ---------- POST /admin/synthesize -----------------------------------------

pub async fn start_batch(
    State(state): State<AppState>,
    RequireAdmin(caller): RequireAdmin,
    Json(req): Json<AdminSynthesizeRequest>,
) -> Result<(StatusCode, Json<AdminSynthesizeResponse>), AppError> {
    if req.n_requested == 0 || req.n_requested > 50 {
        return Err(AppError::BadRequest(
            "n_requested must be between 1 and 50".into(),
        ));
    }

    // VAPT H-5: cap the number of generations a single admin can
    // schedule in a rolling 24h window. The route-level rate-limit is
    // IP-scoped and does not defend against a stolen admin token behind
    // a proxy rotation. 200 generations/day = ~$X ceiling on DeepSeek
    // spend; adjust if the batch-size hard cap moves off 50.
    const DAILY_GEN_CAP_PER_ADMIN: i64 = 200;
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT COALESCE(SUM(n_requested), 0) FROM synthesis_batches \
             WHERE user_id = ?1 \
               AND datetime(generated_at) >= datetime('now', '-1 day')",
            params![caller.id],
        )
        .await?;
    let used_today: i64 = match rows.next().await? {
        Some(row) => row.get::<i64>(0).unwrap_or(0),
        None => 0,
    };
    if used_today + req.n_requested as i64 > DAILY_GEN_CAP_PER_ADMIN {
        return Ok((
            StatusCode::TOO_MANY_REQUESTS,
            Json(AdminSynthesizeResponse {
                batch_id: 0,
                topic_id: req.topic_id,
                n_requested: req.n_requested,
                status: "rejected".into(),
                cap_message: Some(format!(
                    "daily per-admin synthesis cap {DAILY_GEN_CAP_PER_ADMIN} \
                     reached ({used_today} used in last 24h)"
                )),
            }),
        ));
    }

    // Cap check: (existing synth for this topic + n_requested) must not
    // exceed 40 % of active rows in the topic.
    let (existing_total, existing_synth) = topic_counts(&state, req.topic_id).await?;
    let cap = (existing_total as f64 * SYNTHETIC_CAP_RATIO).floor() as i64;
    if existing_synth + req.n_requested as i64 > cap {
        let cap_message = format!(
            "topic has {existing_total} active rows; synthetic cap is {cap} \
             (40%), existing synth = {existing_synth}, requested = {}",
            req.n_requested
        );
        return Ok((
            StatusCode::CONFLICT,
            Json(AdminSynthesizeResponse {
                batch_id: 0,
                topic_id: req.topic_id,
                n_requested: req.n_requested,
                status: "rejected".into(),
                cap_message: Some(cap_message),
            }),
        ));
    }

    let prompt_hash = hash_hex(&format!(
        "topic={} n={} sub={}",
        req.topic_id,
        req.n_requested,
        req.sub_topics.clone().unwrap_or_default()
    ));

    // Insert the batch row up-front so the FE can poll.
    let sql = "INSERT INTO synthesis_batches \
        (topic_id, generated_at, n_requested, n_generated, prompt_hash, model, status, user_id) \
        VALUES (?, ?, ?, 0, ?, ?, 'pending', ?) \
        RETURNING id";
    let mut rows = state
        .db
        .conn()
        .query(
            sql,
            params![
                req.topic_id,
                Utc::now().to_rfc3339(),
                req.n_requested as i64,
                prompt_hash,
                MODEL_NAME.to_string(),
                caller.id,
            ],
        )
        .await?;
    let batch_id: i64 = match rows.next().await? {
        Some(row) => row.get::<i64>(0)?,
        None => return Err(AppError::Internal("INSERT ... RETURNING produced no row".into())),
    };

    // Kick off generation synchronously — the request handler doesn't
    // return until DeepSeek finishes. For our scale (≤ 50 questions per
    // batch, ~1-2 minutes total) this is simpler than a background job.
    let generated = match generate_batch(&state, batch_id, &req).await {
        Ok(n) => n,
        Err(err) => {
            state
                .db
                .conn()
                .execute(
                    "UPDATE synthesis_batches SET status = 'error', notes = ? WHERE id = ?",
                    params![format!("{err:#}"), batch_id],
                )
                .await?;
            return Err(AppError::Upstream(format!("synthesis failed: {err:#}")));
        }
    };

    state
        .db
        .conn()
        .execute(
            "UPDATE synthesis_batches SET status = 'ready', n_generated = ?, n_pending = ? \
              WHERE id = ?",
            params![generated, generated, batch_id],
        )
        .await?;

    Ok((
        StatusCode::CREATED,
        Json(AdminSynthesizeResponse {
            batch_id,
            topic_id: req.topic_id,
            n_requested: req.n_requested,
            status: "ready".into(),
            cap_message: None,
        }),
    ))
}

// ---------- GET /admin/synthesize/{batch_id} -------------------------------

pub async fn get_batch(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Path(batch_id): Path<i64>,
) -> Result<Json<AdminSynthesizeStatusResponse>, AppError> {
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT b.id, b.topic_id, t.name AS topic_name, b.model, b.status, \
                    b.n_requested, b.n_generated, b.n_pending, b.notes \
               FROM synthesis_batches b \
               LEFT JOIN topics t ON t.id = b.topic_id \
              WHERE b.id = ? LIMIT 1",
            params![batch_id],
        )
        .await?;
    let Some(row) = rows.next().await? else {
        return Err(AppError::NotFound("synthesis batch"));
    };
    let batch_id: i64 = row.get::<i64>(0)?;
    let topic_id = value_to_opt_i64(row.get_value(1)?);
    let topic_name = value_to_opt_string(row.get_value(2)?);
    let model = value_to_opt_string(row.get_value(3)?);
    let status = value_to_opt_string(row.get_value(4)?);
    let n_requested = value_to_opt_i64(row.get_value(5)?);
    let n_generated = value_to_opt_i64(row.get_value(6)?);
    let n_pending = value_to_opt_i64(row.get_value(7)?);
    let notes = value_to_opt_string(row.get_value(8)?);

    // Preview the current pending rows (they live in `questions` already).
    let cols = Question::COLUMNS
        .iter()
        .map(|c| format!("q.{c}"))
        .collect::<Vec<_>>()
        .join(", ");
    let sql = format!(
        "SELECT {cols} FROM questions q \
          WHERE q.source = ? \
          ORDER BY q.id ASC LIMIT 100"
    );
    let batch_source = synthetic_source_tag(batch_id);
    let mut rows = state.db.conn().query(&sql, params![batch_source]).await?;
    let mut preview: Vec<Question> = Vec::new();
    while let Some(row) = rows.next().await? {
        preview.push(Question::from_row(&row)?);
    }

    Ok(Json(AdminSynthesizeStatusResponse {
        batch_id,
        topic_id,
        topic_name,
        model,
        status,
        n_requested,
        n_generated,
        n_pending,
        notes,
        preview,
    }))
}

// ---------- POST /admin/synthesize/{batch_id}/commit -----------------------

/// Commit is a lightweight state transition — the questions are already
/// inserted into `questions` with `confidence='medium'`. Committing marks
/// the batch as done + clears `n_pending`.
pub async fn commit_batch(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Path(batch_id): Path<i64>,
) -> Result<Json<AdminSynthesizeCommitResponse>, AppError> {
    let batch_source = synthetic_source_tag(batch_id);
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT COUNT(*) FROM questions \
              WHERE source = ? AND (disabled = 0 OR disabled IS NULL)",
            params![batch_source],
        )
        .await?;
    let activated: i64 = match rows.next().await? {
        Some(row) => row.get::<i64>(0)?,
        None => 0,
    };

    state
        .db
        .conn()
        .execute(
            "UPDATE synthesis_batches SET status = 'committed', n_pending = 0, \
                n_approved = ? WHERE id = ?",
            params![activated, batch_id],
        )
        .await?;

    Ok(Json(AdminSynthesizeCommitResponse {
        batch_id,
        activated,
        status: "committed".into(),
    }))
}

// ---------- generator ------------------------------------------------------

/// Ask DeepSeek to produce `n` MCQs given `k` few-shot exemplars from the
/// target topic. On success, INSERT the rows with source=`synthetic-vN`
/// + confidence='medium', and return the count actually inserted.
async fn generate_batch(
    state: &AppState,
    batch_id: i64,
    req: &AdminSynthesizeRequest,
) -> anyhow::Result<i64> {
    // Few-shot samples: up to 5 real questions from the same topic.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT question_text, option_a, option_b, option_c, option_d, \
                    correct_option, explanation \
               FROM questions \
              WHERE topic_id = ? \
                AND (disabled = 0 OR disabled IS NULL) \
                AND source NOT LIKE 'synthetic-v%' \
              ORDER BY RANDOM() LIMIT 5",
            params![req.topic_id],
        )
        .await?;
    let mut examples: Vec<String> = Vec::new();
    while let Some(row) = rows.next().await? {
        let q = value_to_opt_string(row.get_value(0)?).unwrap_or_default();
        let a = value_to_opt_string(row.get_value(1)?).unwrap_or_default();
        let b = value_to_opt_string(row.get_value(2)?).unwrap_or_default();
        let c = value_to_opt_string(row.get_value(3)?).unwrap_or_default();
        let d = value_to_opt_string(row.get_value(4)?).unwrap_or_default();
        let corr = value_to_opt_string(row.get_value(5)?).unwrap_or_default();
        let expl = value_to_opt_string(row.get_value(6)?).unwrap_or_default();
        examples.push(format!(
            "Q: {q}\nA) {a}\nB) {b}\nC) {c}\nD) {d}\nCorrect: {corr}\nExplanation: {expl}"
        ));
    }
    let few_shot = if examples.is_empty() {
        "(no in-topic examples available — use plausible domain-typical questions)".to_string()
    } else {
        examples.join("\n---\n")
    };

    // Topic name for context.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT name, subject FROM topics WHERE id = ? LIMIT 1",
            params![req.topic_id],
        )
        .await?;
    let (topic_name, subject) = match rows.next().await? {
        Some(row) => (
            value_to_opt_string(row.get_value(0)?).unwrap_or_default(),
            value_to_opt_string(row.get_value(1)?).unwrap_or_default(),
        ),
        None => (String::new(), String::new()),
    };

    let sub_topics = req.sub_topics.clone().unwrap_or_default();
    let n = req.n_requested;

    let user_prompt = format!(
        "Generate exactly {n} multiple-choice questions for a Rajasthan competitive exam.\n\
         Topic: {topic_name} (subject: {subject})\n\
         Sub-topics to prioritise: {sub_topics}\n\n\
         REFERENCE QUESTIONS (style + difficulty guide):\n{few_shot}\n\n\
         Return a JSON array of objects with keys: question_text, option_a, option_b, option_c, option_d, correct_option (A|B|C|D), explanation, difficulty (easy|medium|hard).\n\
         NO extra commentary, no code fences. Just the JSON array."
    );

    let key = state
        .config
        .llm
        .deepseek_primary_key
        .as_ref()
        .or(state.config.llm.deepseek_secondary_key.as_ref())
        .ok_or_else(|| anyhow::anyhow!("DEEPSEEK_PRIMARY_KEY not configured"))?;

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()?;

    let body = serde_json::json!({
        "model": MODEL_NAME,
        "messages": [
            { "role": "system", "content": "You are an expert MCQ writer for Indian competitive exams. Output valid JSON only." },
            { "role": "user", "content": user_prompt },
        ],
        "temperature": 0.7,
    });

    let resp = client
        .post("https://api.deepseek.com/v1/chat/completions")
        .bearer_auth(key.expose_secret())
        .json(&body)
        .send()
        .await?;
    let status = resp.status();
    if !status.is_success() {
        let snippet = resp.text().await.unwrap_or_default();
        return Err(anyhow::anyhow!(
            "deepseek {status}: {}",
            snippet.chars().take(400).collect::<String>()
        ));
    }
    let parsed: DeepSeekChatResponse = resp.json().await?;
    let content = parsed
        .choices
        .into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("deepseek: no choices"))?
        .message
        .content;

    // Strip markdown fences if the model added them anyway.
    let stripped = content
        .trim()
        .trim_start_matches("```json")
        .trim_start_matches("```")
        .trim_end_matches("```")
        .trim();
    let items: Vec<GeneratedQuestion> = serde_json::from_str(stripped)
        .map_err(|e| anyhow::anyhow!("deepseek returned invalid JSON: {e}"))?;

    let batch_source = synthetic_source_tag(batch_id);
    let now = Utc::now().to_rfc3339();
    let mut inserted = 0i64;
    for it in items.into_iter().take(n as usize) {
        let correct = it.correct_option.trim().to_ascii_uppercase();
        if correct.len() != 1 || !matches!(correct.as_str(), "A" | "B" | "C" | "D") {
            continue;
        }
        let difficulty = if matches!(it.difficulty.as_deref(), Some("easy") | Some("medium") | Some("hard")) {
            it.difficulty
        } else {
            Some("medium".to_string())
        };
        state
            .db
            .conn()
            .execute(
                "INSERT INTO questions \
                    (topic_id, question_text, option_a, option_b, option_c, option_d, \
                     correct_option, explanation, difficulty, source, confidence, \
                     disabled, updated_at) \
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'medium', 0, ?)",
                params![
                    req.topic_id,
                    it.question_text,
                    it.option_a,
                    it.option_b,
                    it.option_c,
                    it.option_d,
                    correct,
                    it.explanation,
                    difficulty,
                    batch_source.clone(),
                    now.clone(),
                ],
            )
            .await?;
        inserted += 1;
    }

    Ok(inserted)
}

async fn topic_counts(state: &AppState, topic_id: i64) -> Result<(i64, i64), AppError> {
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT COUNT(*), \
                    SUM(CASE WHEN source LIKE 'synthetic-v%' THEN 1 ELSE 0 END) \
               FROM questions \
              WHERE topic_id = ? AND (disabled = 0 OR disabled IS NULL)",
            params![topic_id],
        )
        .await?;
    if let Some(row) = rows.next().await? {
        let total: i64 = row.get::<i64>(0).unwrap_or(0);
        let synth: i64 = value_to_opt_i64(row.get_value(1)?).unwrap_or(0);
        Ok((total, synth))
    } else {
        Ok((0, 0))
    }
}

fn synthetic_source_tag(batch_id: i64) -> String {
    format!("synthetic-v1:{batch_id}")
}

fn hash_hex(s: &str) -> String {
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    hex::encode(h.finalize())
}

#[derive(Deserialize)]
struct DeepSeekChatResponse {
    choices: Vec<Choice>,
}

#[derive(Deserialize)]
struct Choice {
    message: ChoiceMessage,
}

#[derive(Deserialize)]
struct ChoiceMessage {
    content: String,
}

#[derive(Deserialize)]
struct GeneratedQuestion {
    question_text: String,
    option_a: String,
    option_b: String,
    option_c: String,
    option_d: String,
    correct_option: String,
    #[serde(default)]
    explanation: Option<String>,
    #[serde(default)]
    difficulty: Option<String>,
}
