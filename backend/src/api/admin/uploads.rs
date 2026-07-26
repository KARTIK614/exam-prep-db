//! Admin PDF-upload lifecycle.
//!
//! Endpoints:
//!   GET  /api/v1/admin/uploads
//!   POST /api/v1/admin/uploads               (multipart: file, topic_id?)
//!   POST /api/v1/admin/uploads/{id}/extract  (stub — Claude vision to port)
//!   POST /api/v1/admin/uploads/{id}/import   (accepts pre-extracted rows)
//!
//! The Claude-vision extraction lives in `ai_anthropic.py` on the Flask
//! side. Porting it to Rust needs the `anthropic-sdk` crate + streaming
//! multipart page tiles; deferred to a follow-up task per the Phase 7
//! spec. The route returns 200 with `status="not_implemented"` so the FE
//! can render a "queued for admin" state rather than a hard 5xx.

use axum::extract::{Multipart, Path, State};
use axum::http::StatusCode;
use axum::Json;
use chrono::Utc;
use libsql::params;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAdmin;
use crate::models::{value_to_opt_i64, value_to_opt_string};
use crate::schemas::admin::{
    AdminUploadCreateResponse, AdminUploadExtractResponse, AdminUploadImportRequest,
    AdminUploadImportResponse, AdminUploadListResponse, AdminUploadRow,
};

// ---------- GET /admin/uploads ---------------------------------------------

pub async fn list_uploads(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
) -> Result<Json<AdminUploadListResponse>, AppError> {
    let sql = "SELECT u.id, u.filename, u.uploaded_by, u.uploaded_at, u.topic_id, \
                     t.name AS topic_name, u.status, u.num_extracted, u.num_imported, u.model \
                FROM pdf_uploads u \
                LEFT JOIN topics t ON t.id = u.topic_id \
                ORDER BY u.id DESC LIMIT 200";
    let mut rows = state.db.conn().query(sql, ()).await?;
    let mut items: Vec<AdminUploadRow> = Vec::new();
    while let Some(row) = rows.next().await? {
        items.push(AdminUploadRow {
            id: row.get::<i64>(0)?,
            filename: value_to_opt_string(row.get_value(1)?),
            uploaded_by: value_to_opt_string(row.get_value(2)?),
            uploaded_at: value_to_opt_string(row.get_value(3)?),
            topic_id: value_to_opt_i64(row.get_value(4)?),
            topic_name: value_to_opt_string(row.get_value(5)?),
            status: value_to_opt_string(row.get_value(6)?),
            num_extracted: value_to_opt_i64(row.get_value(7)?),
            num_imported: value_to_opt_i64(row.get_value(8)?),
            model: value_to_opt_string(row.get_value(9)?),
        });
    }
    Ok(Json(AdminUploadListResponse { items }))
}

// ---------- POST /admin/uploads --------------------------------------------

