//! `/api/v1/me/settings` — user-adjacent settings.
//!
//! For v3 first launch the `settings` table is still shared/global.
//! We expose the two keys the UI cares about (target_seconds_per_q,
//! target_score) as a flat JSON object; the PATCH endpoint writes them
//! back via INSERT OR REPLACE. When per-user settings land we'll
//! namespace by user_id — the DTO shape stays the same.

use axum::extract::State;
use axum::Json;
use libsql::params;
use serde::{Deserialize, Serialize};

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct SettingsPayload {
    pub target_seconds_per_q: Option<i64>,
    pub target_score: Option<i64>,
}

pub async fn get_settings(
    State(state): State<AppState>,
    RequireAuth(_auth): RequireAuth,
) -> Result<Json<SettingsPayload>, AppError> {
    let mut payload = SettingsPayload::default();
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT key, value FROM settings WHERE key IN ('target_seconds_per_q','target_score')",
            (),
        )
        .await?;
    while let Some(row) = rows.next().await? {
        let key: String = row.get(0)?;
        let value: String = row.get(1)?;
        match key.as_str() {
            "target_seconds_per_q" => payload.target_seconds_per_q = value.parse().ok(),
            "target_score" => payload.target_score = value.parse().ok(),
            _ => {}
        }
    }
    Ok(Json(payload))
}

pub async fn patch_settings(
    State(state): State<AppState>,
    RequireAuth(_auth): RequireAuth,
    Json(req): Json<SettingsPayload>,
) -> Result<Json<SettingsPayload>, AppError> {
    if let Some(t) = req.target_seconds_per_q {
        let t = t.clamp(15, 600);
        state
            .db
            .conn()
            .execute(
                "INSERT INTO settings (key, value) VALUES ('target_seconds_per_q', ?) \
                 ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                params![t.to_string()],
            )
            .await?;
    }
    if let Some(s) = req.target_score {
        let s = s.clamp(0, 100);
        state
            .db
            .conn()
            .execute(
                "INSERT INTO settings (key, value) VALUES ('target_score', ?) \
                 ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                params![s.to_string()],
            )
            .await?;
    }
    // Return refreshed view inline.
    let mut payload = SettingsPayload::default();
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT key, value FROM settings WHERE key IN ('target_seconds_per_q','target_score')",
            (),
        )
        .await?;
    while let Some(row) = rows.next().await? {
        let key: String = row.get(0)?;
        let value: String = row.get(1)?;
        match key.as_str() {
            "target_seconds_per_q" => payload.target_seconds_per_q = value.parse().ok(),
            "target_score" => payload.target_score = value.parse().ok(),
            _ => {}
        }
    }
    Ok(Json(payload))
}
