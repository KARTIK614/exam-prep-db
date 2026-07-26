//! Top-level `AppError` type + `IntoResponse` mapping.
//!
//! Every handler returns `Result<T, AppError>`. `?` conversions come from
//! `#[from]` on the individual variants. The `IntoResponse` impl produces a
//! consistent JSON envelope:
//!
//! ```json
//! { "error": { "code": "not_found", "message": "...", "request_id": "..." } }
//! ```

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;

tokio::task_local! {
    /// Per-request identifier stitched in by the request-id middleware so
    /// `IntoResponse` can echo it into the error envelope. If the caller
    /// never entered a scoped middleware (e.g. background job), reading
    /// returns `None` and the envelope keeps `"request_id": null`.
    pub static REQUEST_ID: String;
}

/// Errors that can propagate out of any handler.
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("bad request: {0}")]
    BadRequest(String),

    #[error("unauthorized")]
    Unauthorized,

    #[error("forbidden")]
    Forbidden,

    #[error("not found: {0}")]
    NotFound(&'static str),

    #[error("conflict: {0}")]
    Conflict(String),

    #[error("too many requests")]
    RateLimited,

    /// A dependency (Turso, LLM provider, ...) failed.
    #[error("upstream unavailable: {0}")]
    Upstream(String),

    /// Wrapped Turso/libsql failure.
    #[error("database error: {0}")]
    Db(String),

    #[error(transparent)]
    Io(#[from] std::io::Error),

    #[error(transparent)]
    Json(#[from] serde_json::Error),

    /// Catch-all for anything we didn't classify.
    #[error("internal: {0}")]
    Internal(String),

    /// Escape hatch for early plumbing — swallow an `anyhow::Error`.
    #[error(transparent)]
    Any(#[from] anyhow::Error),
}

impl From<libsql::Error> for AppError {
    fn from(err: libsql::Error) -> Self {
        AppError::Db(err.to_string())
    }
}

impl AppError {
    fn parts(&self) -> (StatusCode, &'static str) {
        match self {
            AppError::BadRequest(_) => (StatusCode::BAD_REQUEST, "bad_request"),
            AppError::Unauthorized => (StatusCode::UNAUTHORIZED, "unauthorized"),
            AppError::Forbidden => (StatusCode::FORBIDDEN, "forbidden"),
            AppError::NotFound(_) => (StatusCode::NOT_FOUND, "not_found"),
            AppError::Conflict(_) => (StatusCode::CONFLICT, "conflict"),
            AppError::RateLimited => (StatusCode::TOO_MANY_REQUESTS, "rate_limited"),
            AppError::Upstream(_) => (StatusCode::BAD_GATEWAY, "upstream_unavailable"),
            AppError::Db(_)
            | AppError::Io(_)
            | AppError::Json(_)
            | AppError::Internal(_)
            | AppError::Any(_) => (StatusCode::INTERNAL_SERVER_ERROR, "internal"),
        }
    }

    /// Public-safe message. For 5xx we never surface the wrapped error text.
    fn public_message(&self) -> String {
        match self {
            AppError::BadRequest(msg) | AppError::Conflict(msg) | AppError::Upstream(msg) => {
                msg.clone()
            }
            AppError::Unauthorized => "unauthorized".to_string(),
            AppError::Forbidden => "forbidden".to_string(),
            AppError::NotFound(what) => format!("not found: {what}"),
            AppError::RateLimited => "too many requests".to_string(),
            AppError::Db(_)
            | AppError::Io(_)
            | AppError::Json(_)
            | AppError::Internal(_)
            | AppError::Any(_) => "internal server error".to_string(),
        }
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, code) = self.parts();

        // Log the full error server-side; only expose the safe message.
        if status.is_server_error() {
            tracing::error!(error = %self, status = %status, "handler error");
        } else {
            tracing::warn!(error = %self, status = %status, "handler error");
        }

        // Echo the request id into the envelope when the request-id
        // middleware scoped this task. Falls back to `null` outside a
        // request (e.g. background jobs, unit tests).
        let request_id = REQUEST_ID
            .try_with(|v| v.clone())
            .ok()
            .map(serde_json::Value::from)
            .unwrap_or(serde_json::Value::Null);
        let body = Json(json!({
            "error": {
                "code": code,
                "message": self.public_message(),
                "request_id": request_id,
            }
        }));

        (status, body).into_response()
    }
}