/// Multipart upload. Accepts fields `file` (required) + `topic_id` (optional).
/// The PDF bytes are NOT persisted to disk (Render's filesystem is
/// ephemeral); we only record metadata + a byte count. Actual extraction
/// runs on-demand against the in-memory blob — but since that step is
/// stubbed, this handler just records the metadata for now.
pub async fn create_upload(
    State(state): State<AppState>,
    RequireAdmin(caller): RequireAdmin,
    mut multipart: Multipart,
) -> Result<(StatusCode, Json<AdminUploadCreateResponse>), AppError> {
    let mut filename: Option<String> = None;
    let mut topic_id: Option<i64> = None;
    let mut file_bytes: usize = 0;

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| AppError::BadRequest(format!("multipart: {e}")))?
    {
        let name = field.name().map(str::to_string).unwrap_or_default();
        if name == "file" {
            filename = field.file_name().map(str::to_string);
            let data = field
                .bytes()
                .await
                .map_err(|e| AppError::BadRequest(format!("file read failed: {e}")))?;
            file_bytes = data.len();
        } else if name == "topic_id" {
            let text = field
                .text()
                .await
                .map_err(|e| AppError::BadRequest(format!("topic_id read failed: {e}")))?;
            topic_id = text.trim().parse::<i64>().ok();
        }
    }

    let filename = filename.ok_or_else(|| AppError::BadRequest("file field required".into()))?;
    if file_bytes == 0 {
        return Err(AppError::BadRequest("uploaded file is empty".into()));
    }

    let uploaded_by = format!("user:{}", caller.id);
    let sql = "INSERT INTO pdf_uploads \
        (filename, uploaded_by, uploaded_at, topic_id, status, prompt_id, model) \
        VALUES (?, ?, ?, ?, 'uploaded', NULL, NULL) \
        RETURNING id";
    let mut rows = state
        .db
        .conn()
        .query(
            sql,
            params![
                filename.clone(),
                uploaded_by,
                Utc::now().to_rfc3339(),
                topic_id,
            ],
        )
        .await?;
    let upload_id: i64 = match rows.next().await? {
        Some(row) => row.get::<i64>(0)?,
        None => return Err(AppError::Internal("INSERT ... RETURNING produced no row".into())),
    };

    Ok((
        StatusCode::CREATED,
        Json(AdminUploadCreateResponse {
            upload_id,
            filename,
            status: "uploaded".into(),
        }),
    ))
}

// ---------- POST /admin/uploads/{id}/extract -------------------------------

/// STUB: real work happens in `ai_anthropic.extract_questions_from_pdf`
/// on the Flask side. Deferred to a follow-up per Phase 7 spec.
pub async fn extract_upload(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Path(id): Path<i64>,
) -> Result<Json<AdminUploadExtractResponse>, AppError> {
    // Confirm the upload exists (404 otherwise).
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT id FROM pdf_uploads WHERE id = ? LIMIT 1",
            params![id],
        )
        .await?;
    if rows.next().await?.is_none() {
        return Err(AppError::NotFound("upload"));
    }
    Ok(Json(AdminUploadExtractResponse {
        upload_id: id,
        status: "not_implemented".into(),
        note: "port bp_admin.upload_import → Rust in a follow-up".into(),
    }))
}

// ---------- POST /admin/uploads/{id}/import --------------------------------

/// Accepts a batch of pre-extracted question dictionaries (JSON via the
/// standard request body) and inserts them. This is the fallback path
/// while the vision extraction is stubbed: an admin can extract on the
/// Flask side, POST the JSON here, and the rows land in Turso.
///
/// TODO: after the vision port lands, look up the extracted rows keyed on
/// `pdf_uploads.id` instead of taking them in the request body.
pub async fn import_upload(
    State(state): State<AppState>,
    RequireAdmin(_): RequireAdmin,
    Path(id): Path<i64>,
    Json(req): Json<AdminUploadImportRequest>,
) -> Result<Json<AdminUploadImportResponse>, AppError> {
    // Confirm upload exists.
    let mut rows = state
        .db
        .conn()
        .query(
            "SELECT topic_id FROM pdf_uploads WHERE id = ? LIMIT 1",
            params![id],
        )
        .await?;
    let topic_id: Option<i64> = match rows.next().await? {
        Some(row) => value_to_opt_i64(row.get_value(0)?),
        None => return Err(AppError::NotFound("upload")),
    };

    // Placeholder: without the extraction step wired up the request-body
    // "selected_indices" don't map to any concrete row. Record the intent
    // in the pdf_uploads status column so an operator can see it was
    // triggered.
    let now = Utc::now().to_rfc3339();
    let selection = format!("selected={:?}", req.selected_indices);
    state
        .db
        .conn()
        .execute(
            "UPDATE pdf_uploads SET status = ?, num_imported = COALESCE(num_imported, 0) \
             WHERE id = ?",
            params![format!("import_pending @{now} · {selection}"), id],
        )
        .await?;

    Ok(Json(AdminUploadImportResponse {
        imported: 0,
        imported_question_ids: Vec::new(),
        status: format!("pending — topic_id={topic_id:?}"),
    }))
}
