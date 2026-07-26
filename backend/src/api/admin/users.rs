//! Admin user management.
//!
//! Endpoints:
//!   GET   /api/v1/admin/users
//!   PATCH /api/v1/admin/users/{id}    -- role / is_active
//!
//! Safety rail: refuses to demote / deactivate the last active admin, so
//! the operator can't accidentally lock themselves out over API.

use axum::extract::{Path, Query, State};
use axum::Json;
use libsql::params;

use crate::api::pagination::{clamp_limit, decode_cursor, next_cursor};
use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAdmin;
use crate::models::User;
use crate::schemas::admin::{
    AdminUserListQuery, AdminUserListResponse, AdminUserPatchRequest,
};

// ---------- GET /admin/users -----------------------------------------------

pub async fn list_users(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Query(q): Query<AdminUserListQuery>,
) -> Result<Json<AdminUserListResponse>, AppError> {
    let limit = clamp_limit(q.limit);
    let after_id = decode_cursor(q.cursor.as_deref())?;

    let cols = User::COLUMNS.join(", ");
    let mut sql = format!("SELECT {cols} FROM users");
    let mut vals: Vec<libsql::Value> = Vec::new();
    if let Some(id) = after_id {
        sql.push_str(" WHERE id > ?");
        vals.push(libsql::Value::Integer(id));
    }
    sql.push_str(" ORDER BY id ASC LIMIT ?");
    vals.push(libsql::Value::Integer(limit as i64));

    let mut rows = state.db.conn().query(&sql, vals).await?;
    let mut items: Vec<User> = Vec::with_capacity(limit as usize);
    while let Some(row) = rows.next().await? {
        items.push(User::from_row(&row)?);
    }

    let last_id = items.last().map(|u| u.id);
    Ok(Json(AdminUserListResponse {
        next_cursor: next_cursor(last_id, items.len(), limit),
        items,
    }))
}

// ---------- PATCH /admin/users/{id} ----------------------------------------

pub async fn patch_user(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Path(id): Path<i64>,
    Json(patch): Json<AdminUserPatchRequest>,
) -> Result<Json<User>, AppError> {
    if patch.role.is_none() && patch.is_active.is_none() {
        return Err(AppError::BadRequest("empty patch".into()));
    }
    if let Some(role) = patch.role.as_deref() {
        if !matches!(role, "admin" | "user") {
            return Err(AppError::BadRequest(
                "role must be one of admin|user".into(),
            ));
        }
    }

    // Load current row so the safety-rail check can compare state.
    let existing = load_user(&state, id).await?;

    // Anti-lockout: if we're about to demote OR deactivate an admin, count
    // the remaining active admins other than this user. If it's zero we
    // refuse.
    let demoting = patch.role.as_deref() == Some("user") && existing.role == "admin";
    let deactivating = patch.is_active == Some(false) && existing.is_active;
    if (demoting || deactivating) && existing.role == "admin" {
        let mut rows = state
            .db
            .conn()
            .query(
                "SELECT COUNT(*) FROM users \
                  WHERE id <> ? AND role = 'admin' AND is_active = 1",
                params![id],
            )
            .await?;
        let count: i64 = match rows.next().await? {
            Some(row) => row.get::<i64>(0)?,
            None => 0,
        };
        if count == 0 {
            return Err(AppError::Conflict(
                "cannot demote or deactivate the last active admin".into(),
            ));
        }
    }

    let mut set: Vec<String> = Vec::new();
    let mut vals: Vec<libsql::Value> = Vec::new();
    if let Some(role) = patch.role {
        set.push("role = ?".into());
        vals.push(libsql::Value::Text(role));
    }
    if let Some(active) = patch.is_active {
        set.push("is_active = ?".into());
        vals.push(libsql::Value::Integer(if active { 1 } else { 0 }));
    }
    let sql = format!("UPDATE users SET {} WHERE id = ?", set.join(", "));
    vals.push(libsql::Value::Integer(id));
    state.db.conn().execute(&sql, vals).await?;

    let updated = load_user(&state, id).await?;
    Ok(Json(updated))
}

async fn load_user(state: &AppState, id: i64) -> Result<User, AppError> {
    let cols = User::COLUMNS.join(", ");
    let sql = format!("SELECT {cols} FROM users WHERE id = ? LIMIT 1");
    let mut rows = state.db.conn().query(&sql, params![id]).await?;
    match rows.next().await? {
        Some(row) => Ok(User::from_row(&row)?),
        None => Err(AppError::NotFound("user")),
    }
}
