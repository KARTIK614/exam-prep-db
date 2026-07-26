//! `/api/v1/me` — profile read + patch.
//!
//! Both handlers require `RequireAuth`; the middleware puts the caller's
//! `AuthUser` into request extensions and passes it as a tuple field of
//! the extractor. See `middleware::auth`.

use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use libsql::params;
use validator::Validate;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::models::User;
use crate::schemas::auth::{MeResponse, UpdateMeRequest};
use crate::services::auth as auth_svc;

async fn load_me(state: &AppState, user_id: i64) -> Result<User, AppError> {
    let sql = format!(
        "SELECT {} FROM users WHERE id = ?1 LIMIT 1",
        User::COLUMNS.join(", ")
    );
    let mut rows = state.db.conn().query(&sql, params![user_id]).await?;
    let row = rows
        .next()
        .await?
        .ok_or(AppError::NotFound("user"))?;
    User::from_row(&row).map_err(AppError::from)
}

fn to_response(user: &User) -> MeResponse {
    MeResponse {
        id: user.id,
        username: user.username.clone(),
        email: user.email.clone(),
        role: user.role.clone(),
        created_at: user.created_at.clone(),
        last_login: user.last_login.clone(),
    }
}

// ---------- GET /me --------------------------------------------------------

pub async fn get_me(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
) -> Result<Json<MeResponse>, AppError> {
    let user = load_me(&state, auth.id).await?;
    Ok(Json(to_response(&user)))
}

// ---------- PATCH /me ------------------------------------------------------

pub async fn patch_me(
    State(state): State<AppState>,
    RequireAuth(auth): RequireAuth,
    Json(req): Json<UpdateMeRequest>,
) -> Result<(StatusCode, Json<MeResponse>), AppError> {
    req.validate()
        .map_err(|e| AppError::BadRequest(format!("validation: {e}")))?;

    let user = load_me(&state, auth.id).await?;

    // If the caller is changing the password they MUST prove ownership.
    if let Some(new_pw) = req.new_password.as_deref() {
        let current = req
            .current_password
            .as_deref()
            .ok_or_else(|| AppError::BadRequest("current_password required".into()))?;
        let stored = user
            .password_hash
            .as_deref()
            .ok_or_else(|| AppError::BadRequest("account has no password set".into()))?;
        if !auth_svc::verify_password(current, stored) {
            return Err(AppError::Unauthorized);
        }
        let new_hash = auth_svc::hash_password(new_pw)
            .map_err(|e| AppError::Internal(format!("hash password: {e}")))?;
        state
            .db
            .conn()
            .execute(
                "UPDATE users SET password_hash = ?1 WHERE id = ?2",
                params![new_hash, user.id],
            )
            .await?;
    }

    if let Some(email) = req.email.as_deref() {
        // VAPT M-1: an attacker with a 15-min stolen access token could
        // previously PATCH the email to their own address and then
        // trigger /auth/forgot-password to seize the account
        // permanently. Require the caller to prove ownership by
        // supplying `current_password` alongside the new email — same
        // gate we already apply to password changes above.
        //
        // If the caller also changed their password in this request the
        // ownership proof has already been consumed; we still re-verify
        // against the *pre-change* stored hash below because we loaded
        // `user` before that write.
        let current = req
            .current_password
            .as_deref()
            .ok_or_else(|| AppError::BadRequest("current_password required to change email".into()))?;
        let stored = user
            .password_hash
            .as_deref()
            .ok_or_else(|| AppError::BadRequest("account has no password set".into()))?;
        if !auth_svc::verify_password(current, stored) {
            return Err(AppError::Unauthorized);
        }

        // Reject if that address already belongs to a different user.
        let mut rows = state
            .db
            .conn()
            .query(
                "SELECT id FROM users \
                 WHERE lower(email) = lower(?1) AND id <> ?2 LIMIT 1",
                params![email.to_string(), user.id],
            )
            .await?;
        if rows.next().await?.is_some() {
            return Err(AppError::Conflict("email already registered".into()));
        }
        state
            .db
            .conn()
            .execute(
                "UPDATE users SET email = ?1 WHERE id = ?2",
                params![email.to_string(), user.id],
            )
            .await?;
    }

    let refreshed = load_me(&state, user.id).await?;
    Ok((StatusCode::OK, Json(to_response(&refreshed))))
}
