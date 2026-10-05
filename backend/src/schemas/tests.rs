//! Request / response DTOs for the test-taking API surface
//! (`/api/v1/tests/*`).
//!
//! Semantics preserved from the Flask blueprint `bp_tests.py`, with the
//! session-cookie state moved onto the `mock_tests` / `test_responses`
//! rows themselves so a client can resume-after-refresh. See
//! `docs/plans/v3-R4-api-auth.md` §3.4 and §3.5 for the wire contract.
//!
//! These DTOs are used by handlers in `api::tests`. All numeric ids are
//! `i64` to line up with SQLite's INTEGER PRIMARY KEY convention.

use serde::{Deserialize, Serialize};

// ---------- POST /tests ----------------------------------------------------

/// Request body for `POST /tests`. Mirrors the Flask setup form fields
/// plus the negative-marking preset.
///
/// `test_mode` ∈ {"practice","exam"}. `difficulty` ∈ {"easy","medium","hard"}.
/// `neg_marking_preset` ∈ {"none","third","quarter","fifth","custom"}. When
/// `test_mode == "practice"` the negative-marking fields are ignored (score
/// is always raw accuracy without penalty in practice mode).
#[derive(Debug, Deserialize)]
pub struct CreateTestRequest {
    /// Explicit topic ids to include. Empty = all topics.
    #[serde(default)]
    pub topic_ids: Vec<i64>,

    /// Number of questions to include. Server clamps to 1..=200 and to
    /// however many rows match the filter set.
    pub question_count: u32,

    /// "practice" or "exam". Anything else 400s.
    pub test_mode: String,

    #[serde(default)]
    pub pyq_only: Option<bool>,
    #[serde(default)]
    pub pyq_year_min: Option<i32>,
    #[serde(default)]
    pub pyq_year_max: Option<i32>,

    /// "easy" | "medium" | "hard". Absent = any difficulty.
    #[serde(default)]
    pub difficulty: Option<String>,

    /// "none" | "third" | "quarter" | "fifth" | "custom". Absent =
    /// "third" (BCI/RPSC default) when `test_mode == "exam"`, otherwise
    /// forced to 0.
    #[serde(default)]
    pub neg_marking_preset: Option<String>,

    /// Only consulted when `neg_marking_preset == "custom"`. Clamped
    /// into [0.0, 1.0].
    #[serde(default)]
    pub neg_marking_ratio: Option<f64>,

    /// Full-paper mode (e.g. `GATE2024_CS_S1`): every question of that
    /// paper, in paper order. Overrides `topic_ids`, `question_count` and
    /// the PYQ / difficulty filters.
    #[serde(default)]
    pub paper_code: Option<String>,
}

/// Response from `POST /tests`. Deliberately narrow so the FE can start
/// rendering immediately; the full question payload comes from
/// `GET /tests/{id}`.
#[derive(Debug, Serialize)]
pub struct CreateTestResponse {
    pub test_id: i64,
    pub question_ids: Vec<i64>,
    pub test_mode: String,
    pub negative_ratio: f64,
}

// ---------- GET /tests/{id} -----------------------------------------------

/// One question in the resume payload. Fields chosen to be the minimum
/// set the FE needs to render the test-taking screen without a second
/// round-trip.
#[derive(Debug, Serialize)]
pub struct TestQuestion {
    pub id: i64,
    pub question_text: Option<String>,
    pub option_a: Option<String>,
    pub option_b: Option<String>,
    pub option_c: Option<String>,
    pub option_d: Option<String>,
    pub order_index: i64,
    /// "MCQ" | "MSQ" | "NAT".
    pub qtype: String,
    pub marks: f64,
    /// Set for questions shown as an image (official papers keep their
    /// maths and diagrams exactly as printed).
    pub image_url: Option<String>,
    /// Exam section, e.g. "GA" / "CS" / "DA".
    pub paper_section: Option<String>,
    pub q_number: Option<i64>,
}

/// One response row in the resume payload.
#[derive(Debug, Serialize)]
pub struct TestResponseSnapshot {
    pub question_id: i64,
    pub selected_option: Option<String>,
    pub marked_for_review: bool,
    pub visit_count: i64,
    pub time_spent_sec: Option<f64>,
    /// "sure" | "unsure" | "guess"; None until the student picks one.
    pub confidence: Option<String>,
    pub note: Option<String>,
}

/// GET /tests/{id} — full resume payload.
#[derive(Debug, Serialize)]
pub struct TestStateResponse {
    pub test_id: i64,
    pub test_mode: String,
    pub negative_ratio: f64,
    pub started_at: Option<String>,
    pub questions: Vec<TestQuestion>,
    pub responses: Vec<TestResponseSnapshot>,
    /// "in_progress" | "completed" | "abandoned".
    pub status: String,
    /// Set when the test is a full paper.
    pub paper_code: Option<String>,
}

// ---------- POST /tests/{id}/answers --------------------------------------

