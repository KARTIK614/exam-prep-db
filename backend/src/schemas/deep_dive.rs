//! Request / response DTOs for `POST /api/v1/questions/{qid}/deep-dive`.
//!
//! The response mirrors the section headings emitted by the Gemini
//! prompt in `bp_doubt.py::deep_dive` (Concept / Key Facts / Exam Tips /
//! optional Storyline), reshaped for the React FE per the Phase 7 spec:
//!
//!   { explanation, key_facts: [String], exam_tips: [String],
//!     follow_up_suggestions: [String] }
//!
//! `follow_up_suggestions` is new to v3 — hints for the chat UI. If the
//! model doesn't emit them, we fall back to an empty vec.

use serde::{Deserialize, Serialize};

#[derive(Debug, Default, Deserialize)]
pub struct DeepDiveRequest {
    /// Optional link back to the mock_test the doubt was raised from.
    /// Doesn't affect the answer, only cache-key partitioning.
    pub test_id: Option<i64>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DeepDiveResponse {
    pub explanation: String,
    pub key_facts: Vec<String>,
    pub exam_tips: Vec<String>,
    pub follow_up_suggestions: Vec<String>,
    /// `true` when we returned a cached body without re-hitting Gemini.
    pub cached: bool,
}
