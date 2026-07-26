//! `mock_tests` — one row per test attempt, scoped to a user.
//!
//! Post-migration schema:
//!   id, started_at, completed_at, paper, total_questions,
//!   score, max_score, time_taken_sec, status, test_mode,
//!   duration_sec, negative_ratio, raw_marks, wrong_count,
//!   unanswered_count,
//!   user_id  (INTEGER NOT NULL DEFAULT 1)

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{value_to_opt_f64, value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MockTest {
    pub id: i64,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub paper: Option<String>,
    pub total_questions: Option<i64>,
    pub score: Option<f64>,
    pub max_score: Option<i64>,
    pub time_taken_sec: Option<i64>,
    pub status: Option<String>,
    pub test_mode: Option<String>,
    pub duration_sec: Option<i64>,
    pub negative_ratio: Option<f64>,
    pub raw_marks: Option<f64>,
    pub wrong_count: Option<i64>,
    pub unanswered_count: Option<i64>,
    pub user_id: i64,
}

impl MockTest {
    pub const COLUMNS: &'static [&'static str] = &[
        "id",
        "started_at",
        "completed_at",
        "paper",
        "total_questions",
        "score",
        "max_score",
        "time_taken_sec",
        "status",
        "test_mode",
        "duration_sec",
        "negative_ratio",
        "raw_marks",
        "wrong_count",
        "unanswered_count",
        "user_id",
    ];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("mock_tests.id")?,
            started_at: value_to_opt_string(
                row.get_value(1).context("mock_tests.started_at")?,
            ),
            completed_at: value_to_opt_string(
                row.get_value(2).context("mock_tests.completed_at")?,
            ),
            paper: value_to_opt_string(row.get_value(3).context("mock_tests.paper")?),
            total_questions: value_to_opt_i64(
                row.get_value(4).context("mock_tests.total_questions")?,
            ),
            score: value_to_opt_f64(row.get_value(5).context("mock_tests.score")?),
            max_score: value_to_opt_i64(row.get_value(6).context("mock_tests.max_score")?),
            time_taken_sec: value_to_opt_i64(
                row.get_value(7).context("mock_tests.time_taken_sec")?,
            ),
            status: value_to_opt_string(row.get_value(8).context("mock_tests.status")?),
            test_mode: value_to_opt_string(row.get_value(9).context("mock_tests.test_mode")?),
            duration_sec: value_to_opt_i64(
                row.get_value(10).context("mock_tests.duration_sec")?,
            ),
            negative_ratio: value_to_opt_f64(
                row.get_value(11).context("mock_tests.negative_ratio")?,
            ),
            raw_marks: value_to_opt_f64(row.get_value(12).context("mock_tests.raw_marks")?),
            wrong_count: value_to_opt_i64(
                row.get_value(13).context("mock_tests.wrong_count")?,
            ),
            unanswered_count: value_to_opt_i64(
                row.get_value(14).context("mock_tests.unanswered_count")?,
            ),
            user_id: row.get::<i64>(15).context("mock_tests.user_id")?,
        })
    }
}
