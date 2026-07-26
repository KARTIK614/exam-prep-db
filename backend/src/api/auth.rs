//! `/api/v1/auth/*` handlers.
//!
//! Endpoints wired by `api::mod::router`:
//!   POST /auth/register
//!   POST /auth/login
//!   POST /auth/refresh
//!   POST /auth/logout
//!   POST /auth/forgot-password
//!   POST /auth/reset-password/{token}
//!
//! Phase-3 simplification: we store a single sha256(refresh_token) on
//! `users.refresh_token_hash` rather than the full rotation-chain from
//! R4 §2.4. That means refresh works, logout works, but "reuse
//! detection" is best-effort: the second use of a stolen token 401s
//! because we overwrote the hash on the legit user's most-recent
//! refresh. Full chain is a future phase.

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use chrono::{Duration, Utc};
use libsql::params; // brings the `params!` macro into scope via re-export
use validator::Validate;

use crate::api::AppState;
use crate::error::AppError;
use crate::models::User;
use crate::schemas::auth::{
    ForgotPasswordRequest, ForgotPasswordResponse, LoginRequest, LogoutRequest,
    RefreshRequest, RefreshResponse, RegisterRequest, RegisterResponse,
    ResetPasswordRequest, TokenResponse,
};
use crate::services::auth as auth_svc;

// ---------- helpers --------------------------------------------------------

/// Load a user by id. Returns `Ok(None)` when the row is absent so
/// handlers can distinguish "gone" from "db error".
async fn fetch_user_by_id(state: &AppState, id: i64) -> anyhow::Result<Option<User>> {
    let sql = format!(
        "SELECT {} FROM users WHERE id = ?1 LIMIT 1",
        User::COLUMNS.join(", ")
    );
    let mut rows = state.db.conn().query(&sql, params![id]).await?;
    match rows.next().await? {
        Some(row) => Ok(Some(User::from_row(&row)?)),
        None => Ok(None),
    }
}

/// Case-insensitive lookup by either username or email.
async fn fetch_user_by_identifier(
    state: &AppState,
    identifier: &str,
) -> anyhow::Result<Option<User>> {
    let sql = format!(
        "SELECT {} FROM users \
         WHERE lower(username) = lower(?1) OR lower(email) = lower(?1) \
         LIMIT 1",
        User::COLUMNS.join(", ")
    );
    let mut rows = state
        .db
        .conn()
        .query(&sql, params![identifier])
        .await?;
    match rows.next().await? {
        Some(row) => Ok(Some(User::from_row(&row)?)),
        None => Ok(None),
    }
}

/// Bump `users.refresh_token_hash` and `users.last_login`. Passing
/// `Some(hash)` stores a fresh hash; `None` clears the field (logout).
async fn set_refresh_hash(
    state: &AppState,
    user_id: i64,
    hash: Option<&str>,
) -> anyhow::Result<()> {
    match hash {
        Some(h) => {
            state
                .db
                .conn()
                .execute(
                    "UPDATE users SET refresh_token_hash = ?1 WHERE id = ?2",
                    params![h.to_string(), user_id],
                )
                .await?;
        }
        None => {
            state
                .db
                .conn()
                .execute(
                    "UPDATE users SET refresh_token_hash = NULL WHERE id = ?1",
                    params![user_id],
                )
                .await?;
        }
    }
    Ok(())
}

async fn update_last_login(state: &AppState, user_id: i64) -> anyhow::Result<()> {
    let now = Utc::now().to_rfc3339();
    state
        .db
        .conn()
        .execute(
            "UPDATE users SET last_login = ?1 WHERE id = ?2",
            params![now, user_id],
        )
        .await?;
    Ok(())
}

