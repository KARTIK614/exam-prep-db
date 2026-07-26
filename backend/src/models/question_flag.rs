//! `question_flags` — user-reported issues on a question.
//!
//! Kept the legacy `reporter TEXT` (username string) alongside the new
//! `user_id INTEGER` during the coexistence window. Rust code writes
//! `user_id`; the Python app that still writes `reporter` is on its way
//! out.
//!
//! Schema:
//!   id, question_id, test_id, reporter, category, note,
//!   status, created_at, resolved_at, user_id

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuestionFlag {
    pub id: i64,
    pub question_id: Option<i64>,
    pub test_id: Option<i64>,
    pub reporter: Option<String>,
    pub category: Option<String>,
    pub note: Option<String>,
    pub status: Option<String>,
    pub created_at: Option<String>,
    pub resolved_at: Option<String>,
    pub user_id: i64,
}

impl QuestionFlag {
    pub const COLUMNS: &'static [&'static str] = &[
        "id",
        "question_id",
        "test_id",
        "reporter",
        "category",
        "note",
        "status",
        "created_at",
        "resolved_at",
        "user_id",
    ];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("question_flags.id")?,
            question_id: value_to_opt_i64(
                row.get_value(1).context("question_flags.question_id")?,
            ),
            test_id: value_to_opt_i64(row.get_value(2).context("question_flags.test_id")?),
            reporter: value_to_opt_string(
                row.get_value(3).context("question_flags.reporter")?,
            ),
            category: value_to_opt_string(
                row.get_value(4).context("question_flags.category")?,
            ),
            note: value_to_opt_string(row.get_value(5).context("question_flags.note")?),
            status: value_to_opt_string(row.get_value(6).context("question_flags.status")?),
            created_at: value_to_opt_string(
                row.get_value(7).context("question_flags.created_at")?,
            ),
            resolved_at: value_to_opt_string(
                row.get_value(8).context("question_flags.resolved_at")?,
            ),
            user_id: row.get::<i64>(9).context("question_flags.user_id")?,
        })
    }
}
