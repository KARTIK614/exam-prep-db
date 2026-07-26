//! `users` — application accounts.
//!
//! Post-v3-Phase-2 schema:
//!   id INTEGER PRIMARY KEY AUTOINCREMENT
//!   username TEXT UNIQUE NOT NULL
//!   password_hash TEXT              -- nullable while a user is being seeded
//!   role TEXT DEFAULT 'user'
//!   is_active INTEGER DEFAULT 1
//!   created_at TEXT DEFAULT CURRENT_TIMESTAMP
//!   last_login TEXT
//!   email TEXT                      -- added in v3 phase 2
//!   email_verified_at TEXT          -- added in v3 phase 2
//!   password_reset_token TEXT       -- added in v3 phase 2
//!   password_reset_expires_at TEXT  -- added in v3 phase 2
//!   refresh_token_hash TEXT         -- added in v3 phase 2

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{int_to_bool, value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id: i64,
    pub username: String,
    /// Never leak the hash outside the auth layer.
    #[serde(skip_serializing)]
    pub password_hash: Option<String>,
    pub role: String,
    pub is_active: bool,
    pub created_at: Option<String>,
    pub last_login: Option<String>,
    pub email: Option<String>,
    pub email_verified_at: Option<String>,
    #[serde(skip_serializing)]
    pub password_reset_token: Option<String>,
    pub password_reset_expires_at: Option<String>,
    #[serde(skip_serializing)]
    pub refresh_token_hash: Option<String>,
    /// Consecutive failed-login attempts since the last successful login
    /// (VAPT H-4). Reset to 0 on any successful login.
    #[serde(skip_serializing)]
    pub failed_login_count: i64,
    /// ISO-8601 timestamp until which login is refused with 401, even
    /// on a correct password. Cleared on any successful login.
    #[serde(skip_serializing)]
    pub locked_until: Option<String>,
}

impl User {
    /// SELECT list ordered to match `from_row` below. Callers should
    /// reuse this to build queries so schema changes stay in sync.
    pub const COLUMNS: &'static [&'static str] = &[
        "id",
        "username",
        "password_hash",
        "role",
        "is_active",
        "created_at",
        "last_login",
        "email",
        "email_verified_at",
        "password_reset_token",
        "password_reset_expires_at",
        "refresh_token_hash",
        "failed_login_count",
        "locked_until",
    ];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("users.id")?,
            username: row.get::<String>(1).context("users.username")?,
            password_hash: value_to_opt_string(
                row.get_value(2).context("users.password_hash")?,
            ),
            role: row.get::<String>(3).context("users.role")?,
            is_active: int_to_bool(value_to_opt_i64(
                row.get_value(4).context("users.is_active")?,
            )),
            created_at: value_to_opt_string(row.get_value(5).context("users.created_at")?),
            last_login: value_to_opt_string(row.get_value(6).context("users.last_login")?),
            email: value_to_opt_string(row.get_value(7).context("users.email")?),
            email_verified_at: value_to_opt_string(
                row.get_value(8).context("users.email_verified_at")?,
            ),
            password_reset_token: value_to_opt_string(
                row.get_value(9).context("users.password_reset_token")?,
            ),
            password_reset_expires_at: value_to_opt_string(
                row.get_value(10).context("users.password_reset_expires_at")?,
            ),
            refresh_token_hash: value_to_opt_string(
                row.get_value(11).context("users.refresh_token_hash")?,
            ),
            failed_login_count: value_to_opt_i64(
                row.get_value(12).context("users.failed_login_count")?,
            )
            .unwrap_or(0),
            locked_until: value_to_opt_string(row.get_value(13).context("users.locked_until")?),
        })
    }
}
