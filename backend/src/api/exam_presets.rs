//! `GET /api/v1/exam-presets` — hardcoded catalog of one-click exam bundles.
//!
//! Driven by user feedback (see `memory/user_feedback_sujit.md`): students
//! want to pick "SSC CGL mock" and start immediately, not hand-pick topics.
//!
//! Adding a new preset: add a line to `PRESETS()` below and redeploy. Slugs
//! must be URL-safe (kebab-case) and stable — the frontend persists last-
//! used slug to localStorage.
//!
//! Topic IDs correspond to the seed data in `seed.py`:
//!   25 Computer Fundamentals   26 Number Systems       27 MS Office Suite
//!   28 Programming C/C++       29 OOP & Java           30 Python Programming
//!   31 Data Structures         32 Algorithms           33 DBMS & SQL
//!   34 Operating System        35 Computer Networks    36 Network Security
//!   37 Web Technologies        38 System Analysis      39 IoT & Emerging Tech
//!   40 Pedagogy & Teaching     41 Computer Organization 42 AI & Machine Learning
//!
//! Empty `topic_ids` = all Paper II topics.

use axum::extract::State;
use axum::Json;

use crate::api::AppState;
use crate::error::AppError;
use crate::middleware::auth::RequireAuth;
use crate::schemas::exam_presets::{DifficultyMix, ExamPreset, ExamPresetsResponse};

fn presets() -> Vec<ExamPreset> {
    vec![
        ExamPreset {
            slug: "bci",
            name: "BCI — Basic Computer Instructor",
            description: "Rajasthan Basic Computer Instructor full mock. All CS topics, PYQ-preferred.",
            topic_ids: vec![], // all Paper II
            question_count: 100,
            test_mode: "exam",
            neg_marking_preset: "third",
            pyq_only: true,
            difficulty_mix: DifficultyMix { easy: 30, medium: 50, hard: 20 },
            suggested_minutes: 120,
        },
        ExamPreset {
            slug: "rpsc-programmer",
            name: "RPSC Programmer",
            description: "DBMS + OS + Networks + CO + Programming + Algorithms + SAD. 1/3 penalty.",
            topic_ids: vec![28, 29, 31, 32, 33, 34, 35, 38, 41],
            question_count: 100,
            test_mode: "exam",
            neg_marking_preset: "third",
            pyq_only: false,
            difficulty_mix: DifficultyMix { easy: 20, medium: 55, hard: 25 },
            suggested_minutes: 120,
        },
        ExamPreset {
            slug: "ssc-cgl-computer",
            name: "SSC CGL — Computer Section",
            description: "Fundamentals + MS Office + Internet + Networks + Security. 25 Qs, 1/4 penalty.",
            topic_ids: vec![25, 27, 35, 36, 37],
            question_count: 25,
            test_mode: "exam",
            neg_marking_preset: "quarter",
            pyq_only: false,
            difficulty_mix: DifficultyMix { easy: 40, medium: 45, hard: 15 },
            suggested_minutes: 20,
        },
        ExamPreset {
            slug: "gate-cs",
            name: "GATE — Computer Science",
            description: "DS + Algo + DBMS + OS + Networks + CO + Programming. 65 Qs, no negative (MSQs later).",
            topic_ids: vec![28, 29, 31, 32, 33, 34, 35, 41],
            question_count: 65,
            test_mode: "exam",
            neg_marking_preset: "none",
            pyq_only: false,
            difficulty_mix: DifficultyMix { easy: 15, medium: 45, hard: 40 },
            suggested_minutes: 180,
        },
        ExamPreset {
            slug: "ugc-net-cs",
            name: "UGC NET Paper II — Computer Science",
            description: "All Paper II CS topics. 100 Qs, no negative marking.",
            topic_ids: vec![],
            question_count: 100,
            test_mode: "exam",
            neg_marking_preset: "none",
            pyq_only: false,
            difficulty_mix: DifficultyMix { easy: 25, medium: 55, hard: 20 },
            suggested_minutes: 120,
        },
        ExamPreset {
            slug: "warmup",
            name: "Quick Warm-up",
            description: "10 mixed questions in practice mode. Perfect for a 5-minute study break.",
            topic_ids: vec![],
            question_count: 10,
            test_mode: "practice",
            neg_marking_preset: "none",
            pyq_only: false,
            difficulty_mix: DifficultyMix { easy: 50, medium: 40, hard: 10 },
            suggested_minutes: 5,
        },
        ExamPreset {
            slug: "pyq-practice",
            name: "PYQ Practice",
            description: "50 real past-year questions from any exam. Practice mode, immediate feedback.",
            topic_ids: vec![],
            question_count: 50,
            test_mode: "practice",
            neg_marking_preset: "none",
            pyq_only: true,
            difficulty_mix: DifficultyMix { easy: 25, medium: 55, hard: 20 },
            suggested_minutes: 40,
        },
    ]
}

/// GET /api/v1/exam-presets — auth-gated, static list.
pub async fn list_presets(
    _auth: RequireAuth,
    State(_state): State<AppState>,
) -> Result<Json<ExamPresetsResponse>, AppError> {
    Ok(Json(ExamPresetsResponse { items: presets() }))
}
