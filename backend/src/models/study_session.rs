//! `study_sessions` — one row per journalled study block.
//!
//! Schema:
//!   id, date, topic_id, duration_min, mcqs_solved, score, notes, user_id

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{value_to_opt_f64, value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StudySession {
    pub id: i64,
    pub date: Option<String>,
    pub topic_id: Option<i64>,
    pub duration_min: Option<i64>,
    pub mcqs_solved: Option<i64>,
    pub score: Option<f64>,
    pub notes: Option<String>,
    pub user_id: i64,
}

impl StudySession {
    pub const COLUMNS: &'static [&'static str] = &[
        "id",
        "date",
        "topic_id",
        "duration_min",
        "mcqs_solved",
        "score",
        "notes",
        "user_id",
    ];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("study_sessions.id")?,
            date: value_to_opt_string(row.get_value(1).context("study_sessions.date")?),
            topic_id: value_to_opt_i64(
                row.get_value(2).context("study_sessions.topic_id")?,
            ),
            duration_min: value_to_opt_i64(
                row.get_value(3).context("study_sessions.duration_min")?,
            ),
            mcqs_solved: value_to_opt_i64(
                row.get_value(4).context("study_sessions.mcqs_solved")?,
            ),
            score: value_to_opt_f64(row.get_value(5).context("study_sessions.score")?),
            notes: value_to_opt_string(row.get_value(6).context("study_sessions.notes")?),
            user_id: row.get::<i64>(7).context("study_sessions.user_id")?,
        })
    }
}
