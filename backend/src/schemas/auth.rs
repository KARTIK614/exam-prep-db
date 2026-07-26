//! Auth-endpoint request/response DTOs.
//!
//! Kept in sync with `docs/plans/v3-R4-api-auth.md` §3.1. Deviations from
//! the plan document are noted inline — the main one is that this phase
//! ships a *simplified* refresh model: we store a single sha256 hash of
//! the current refresh token on `users.refresh_token_hash` rather than a
//! full rotation-chain in a separate `refresh_tokens` table. Reuse
//! detection is therefore best-effort (a leaked token stops working the
//! instant the legit user refreshes) rather than the full-chain revoke
//! described in R4 §2.4. Full rotation chain is a future phase.

use serde::{Deserialize, Serialize};
use validator::Validate;

// -------- Register ---------------------------------------------------------

#[derive(Debug, Deserialize, Validate)]
pub struct RegisterRequest {
    #[validate(length(min = 3, max = 64))]
    pub username: String,

    #[validate(email)]
    pub email: String,

    #[validate(length(min = 8, max = 256))]
    pub password: String,

    /// Optional human-friendly display name. Phase 3 stores this under
    /// `users.username` unless we later extend the schema; we accept it
    /// on the wire for FE convenience but do not persist it separately.
    pub name: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct RegisterResponse {
    pub user_id: i64,
    pub access_token: String,
    pub refresh_token: String,
}

// -------- Login ------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct LoginRequest {
    /// Email OR username — the login handler tries each.
    pub username_or_email: String,
    pub password: String,
}

#[derive(Debug, Serialize)]
pub struct TokenResponse {
    pub access_token: String,
    pub refresh_token: String,
    pub user_id: i64,
    pub role: String,
}

// -------- Refresh ----------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct RefreshRequest {
    pub refresh_token: String,
}

/// Logout may run with or without a refresh token in hand — a client that
/// lost the token still wants to be able to invalidate its session.
/// The refresh-token field is therefore optional.
#[derive(Debug, Deserialize, Default)]
#[serde(default)]
pub struct LogoutRequest {
    pub refresh_token: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct RefreshResponse {
    pub access_token: String,
    pub refresh_token: String,
}

// -------- Forgot / reset password -----------------------------------------

#[derive(Debug, Deserialize, Validate)]
pub struct ForgotPasswordRequest {
    #[validate(email)]
    pub email: String,
}

#[derive(Debug, Serialize)]
pub struct ForgotPasswordResponse {
    /// Always the same message regardless of whether the email exists;
    /// prevents user enumeration.
    pub message: String,
}

#[derive(Debug, Deserialize, Validate)]
pub struct ResetPasswordRequest {
    #[validate(length(min = 8, max = 256))]
    pub new_password: String,
}

// -------- Me / profile -----------------------------------------------------

#[derive(Debug, Serialize)]
pub struct MeResponse {
    pub id: i64,
    pub username: String,
    pub email: Option<String>,
    pub role: String,
    pub created_at: Option<String>,
    pub last_login: Option<String>,
}

#[derive(Debug, Deserialize, Validate)]
pub struct UpdateMeRequest {
    #[validate(email)]
    pub email: Option<String>,

    /// Required when `new_password` is set — proves possession of the
    /// existing account.
    pub current_password: Option<String>,

    #[validate(length(min = 8, max = 256))]
    pub new_password: Option<String>,
}
