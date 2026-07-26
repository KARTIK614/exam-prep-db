//! Liveness/health endpoint.
//!
//! `GET /health` returns 200 with `{status: "ok", turso: "ok"}` after
//! pinging the Turso backend. If the ping fails we return 503 with
//! `{status: "degraded", turso: "unreachable"}` — Render's health check
//! will interpret that as unhealthy and stop routing traffic.

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use serde_json::json;

use crate::api::AppState;

pub async fn health(State(state): State<AppState>) -> impl IntoResponse {
    match state.db.ping().await {
        Ok(()) => (
            StatusCode::OK,
            Json(json!({ "status": "ok", "turso": "ok" })),
        )
            .into_response(),
        Err(err) => {
            tracing::warn!(error = %err, "turso health-check ping failed");
            (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({ "status": "degraded", "turso": "unreachable" })),
            )
                .into_response()
        }
    }
}