/// Request body for `POST /tests/{id}/answers`. Preserves the Flask
/// semantics: sending the same body twice is a no-op except for
/// visit_count, which increments each time so we can distinguish
/// "reviewed once" from "kept coming back".
#[derive(Debug, Deserialize)]
pub struct SubmitAnswerRequest {
    pub question_id: i64,
    /// `null` clears the selection (e.g. user tapped "Clear Response").
    /// Otherwise MCQ "A"|"B"|"C"|"D", MSQ letters like "A;C", NAT a number.
    #[serde(default)]
    pub selected_option: Option<String>,
    pub marked_for_review: bool,
    /// Wall-clock time spent on this question in seconds. Sent by the FE
    /// on every autosave; we accept a float so client-side timers can
    /// aggregate sub-second increments.
    pub time_spent_sec: f64,
    /// "sure" | "unsure" | "guess".
    #[serde(default)]
    pub confidence: Option<String>,
    /// One line on why this answer was chosen (max 500 chars).
    #[serde(default)]
    pub note: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct SubmitAnswerResponse {
    pub status: &'static str,
}

// ---------- POST /tests/{id}/mark-for-review ------------------------------

/// Standalone toggle for the palette's "mark for review" button. Kept
/// separate from the answer submission for FE convenience.
#[derive(Debug, Deserialize)]
pub struct MarkForReviewRequest {
    pub question_id: i64,
    pub marked: bool,
}

#[derive(Debug, Serialize)]
pub struct MarkForReviewResponse {
    pub status: &'static str,
}

// ---------- PATCH /tests/{id}/responses/{question_id} ---------------------

/// Edit the note on one answer. Allowed after the test is finished,
/// because the reasoning is often written on the results page.
#[derive(Debug, Deserialize)]
pub struct UpdateNoteRequest {
    #[serde(default)]
    pub note: Option<String>,
}

// ---------- POST /tests/{id}/finish ---------------------------------------

/// Per-topic breakdown in the finish + results payloads.
#[derive(Debug, Serialize, Clone)]
pub struct TopicBreakdownRow {
    pub topic_id: Option<i64>,
    pub topic_name: Option<String>,
    pub correct: i64,
    pub total: i64,
    pub accuracy_pct: f64,
}

/// Return shape for both `POST /tests/{id}/finish` and
/// `GET /tests/{id}/results` (idempotent variant).
#[derive(Debug, Serialize)]
pub struct FinishResponse {
    pub test_id: i64,
    pub correct: i64,
    pub wrong: i64,
    pub unanswered: i64,
    pub score_pct: f64,
    pub raw_marks: f64,
    /// Sum of question marks (equals the question count for 1-mark tests).
    pub max_marks: f64,
    pub negative_ratio: f64,
    pub breakdown_by_topic: Vec<TopicBreakdownRow>,
}

// ---------- GET /tests (history) ------------------------------------------

/// Query params for `GET /tests` — the caller's test history.
#[derive(Debug, Default, Deserialize)]
pub struct TestListQuery {
    /// Restrict to "in_progress" or "completed" (anything else = both).
    #[serde(default)]
    pub status: Option<String>,
    /// Opaque cursor from the previous page's `next_cursor`.
    #[serde(default)]
    pub cursor: Option<String>,
    /// Page size (default 20, capped at 100).
    #[serde(default)]
    pub limit: Option<u32>,
}

/// Row shape for `GET /tests`. `computed_grade` is a purely-cosmetic
/// letter grade derived from `score_pct` — nice-to-have but the FE can
/// also compute it. We compute it server-side so it's stable across
/// clients.
#[derive(Debug, Serialize)]
pub struct TestHistoryItem {
    pub id: i64,
    pub test_mode: Option<String>,
    pub status: Option<String>,
    pub total_questions: Option<i64>,
    pub score: Option<f64>,
    pub raw_marks: Option<f64>,
    pub wrong_count: Option<i64>,
    pub unanswered_count: Option<i64>,
    pub negative_ratio: Option<f64>,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub time_taken_sec: Option<i64>,
    /// "A" | "B" | "C" | "D" | "F". `None` when the test isn't complete.
    pub computed_grade: Option<&'static str>,
    pub paper_code: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct TestListResponse {
    pub items: Vec<TestHistoryItem>,
    pub next_cursor: Option<String>,
}

// ---------- GET /tests/{id}/results ---------------------------------------

/// Per-question row on the results page.
#[derive(Debug, Serialize)]
pub struct ResultsQuestionRow {
    pub question_id: i64,
    pub question_text: Option<String>,
    pub selected_option: Option<String>,
    pub correct_option: Option<String>,
    pub is_correct: bool,
    pub explanation: Option<String>,
    pub time_spent_sec: Option<f64>,
    pub topic_name: Option<String>,
    pub option_a: Option<String>,
    pub option_b: Option<String>,
    pub option_c: Option<String>,
    pub option_d: Option<String>,
    pub qtype: String,
    pub marks: f64,
    pub marks_awarded: Option<f64>,
    pub image_url: Option<String>,
    pub paper_section: Option<String>,
    pub q_number: Option<i64>,
    pub confidence: Option<String>,
    pub note: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ResultsResponse {
    #[serde(flatten)]
    pub finish: FinishResponse,
    pub questions: Vec<ResultsQuestionRow>,
}

// ---------- GET /papers ---------------------------------------------------

/// One full paper available for a paper-mode test.
#[derive(Debug, Serialize)]
pub struct PaperSummary {
    pub paper_code: String,
    pub question_count: i64,
    pub max_marks: f64,
    /// Exam sections in this paper, e.g. ["CS", "GA"].
    pub sections: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct PapersResponse {
    pub papers: Vec<PaperSummary>,
}