/// Mint access + refresh, persist the refresh-hash, and package them
/// into the standard token payload used by register / login / refresh.
async fn issue_tokens(state: &AppState, user: &User) -> Result<TokenResponse, AppError> {
    let access = auth_svc::mint_access_token(user.id, &user.role, &state.config.jwt.access_secret)
        .map_err(|e| AppError::Internal(format!("mint access: {e}")))?;
    let (refresh, refresh_hash) =
        auth_svc::mint_refresh_token(user.id, &state.config.jwt.refresh_secret)
            .map_err(|e| AppError::Internal(format!("mint refresh: {e}")))?;

    set_refresh_hash(state, user.id, Some(&refresh_hash)).await?;

    Ok(TokenResponse {
        access_token: access,
        refresh_token: refresh,
        user_id: user.id,
        role: user.role.clone(),
    })
}

// ---------- POST /auth/register -------------------------------------------

pub async fn register(
    State(state): State<AppState>,
    Json(req): Json<RegisterRequest>,
) -> Result<impl IntoResponse, AppError> {
    req.validate()
        .map_err(|e| AppError::BadRequest(format!("validation: {e}")))?;

    // Reject username/email collision (case-insensitive).
    let exists_sql = "SELECT id FROM users \
                      WHERE lower(username) = lower(?1) OR lower(email) = lower(?2) \
                      LIMIT 1";
    let mut rows = state
        .db
        .conn()
        .query(exists_sql, params![req.username.clone(), req.email.clone()])
        .await?;
    if rows.next().await?.is_some() {
        return Err(AppError::BadRequest(
            "username or email already registered".into(),
        ));
    }

    let password_hash = auth_svc::hash_password(&req.password)
        .map_err(|e| AppError::Internal(format!("hash password: {e}")))?;

    let now = Utc::now().to_rfc3339();
    // Insert & return the new id via RETURNING (libsql supports it).
    let insert_sql = "INSERT INTO users \
                        (username, email, password_hash, role, is_active, created_at) \
                      VALUES (?1, ?2, ?3, 'user', 1, ?4) \
                      RETURNING id";
    let mut rows = state
        .db
        .conn()
        .query(
            insert_sql,
            params![
                req.username.clone(),
                req.email.clone(),
                password_hash,
                now,
            ],
        )
        .await?;
    let row = rows
        .next()
        .await?
        .ok_or_else(|| AppError::Internal("INSERT ... RETURNING produced no row".into()))?;
    let user_id: i64 = row
        .get::<i64>(0)
        .map_err(|e| AppError::Internal(format!("read new user id: {e}")))?;

    // Fetch full row so `issue_tokens` has the role/other fields.
    let user = fetch_user_by_id(&state, user_id)
        .await?
        .ok_or_else(|| AppError::Internal("newly-inserted user not found".into()))?;

    let tokens = issue_tokens(&state, &user).await?;

    Ok((
        StatusCode::CREATED,
        Json(RegisterResponse {
            user_id: user.id,
            access_token: tokens.access_token,
            refresh_token: tokens.refresh_token,
        }),
    ))
}

// ---------- POST /auth/login ----------------------------------------------

/// Per-user login lockout thresholds (VAPT H-4). We cap consecutive
/// failures at `LOCKOUT_THRESHOLD` and refuse further attempts for
/// `LOCKOUT_MINUTES` regardless of password correctness. This is per
/// username (not per IP) so an attacker rotating IPs still gets locked
/// out after a handful of failed guesses per account.
const LOCKOUT_THRESHOLD: i64 = 5;
const LOCKOUT_MINUTES: i64 = 15;

