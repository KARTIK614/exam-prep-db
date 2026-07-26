//! `POST /api/v1/questions/{qid}/deep-dive` — Gemini-backed tutor.
//!
//! Semantics preserved from `bp_doubt.py::deep_dive`:
//!   * Cache key: `deep_dive:{question_id}:{test_id}` (test_id defaults to
//!     the empty string so calls without a test_id share a cache slot).
//!   * On Gemini failure: mint an 8-char UUID `error_id`, log
//!     `tracing::error!("[{error_id}] deep-dive failed for qid={qid}
//!     tid={tid}")`, return `AppError::Upstream("AI tutor temporarily
//!     unavailable. Ref: {error_id}")` which maps to a 502 with the
//!     standard `{error: {code, message, request_id}}` envelope.
//!
//! Rate limit: 20/hour per IP applied at the route layer (see
//! `api::mod::router`).

use axum::extract::{Path, State};
use axum::Json;
use libsql::params;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::models::value_to_opt_string;
use crate::schemas::deep_dive::{DeepDiveRequest, DeepDiveResponse};
use crate::services::gemini;

pub async fn deep_dive(
    State(state): State<AppState>,
    RequireAuth(caller): RequireAuth,
    Path(qid): Path<i64>,
    body: Option<Json<DeepDiveRequest>>,
) -> Result<Json<DeepDiveResponse>, AppError> {
    let req = body.map(|Json(r)| r).unwrap_or_default();
    let test_id_str = req
        .test_id
        .map(|t| t.to_string())
        .unwrap_or_default();

    // VAPT H-1: the Gemini prompt is seeded with the correct answer +
    // canonical explanation, so returning it before the user has been
    // served this question re-introduces the F01 answer leak via a side
    // channel. Require that the caller has an existing `test_responses`
    // row for `(user_id, question_id)` — i.e., the question has been
    // included in one of their tests, and (by F62) they've either
    // finished it or explicitly opted in.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT 1 FROM test_responses \
             WHERE user_id = ?1 AND question_id = ?2 LIMIT 1",
            params![caller.id, qid],
        )
        .await?;
    if rows.next().await?.is_none() {
        return Err(AppError::Forbidden);
    }

    // Cache key is now user-scoped so a leaked cache row can't be
    // replayed to a fresh user before they've attempted the question.
    let cache_key = format!("deep_dive:{}:{qid}:{test_id_str}", caller.id);
    if let Some(body) = load_cache(&state, &cache_key).await? {
        match serde_json::from_str::<DeepDiveResponse>(&body) {
            Ok(mut resp) => {
                resp.cached = true;
                return Ok(Json(resp));
            }
            Err(err) => {
                // Corrupted cache row — log + fall through to regenerate.
                tracing::warn!(
                    error = %err,
                    key = %cache_key,
                    "deep-dive cache row corrupted; regenerating"
                );
            }
        }
    }

    // Load the question so we can build the prompt.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT q.question_text, q.correct_option, q.explanation, \
                    t.name AS topic_name, t.subject AS subject \
               FROM questions q \
               LEFT JOIN topics t ON t.id = q.topic_id \
              WHERE q.id = ? LIMIT 1",
            params![qid],
        )
        .await?;
    let Some(row) = rows.next().await? else {
        return Err(AppError::NotFound("question"));
    };
    // question_text is nullable in the schema — defend against a NULL row.
    let question_text = value_to_opt_string(row.get_value(0)?).ok_or_else(|| {
        AppError::BadRequest("question has no text to analyze".into())
    })?;
    let correct_option = value_to_opt_string(row.get_value(1)?);
    let explanation = value_to_opt_string(row.get_value(2)?);
    let topic_name = value_to_opt_string(row.get_value(3)?);
    let subject = value_to_opt_string(row.get_value(4)?);

    let prompt = gemini::build_prompt(
        &question_text,
        topic_name.as_deref(),
        subject.as_deref(),
        correct_option.as_deref(),
        explanation.as_deref(),
    );

    let text = match gemini::generate(&state.config.llm, &prompt).await {
        Ok(t) => t,
        Err(err) => {
            let error_id = new_error_id();
            tracing::error!(
                "[{error_id}] deep-dive failed for qid={qid} tid={test_id_str}: {err:#}"
            );
            return Err(AppError::Upstream(format!(
                "AI tutor temporarily unavailable. Ref: {error_id}"
            )));
        }
    };

    let parsed = gemini::parse_sections(&text);
    let resp = DeepDiveResponse {
        explanation: parsed.explanation,
        key_facts: parsed.key_facts,
        exam_tips: parsed.exam_tips,
        follow_up_suggestions: parsed.follow_up_suggestions,
        cached: false,
    };

    // Cache write is best-effort — a failure here just means the next
    // request pays the LLM cost again.
    if let Ok(json) = serde_json::to_string(&resp) {
        let _ = state
            .db
            .conn()
            .execute(
                "INSERT OR REPLACE INTO doubt_cache (cache_key, response_json, created_at) \
                 VALUES (?, ?, CURRENT_TIMESTAMP)",
                params![cache_key.clone(), json],
            )
            .await
            .map_err(|e| {
                tracing::warn!(error = %e, key = %cache_key, "failed to write doubt_cache");
                e
            });
    }

    Ok(Json(resp))
}

async fn load_cache(state: &AppState, key: &str) -> Result<Option<String>, AppError> {
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT response_json FROM doubt_cache WHERE cache_key = ? LIMIT 1",
            params![key.to_string()],
        )
        .await?;
    if let Some(row) = rows.next().await? {
        return Ok(Some(row.get::<String>(0)?));
    }
    Ok(None)
}

fn new_error_id() -> String {
    let mut buf = Uuid::new_v4().simple().to_string();
    buf.truncate(8);
    buf
}

/// Helper for building a stable prompt hash (used elsewhere by the
/// synthesize path). Kept here since `sha2` is already in scope.
#[allow(dead_code)]
pub(crate) fn prompt_hash(s: &str) -> String {
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    hex::encode(h.finalize())
}
