//! Request / response DTOs for the `/api/v1/admin/*` endpoints.
//!
//! Grouped by resource in the same order as the module tree:
//!   * questions          — CRUD + bulk-toggle
//!   * users              — list + patch (role / is_active)
//!   * flags              — queue + resolve actions
//!   * duplicates         — pair listing + resolve
//!   * review             — mid-confidence review queue
//!   * uploads            — PDF upload lifecycle
//!   * synthesize         — LLM question generation
//!
//! Everything here is admin-gated at the route layer.

use serde::{Deserialize, Serialize};

use crate::models::{Question, User};

// ============ Questions ====================================================

#[derive(Debug, Deserialize)]
pub struct AdminQuestionCreateRequest {
    pub topic_id: Option<i64>,
    pub question_text: String,
    pub option_a: String,
    pub option_b: String,
    pub option_c: String,
    pub option_d: String,
    /// Single-letter A|B|C|D. Coerced to uppercase server-side.
    pub correct_option: String,
    pub explanation: Option<String>,
    pub difficulty: Option<String>,
    pub source: Option<String>,
    pub confidence: Option<String>,
    pub section: Option<String>,
    pub sub_topic: Option<String>,
    pub pyq_exam: Option<String>,
    pub pyq_year: Option<i64>,
    pub review_notes: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
pub struct AdminQuestionPatchRequest {
    pub topic_id: Option<i64>,
    pub question_text: Option<String>,
    pub option_a: Option<String>,
    pub option_b: Option<String>,
    pub option_c: Option<String>,
    pub option_d: Option<String>,
    pub correct_option: Option<String>,
    pub explanation: Option<String>,
    pub difficulty: Option<String>,
    pub source: Option<String>,
    pub confidence: Option<String>,
    pub section: Option<String>,
    pub sub_topic: Option<String>,
    pub pyq_exam: Option<String>,
    pub pyq_year: Option<i64>,
    pub review_notes: Option<String>,
    pub disabled: Option<bool>,
}

#[derive(Debug, Serialize)]
pub struct AdminQuestionResponse {
    pub question: Question,
}

#[derive(Debug, Deserialize)]
pub struct BulkToggleDisabledRequest {
    pub ids: Vec<i64>,
    pub disabled: bool,
}

#[derive(Debug, Serialize)]
pub struct BulkToggleDisabledResponse {
    pub updated: usize,
    pub disabled: bool,
}

// ============ Users ========================================================

#[derive(Debug, Default, Deserialize)]
pub struct AdminUserListQuery {
    pub cursor: Option<String>,
    pub limit: Option<u32>,
}

#[derive(Debug, Serialize)]
pub struct AdminUserListResponse {
    pub items: Vec<User>,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
pub struct AdminUserPatchRequest {
    /// One of `"admin" | "user"`.
    pub role: Option<String>,
    pub is_active: Option<bool>,
}

// ============ Flags ========================================================

#[derive(Debug, Default, Deserialize)]
pub struct AdminFlagListQuery {
    /// `open | resolved | dismissed | all`. Defaults to `open`.
    pub status: Option<String>,
    pub cursor: Option<String>,
    pub limit: Option<u32>,
}

/// Denormalised flag row with the linked question preview inline —
/// mirrors what `bp_admin.py::flags` streams into its template.
#[derive(Debug, Serialize)]
pub struct AdminFlagRow {
    pub id: i64,
    pub question_id: Option<i64>,
    pub test_id: Option<i64>,
    pub reporter: Option<String>,
    pub user_id: Option<i64>,
    pub category: Option<String>,
    pub note: Option<String>,
    pub status: Option<String>,
    pub created_at: Option<String>,
    pub resolved_at: Option<String>,
    pub question_text: Option<String>,
    pub option_a: Option<String>,
    pub option_b: Option<String>,
    pub option_c: Option<String>,
    pub option_d: Option<String>,
    pub correct_option: Option<String>,
    pub topic_name: Option<String>,
    pub question_disabled: bool,
}

#[derive(Debug, Serialize)]
pub struct AdminFlagListResponse {
    pub items: Vec<AdminFlagRow>,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct AdminFlagActionResponse {
    pub ok: bool,
    /// Only populated when `action == "disable_question"`.
    pub question_id_disabled: Option<i64>,
}

// ============ Duplicates ===================================================

#[derive(Debug, Default, Deserialize)]
pub struct AdminDuplicateQuery {
    pub limit: Option<u32>,
    /// Optional Jaccard floor. Defaults to `0.7`, clamped `[0.5, 1.0]`.
    pub threshold: Option<f64>,
}

#[derive(Debug, Serialize)]
pub struct DuplicatePair {
    pub q1: Question,
    pub q2: Question,
    pub jaccard: f64,
    /// Trigram-intersection size (used server-side to prune noise).
    pub isize: i64,
    pub n1: i64,
    pub n2: i64,
    /// Auto-heuristic recommendation (PYQ > confidence high > longer
    /// explanation > newer updated_at). See `keep_better_of` (ported
    /// from Flask).
    pub suggested_keep: i64,
    pub suggested_disable: i64,
    pub q1_refs: i64,
    pub q2_refs: i64,
}

#[derive(Debug, Serialize)]
pub struct AdminDuplicateListResponse {
    pub pairs: Vec<DuplicatePair>,
    pub threshold: f64,
    pub total_trigrams: i64,
}

#[derive(Debug, Deserialize)]
pub struct AdminDuplicateResolveRequest {
    pub keeper_id: i64,
    pub loser_id: i64,
}

#[derive(Debug, Serialize)]
pub struct AdminDuplicateResolveResponse {
    pub keeper_id: i64,
    pub loser_id: i64,
    pub disabled: bool,
}

// ============ Review queue =================================================

#[derive(Debug, Default, Deserialize)]
pub struct AdminReviewQuery {
    /// `all | medium | has_notes | synthetic | deferred`.
    pub filter: Option<String>,
    pub cursor: Option<String>,
    pub limit: Option<u32>,
}

#[derive(Debug, Serialize)]
pub struct AdminReviewListResponse {
    pub items: Vec<Question>,
    pub next_cursor: Option<String>,
    pub counts: AdminReviewCounts,
}

#[derive(Debug, Default, Serialize)]
pub struct AdminReviewCounts {
    pub medium: i64,
    pub has_notes: i64,
    pub synthetic: i64,
    pub deferred: i64,
    pub non_high: i64,
}

#[derive(Debug, Deserialize)]
pub struct AdminReviewActionRequest {
    /// One of: `confirm | edit | disable | defer`.
    pub action: String,
    /// Field-level patch — only honoured when `action == "edit"`.
    pub patch: Option<AdminQuestionPatchRequest>,
}

#[derive(Debug, Serialize)]
pub struct AdminReviewActionResponse {
    pub ok: bool,
    pub confidence: Option<String>,
    pub disabled: Option<bool>,
}

// ============ Uploads ======================================================

#[derive(Debug, Serialize)]
pub struct AdminUploadRow {
    pub id: i64,
    pub filename: Option<String>,
    pub uploaded_by: Option<String>,
    pub uploaded_at: Option<String>,
    pub topic_id: Option<i64>,
    pub topic_name: Option<String>,
    pub status: Option<String>,
    pub num_extracted: Option<i64>,
    pub num_imported: Option<i64>,
    pub model: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct AdminUploadListResponse {
    pub items: Vec<AdminUploadRow>,
}

#[derive(Debug, Serialize)]
pub struct AdminUploadCreateResponse {
    pub upload_id: i64,
    pub filename: String,
    pub status: String,
}

#[derive(Debug, Deserialize)]
pub struct AdminUploadImportRequest {
    /// Row-indices into the extracted-question preview list.
    pub selected_indices: Vec<u32>,
}

#[derive(Debug, Serialize)]
pub struct AdminUploadImportResponse {
    pub imported: usize,
    pub imported_question_ids: Vec<i64>,
    pub status: String,
}

#[derive(Debug, Serialize)]
pub struct AdminUploadExtractResponse {
    pub upload_id: i64,
    pub status: String,
    pub note: String,
}

// ============ Synthesize ===================================================

#[derive(Debug, Deserialize)]
pub struct AdminSynthesizeRequest {
    pub topic_id: i64,
    pub n_requested: u32,
    /// Optional freeform sub-topic guidance, passed straight through to
    /// the LLM prompt.
    pub sub_topics: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct AdminSynthesizeResponse {
    pub batch_id: i64,
    pub topic_id: i64,
    pub n_requested: u32,
    pub status: String,
    /// Non-empty when the pre-flight cap-check rejected the request.
    pub cap_message: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct AdminSynthesizeStatusResponse {
    pub batch_id: i64,
    pub topic_id: Option<i64>,
    pub topic_name: Option<String>,
    pub model: Option<String>,
    pub status: Option<String>,
    pub n_requested: Option<i64>,
    pub n_generated: Option<i64>,
    pub n_pending: Option<i64>,
    pub notes: Option<String>,
    pub preview: Vec<Question>,
}

#[derive(Debug, Serialize)]
pub struct AdminSynthesizeCommitResponse {
    pub batch_id: i64,
    pub activated: i64,
    pub status: String,
}