pub async fn login(
    State(state): State<AppState>,
    Json(req): Json<LoginRequest>,
) -> Result<Json<TokenResponse>, AppError> {
    let user = fetch_user_by_identifier(&state, &req.username_or_email).await?;

    // Uniform error for both "unknown user" and "wrong password" (R4 §2.2).
    let Some(user) = user else {
        return Err(AppError::Unauthorized);
    };
    if !user.is_active {
        return Err(AppError::Unauthorized);
    }

    // Lockout check. `locked_until > now()` → 401 without touching the
    // password hash (also spares us the argon2 CPU cost during an attack).
    if let Some(until) = user.locked_until.as_deref() {
        if let Ok(parsed) = chrono::DateTime::parse_from_rfc3339(until) {
            if parsed.with_timezone(&Utc) > Utc::now() {
                tracing::warn!(
                    user_id = user.id,
                    locked_until = %until,
                    "login refused: account is locked"
                );
                return Err(AppError::Unauthorized);
            }
        }
    }

    let Some(stored_hash) = user.password_hash.as_deref() else {
        return Err(AppError::Unauthorized);
    };
    if !auth_svc::verify_password(&req.password, stored_hash) {
        // Bump the counter; lock if threshold reached.
        let new_count = user.failed_login_count.saturating_add(1);
        if new_count >= LOCKOUT_THRESHOLD {
            let until = (Utc::now() + Duration::minutes(LOCKOUT_MINUTES)).to_rfc3339();
            let _ = state
                .db
                .conn()
                .execute(
                    "UPDATE users SET failed_login_count = ?1, locked_until = ?2 \
                     WHERE id = ?3",
                    params![new_count, until.clone(), user.id],
                )
                .await;
            tracing::warn!(
                user_id = user.id,
                threshold = LOCKOUT_THRESHOLD,
                until = %until,
                "account locked after repeated failed logins"
            );
        } else {
            let _ = state
                .db
                .conn()
                .execute(
                    "UPDATE users SET failed_login_count = ?1 WHERE id = ?2",
                    params![new_count, user.id],
                )
                .await;
        }
        return Err(AppError::Unauthorized);
    }

    // Success — clear failure state.
    let _ = state
        .db
        .conn()
        .execute(
            "UPDATE users SET failed_login_count = 0, locked_until = NULL \
             WHERE id = ?1",
            params![user.id],
        )
        .await;
    update_last_login(&state, user.id).await?;
    let tokens = issue_tokens(&state, &user).await?;
    Ok(Json(tokens))
}

// ---------- POST /auth/refresh --------------------------------------------

pub async fn refresh(
    State(state): State<AppState>,
    Json(req): Json<RefreshRequest>,
) -> Result<Json<RefreshResponse>, AppError> {
    if req.refresh_token.trim().is_empty() {
        return Err(AppError::Unauthorized);
    }
    let hash = auth_svc::hash_refresh_token(&req.refresh_token);

    // Look up by stored hash; if it doesn't match anyone, 401.
    let sql = format!(
        "SELECT {} FROM users WHERE refresh_token_hash = ?1 LIMIT 1",
        User::COLUMNS.join(", ")
    );
    let mut rows = state.db.conn().query(&sql, params![hash]).await?;
    let user = match rows.next().await? {
        Some(row) => User::from_row(&row)?,
        None => return Err(AppError::Unauthorized),
    };
    if !user.is_active {
        return Err(AppError::Unauthorized);
    }

    // Rotate: mint a fresh pair and overwrite the stored hash.
    let tokens = issue_tokens(&state, &user).await?;
    Ok(Json(RefreshResponse {
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
    }))
}

// ---------- POST /auth/logout ---------------------------------------------

/// Clears the stored refresh-token hash for the given refresh token.
/// Idempotent: returns 204 even if the token was already invalid or the
/// caller didn't send one. Body may be empty (`{}`) or absent-shaped.
pub async fn logout(
    State(state): State<AppState>,
    body: Option<Json<LogoutRequest>>,
) -> Result<StatusCode, AppError> {
    let token = body
        .and_then(|Json(b)| b.refresh_token)
        .filter(|t| !t.trim().is_empty());

    if let Some(token) = token {
        let hash = auth_svc::hash_refresh_token(&token);
        // Best-effort: clear the row that matches. If it doesn't exist we
        // still 204 — logout is idempotent by contract.
        state
            .db
            .conn()
            .execute(
                "UPDATE users SET refresh_token_hash = NULL WHERE refresh_token_hash = ?1",
                params![hash],
            )
            .await?;
    }
    Ok(StatusCode::NO_CONTENT)
}

// ---------- POST /auth/forgot-password ------------------------------------

