//! `test_responses` — one row per (test, question) attempt.
//!
//! Post-migration:
//!   id, test_id, question_id, selected_option, is_correct,
//!   time_spent_sec, confidence, error_type,
//!   marked_for_review, visit_count,
//!   user_id

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{int_to_bool, value_to_opt_f64, value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestResponse {
    pub id: i64,
    pub test_id: Option<i64>,
    pub question_id: Option<i64>,
    pub selected_option: Option<String>,
    pub is_correct: bool,
    pub time_spent_sec: Option<f64>,
    pub confidence: Option<String>,
    pub error_type: Option<String>,
    pub marked_for_review: bool,
    pub visit_count: Option<i64>,
    pub user_id: i64,
}

impl TestResponse {
    pub const COLUMNS: &'static [&'static str] = &[
        "id",
        "test_id",
        "question_id",
        "selected_option",
        "is_correct",
        "time_spent_sec",
        "confidence",
        "error_type",
        "marked_for_review",
        "visit_count",
        "user_id",
    ];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("test_responses.id")?,
            test_id: value_to_opt_i64(row.get_value(1).context("test_responses.test_id")?),
            question_id: value_to_opt_i64(
                row.get_value(2).context("test_responses.question_id")?,
            ),
            selected_option: value_to_opt_string(
                row.get_value(3).context("test_responses.selected_option")?,
            ),
            is_correct: int_to_bool(value_to_opt_i64(
                row.get_value(4).context("test_responses.is_correct")?,
            )),
            time_spent_sec: value_to_opt_f64(
                row.get_value(5).context("test_responses.time_spent_sec")?,
            ),
            confidence: value_to_opt_string(
                row.get_value(6).context("test_responses.confidence")?,
            ),
            error_type: value_to_opt_string(
                row.get_value(7).context("test_responses.error_type")?,
            ),
            marked_for_review: int_to_bool(value_to_opt_i64(
                row.get_value(8).context("test_responses.marked_for_review")?,
            )),
            visit_count: value_to_opt_i64(
                row.get_value(9).context("test_responses.visit_count")?,
            ),
            user_id: row.get::<i64>(10).context("test_responses.user_id")?,
        })
    }
}
