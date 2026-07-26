//! `error_log` — the SRS/error-review queue.
//!
//! Post-migration:
//!   id, test_id, question_id, topic_id,
//!   selected_option, correct_option, error_type,
//!   root_cause, resolved, created_at,
//!   redo_1_score, redo_2_score,
//!   sr_box, sr_due_at, sr_last_reviewed,
//!   user_id

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{int_to_bool, value_to_opt_f64, value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorLog {
    pub id: i64,
    pub test_id: Option<i64>,
    pub question_id: Option<i64>,
    pub topic_id: Option<i64>,
    pub selected_option: Option<String>,
    pub correct_option: Option<String>,
    pub error_type: Option<String>,
    pub root_cause: Option<String>,
    pub resolved: bool,
    pub created_at: Option<String>,
    pub redo_1_score: Option<f64>,
    pub redo_2_score: Option<f64>,
    pub sr_box: Option<i64>,
    pub sr_due_at: Option<String>,
    pub sr_last_reviewed: Option<String>,
    pub user_id: i64,
}

impl ErrorLog {
    pub const COLUMNS: &'static [&'static str] = &[
        "id",
        "test_id",
        "question_id",
        "topic_id",
        "selected_option",
        "correct_option",
        "error_type",
        "root_cause",
        "resolved",
        "created_at",
        "redo_1_score",
        "redo_2_score",
        "sr_box",
        "sr_due_at",
        "sr_last_reviewed",
        "user_id",
    ];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("error_log.id")?,
            test_id: value_to_opt_i64(row.get_value(1).context("error_log.test_id")?),
            question_id: value_to_opt_i64(
                row.get_value(2).context("error_log.question_id")?,
            ),
            topic_id: value_to_opt_i64(row.get_value(3).context("error_log.topic_id")?),
            selected_option: value_to_opt_string(
                row.get_value(4).context("error_log.selected_option")?,
            ),
            correct_option: value_to_opt_string(
                row.get_value(5).context("error_log.correct_option")?,
            ),
            error_type: value_to_opt_string(
                row.get_value(6).context("error_log.error_type")?,
            ),
            root_cause: value_to_opt_string(
                row.get_value(7).context("error_log.root_cause")?,
            ),
            resolved: int_to_bool(value_to_opt_i64(
                row.get_value(8).context("error_log.resolved")?,
            )),
            created_at: value_to_opt_string(
                row.get_value(9).context("error_log.created_at")?,
            ),
            redo_1_score: value_to_opt_f64(
                row.get_value(10).context("error_log.redo_1_score")?,
            ),
            redo_2_score: value_to_opt_f64(
                row.get_value(11).context("error_log.redo_2_score")?,
            ),
            sr_box: value_to_opt_i64(row.get_value(12).context("error_log.sr_box")?),
            sr_due_at: value_to_opt_string(row.get_value(13).context("error_log.sr_due_at")?),
            sr_last_reviewed: value_to_opt_string(
                row.get_value(14).context("error_log.sr_last_reviewed")?,
            ),
            user_id: row.get::<i64>(15).context("error_log.user_id")?,
        })
    }
}
