//! `RequireAuth` / `RequireAdmin` axum extractors.
//!
//! Handlers that need the caller's identity take `RequireAuth` (or
//! `RequireAdmin`) as an argument; axum runs the extractor before the
//! handler and short-circuits with a 401/403 on failure.
//!
//! Access tokens live in the `Authorization: Bearer <jwt>` header. The
//! JWT is verified against `Config.jwt.access_secret`.

use axum::extract::FromRequestParts;
use axum::http::request::Parts;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;

use crate::api::AppState;
use crate::services::auth as auth_svc;

/// Identity attached to the request after successful auth.
#[derive(Debug, Clone)]
pub struct AuthUser {
    pub id: i64,
    pub role: String,
}

/// Extractor: any authenticated user.
#[derive(Debug, Clone)]
pub struct RequireAuth(pub AuthUser);

/// Extractor: authenticated user with `role == "admin"`.
#[derive(Debug, Clone)]
pub struct RequireAdmin(pub AuthUser);

// ---------- FromRequestParts ------------------------------------------------

impl FromRequestParts<AppState> for RequireAuth {
    type Rejection = AuthRejection;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let user = extract_auth_user(parts, state)?;
        // Stash into request extensions so downstream handlers/log spans
        // can read `AuthUser` without re-parsing the header.
        parts.extensions.insert(user.clone());
        Ok(RequireAuth(user))
    }
}

impl FromRequestParts<AppState> for RequireAdmin {
    type Rejection = AuthRejection;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let user = extract_auth_user(parts, state)?;
        if user.role != "admin" {
            return Err(AuthRejection::Forbidden);
        }
        parts.extensions.insert(user.clone());
        Ok(RequireAdmin(user))
    }
}

fn extract_auth_user(parts: &Parts, state: &AppState) -> Result<AuthUser, AuthRejection> {
    let header = parts
        .headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .ok_or(AuthRejection::MissingHeader)?;

    let token = header
        .strip_prefix("Bearer ")
        .or_else(|| header.strip_prefix("bearer "))
        .ok_or(AuthRejection::MalformedHeader)?
        .trim();

    if token.is_empty() {
        return Err(AuthRejection::MalformedHeader);
    }

    let claims = auth_svc::verify_token(token, &state.config.jwt.access_secret)
        .map_err(|_| AuthRejection::InvalidToken)?;

    Ok(AuthUser {
        id: claims.user_id,
        role: claims.role,
    })
}

// ---------- Rejection type --------------------------------------------------

/// Reasons an auth extractor can fail. Mapped to the standard error
/// envelope on `IntoResponse`.
#[derive(Debug, Clone)]
pub enum AuthRejection {
    MissingHeader,
    MalformedHeader,
    InvalidToken,
    Forbidden,
}

impl IntoResponse for AuthRejection {
    fn into_response(self) -> Response {
        let (status, code, message) = match self {
            AuthRejection::MissingHeader => (
                StatusCode::UNAUTHORIZED,
                "unauthenticated",
                "Authorization header required",
            ),
            AuthRejection::MalformedHeader => (
                StatusCode::UNAUTHORIZED,
                "unauthenticated",
                "Authorization header must be `Bearer <token>`",
            ),
            AuthRejection::InvalidToken => (
                StatusCode::UNAUTHORIZED,
                "unauthenticated",
                "Access token is invalid or expired",
            ),
            AuthRejection::Forbidden => (
                StatusCode::FORBIDDEN,
                "admin_required",
                "Admin role required",
            ),
        };

        let body = Json(json!({
            "error": {
                "code": code,
                "message": message,
                "request_id": null,
            }
        }));
        (status, body).into_response()
    }
}
