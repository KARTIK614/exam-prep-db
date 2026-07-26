//! Pure crypto/token primitives used by the auth API.
//!
//! No axum, no HTTP, no database. Handlers call these; middleware calls
//! `verify_token`. Kept dependency-light so unit tests can exercise the
//! crypto without spinning up the world.

use anyhow::{anyhow, Context};
use argon2::password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString};
use argon2::{Algorithm, Argon2, Params, Version};
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use chrono::{Duration, Utc};
use jsonwebtoken::{
    decode, encode, DecodingKey, EncodingKey, Header, TokenData, Validation,
};
use rand::rngs::OsRng;
use rand::RngCore;
use secrecy::{ExposeSecret, SecretString};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Argon2id parameters per OWASP 2025 baseline.
///
/// `m = 19456 KiB (~19 MiB), t = 2, p = 1`.
///
/// These are the numbers spelled out in R4 §2.5 and in the phase-3 task
/// spec. Do NOT lower without a matching migration for existing hashes.
const ARGON2_M_COST: u32 = 19_456;
const ARGON2_T_COST: u32 = 2;
const ARGON2_P_COST: u32 = 1;

const ACCESS_TOKEN_TTL_MIN: i64 = 15;
/// 30-day refresh token TTL. Not enforced yet because Phase 3's opaque-
/// refresh-in-users-row model has no per-token issuance time — every
/// rotation overwrites the previous hash. When R4 §2.4's full
/// `refresh_tokens` table lands, this constant drives the `expires_at`
/// column at insert time.
#[allow(dead_code)]
const REFRESH_TOKEN_TTL_DAYS: i64 = 30;

/// JWT claims for the access token. Refresh tokens are opaque and are
/// verified against the sha256 hash stored on `users.refresh_token_hash`,
/// so they don't need a claim struct.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Claims {
    /// Subject — user id as a string (JWT convention).
    pub sub: String,
    /// Duplicate of `sub` as an int; convenient for handlers.
    pub user_id: i64,
    /// `"user"` or `"admin"`.
    pub role: String,
    /// Issued-at (unix seconds).
    pub iat: i64,
    /// Expiry (unix seconds).
    pub exp: i64,
    /// Issuer — pinned to `"exam-prep-api"` so tokens from other systems
    /// signed with the same key still fail validation.
    pub iss: String,
    /// Audience — pinned to `"exam-prep-web"`.
    pub aud: String,
}

/// Hash a plain-text password with Argon2id.
///
/// The returned string is the full PHC-format hash
/// (`$argon2id$v=19$m=19456,t=2,p=1$<salt>$<hash>`) suitable for direct
/// storage in `users.password_hash`.
pub fn hash_password(plain: &str) -> anyhow::Result<String> {
    let salt = SaltString::generate(&mut OsRng);
    let params = Params::new(ARGON2_M_COST, ARGON2_T_COST, ARGON2_P_COST, None)
        .map_err(|e| anyhow!("argon2 params: {e}"))?;
    let argon2 = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);
    let hash = argon2
        .hash_password(plain.as_bytes(), &salt)
        .map_err(|e| anyhow!("argon2 hash_password: {e}"))?;
    Ok(hash.to_string())
}

/// Constant-time verify a plaintext password against a stored PHC hash.
///
/// Returns `false` on any error (bad hash format, mismatch, ...) so a
/// caller cannot distinguish "wrong password" from "corrupt hash" —
/// preserves the login-error uniformity R4 §2.2 requires.
pub fn verify_password(plain: &str, stored_hash: &str) -> bool {
    let Ok(parsed) = PasswordHash::new(stored_hash) else {
        return false;
    };
    Argon2::default()
        .verify_password(plain.as_bytes(), &parsed)
        .is_ok()
}

/// Mint a 15-minute HS256 JWT for the given user.
pub fn mint_access_token(
    user_id: i64,
    role: &str,
    secret: &SecretString,
) -> anyhow::Result<String> {
    let now = Utc::now();
    let exp = now + Duration::minutes(ACCESS_TOKEN_TTL_MIN);
    let claims = Claims {
        sub: user_id.to_string(),
        user_id,
        role: role.to_string(),
        iat: now.timestamp(),
        exp: exp.timestamp(),
        iss: "exam-prep-api".to_string(),
        aud: "exam-prep-web".to_string(),
    };

    let token = encode(
        &Header::default(),
        &claims,
        &EncodingKey::from_secret(secret.expose_secret().as_bytes()),
    )
    .context("encoding JWT")?;
    Ok(token)
}

/// Mint an opaque 30-day refresh token.
///
/// Returns `(plaintext_token, sha256_hex_hash)`. The caller stores the
/// hash in `users.refresh_token_hash`; the plaintext is returned to the
/// client and never persisted server-side.
///
/// The `secret` argument is currently unused because the refresh token
/// is opaque (256 bits of CSPRNG output, base64url-encoded), *not* a
/// JWT. It is threaded through the signature so we can later swap the
/// implementation for a signed JWT variant without breaking callers.
pub fn mint_refresh_token(
    _user_id: i64,
    _secret: &SecretString,
) -> anyhow::Result<(String, String)> {
    // 32 bytes = 256 bits of entropy; url-safe base64 without padding
    // gives ~43 ASCII chars, cookie-safe and header-safe.
    let mut buf = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut buf);
    let token = URL_SAFE_NO_PAD.encode(buf);
    let hash = hash_refresh_token(&token);
    Ok((token, hash))
}

/// Verify an access-token JWT. Returns the decoded claims on success.
pub fn verify_token(token: &str, secret: &SecretString) -> anyhow::Result<Claims> {
    let mut validation = Validation::new(jsonwebtoken::Algorithm::HS256);
    validation.set_audience(&["exam-prep-web"]);
    validation.set_issuer(&["exam-prep-api"]);
    // `exp` validation is on by default.

    let data: TokenData<Claims> = decode::<Claims>(
        token,
        &DecodingKey::from_secret(secret.expose_secret().as_bytes()),
        &validation,
    )
    .context("decoding JWT")?;
    Ok(data.claims)
}

/// Deterministic sha256(hex) of a refresh token. Used both when minting
/// (to compute the stored hash) and when verifying (to compare against
/// the persisted hash).
pub fn hash_refresh_token(token: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(token.as_bytes());
    hex::encode(hasher.finalize())
}

/// Generate a 32-byte url-safe reset token for the forgot-password flow.
/// Returned as the plaintext string; store the sha256 (via
/// `hash_refresh_token`, same primitive) in `users.password_reset_token`
/// alongside a `password_reset_expires_at` timestamp.
pub fn generate_reset_token() -> String {
    let mut buf = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut buf);
    URL_SAFE_NO_PAD.encode(buf)
}