pub async fn forgot_password(
    State(state): State<AppState>,
    Json(req): Json<ForgotPasswordRequest>,
) -> Result<(StatusCode, Json<ForgotPasswordResponse>), AppError> {
    req.validate()
        .map_err(|e| AppError::BadRequest(format!("validation: {e}")))?;

    // Look up by email only.
    let user_sql = format!(
        "SELECT {} FROM users WHERE lower(email) = lower(?1) LIMIT 1",
        User::COLUMNS.join(", ")
    );
    let mut rows = state
        .db
        .conn()
        .query(&user_sql, params![req.email.clone()])
        .await?;

    if let Some(row) = rows.next().await? {
        let user = User::from_row(&row)?;
        let token = auth_svc::generate_reset_token();
        // Store only the sha256 — the plaintext is emailed to the user
        // and never sits in the DB. Anyone with log/DB access thus can't
        // hijack a pending reset (VAPT C-1).
        let token_hash = auth_svc::hash_refresh_token(&token);
        let expires = (Utc::now() + Duration::hours(1)).to_rfc3339();

        state
            .db
            .conn()
            .execute(
                "UPDATE users SET password_reset_token = ?1, \
                                    password_reset_expires_at = ?2 \
                 WHERE id = ?3",
                params![token_hash, expires, user.id],
            )
            .await?;

        // TODO(email): send this via Resend / Postmark once SMTP is wired
        // (see docs/plans/v3-R5-migration-deploy.md). Deliberately do NOT
        // log the plaintext token — VAPT C-1. Ops can trigger a fresh
        // reset locally for a specific email if needed.
        tracing::info!(
            user_id = user.id,
            "password reset requested — token hashed; email delivery pending SMTP wiring"
        );
    } else {
        // Do NOT reveal whether the email exists. Log at debug so
        // operators can still see attempts on unknown addresses.
        tracing::debug!(email = %req.email, "forgot-password for unknown email");
    }

    Ok((
        StatusCode::ACCEPTED,
        Json(ForgotPasswordResponse {
            message: "If that email is registered, a reset link has been sent.".into(),
        }),
    ))
}

// ---------- POST /auth/reset-password/{token} -----------------------------

pub async fn reset_password(
    State(state): State<AppState>,
    Path(token): Path<String>,
    Json(req): Json<ResetPasswordRequest>,
) -> Result<StatusCode, AppError> {
    req.validate()
        .map_err(|e| AppError::BadRequest(format!("validation: {e}")))?;

    // Reset tokens are stored as sha256 hashes (VAPT C-1). The
    // path-parameter carries the plaintext token from the email; hash
    // and compare in constant enough time (SQL equality on a fixed-
    // length hex string is fine).
    let token_hash = auth_svc::hash_refresh_token(&token);
    let sql = format!(
        "SELECT {} FROM users WHERE password_reset_token = ?1 LIMIT 1",
        User::COLUMNS.join(", ")
    );
    let mut rows = state.db.conn().query(&sql, params![token_hash]).await?;
    let user = match rows.next().await? {
        Some(row) => User::from_row(&row)?,
        None => return Err(AppError::BadRequest("invalid or expired reset token".into())),
    };

    // Enforce expiry.
    let expired = match user.password_reset_expires_at.as_deref() {
        Some(iso) => {
            let parsed = chrono::DateTime::parse_from_rfc3339(iso)
                .map(|dt| dt.with_timezone(&Utc))
                .ok();
            match parsed {
                Some(dt) => dt < Utc::now(),
                None => true, // unparseable → treat as expired, don't panic
            }
        }
        None => true,
    };
    if expired {
        return Err(AppError::BadRequest("invalid or expired reset token".into()));
    }

    let new_hash = auth_svc::hash_password(&req.new_password)
        .map_err(|e| AppError::Internal(format!("hash password: {e}")))?;

    // Update password, clear reset fields, and invalidate all existing
    // sessions by clearing the refresh hash.
    state
        .db
        .conn()
        .execute(
            "UPDATE users SET password_hash = ?1, \
                                password_reset_token = NULL, \
                                password_reset_expires_at = NULL, \
                                refresh_token_hash = NULL \
             WHERE id = ?2",
            params![new_hash, user.id],
        )
        .await?;

    Ok(StatusCode::OK)
}
