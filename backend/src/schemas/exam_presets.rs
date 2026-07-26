//! DTOs for `GET /api/v1/exam-presets`.
//!
//! Static list of one-click exam bundle presets. Each preset auto-fills the
//! `TestSetup` form so a student can pick e.g. "SSC CGL Computer" and start
//! without picking topics by hand.
//!
//! Presets are hard-coded (no DB) for v1 — see `api/exam_presets.rs` for the
//! seed list. Adding a new one requires a code change + redeploy, which is
//! fine at solo-dev scale.

use serde::Serialize;

#[derive(Debug, Serialize, Clone)]
pub struct DifficultyMix {
    pub easy: u8,   // percent 0-100
    pub medium: u8,
    pub hard: u8,
}

#[derive(Debug, Serialize, Clone)]
pub struct ExamPreset {
    /// URL-safe slug, e.g. "ssc-cgl-computer". Used in localStorage.
    pub slug: &'static str,
    /// Human-readable name shown on the card.
    pub name: &'static str,
    /// One-line description shown under the name.
    pub description: &'static str,
    /// Topic IDs to pre-select. Empty vec = all Paper II topics.
    pub topic_ids: Vec<i64>,
    pub question_count: u32,
    /// "practice" | "exam".
    pub test_mode: &'static str,
    /// "none" | "third" | "quarter" | "fifth" | "custom".
    pub neg_marking_preset: &'static str,
    pub pyq_only: bool,
    pub difficulty_mix: DifficultyMix,
    /// Suggested time in minutes (display hint only; backend doesn't enforce).
    pub suggested_minutes: u32,
}

#[derive(Debug, Serialize)]
pub struct ExamPresetsResponse {
    pub items: Vec<ExamPreset>,
}
