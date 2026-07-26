//! `topic_mastery` — per-user, per-topic progress score.
//!
//! After the v3 migration we rely on the composite UNIQUE
//! (`idx_topic_mastery_user_topic`) for `(user_id, topic_id)`. Note that
//! the legacy table-level UNIQUE on `topic_id` is still present in the
//! schema — since we only ever had user 1's data there's no conflict
//! yet, and rebuilding the table is deferred until after cutover.
//!
//! Schema:
//!   id, topic_id, diagnostic_score, current_score,
//!   study_hours, status, last_studied, test_count,
//!   user_id

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{value_to_opt_f64, value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TopicMastery {
    pub id: i64,
    pub topic_id: Option<i64>,
    pub diagnostic_score: Option<f64>,
    pub current_score: Option<f64>,
    pub study_hours: Option<f64>,
    pub status: Option<String>,
    pub last_studied: Option<String>,
    pub test_count: Option<i64>,
    pub user_id: i64,
}

impl TopicMastery {
    pub const COLUMNS: &'static [&'static str] = &[
        "id",
        "topic_id",
        "diagnostic_score",
        "current_score",
        "study_hours",
        "status",
        "last_studied",
        "test_count",
        "user_id",
    ];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("topic_mastery.id")?,
            topic_id: value_to_opt_i64(row.get_value(1).context("topic_mastery.topic_id")?),
            diagnostic_score: value_to_opt_f64(
                row.get_value(2).context("topic_mastery.diagnostic_score")?,
            ),
            current_score: value_to_opt_f64(
                row.get_value(3).context("topic_mastery.current_score")?,
            ),
            study_hours: value_to_opt_f64(
                row.get_value(4).context("topic_mastery.study_hours")?,
            ),
            status: value_to_opt_string(row.get_value(5).context("topic_mastery.status")?),
            last_studied: value_to_opt_string(
                row.get_value(6).context("topic_mastery.last_studied")?,
            ),
            test_count: value_to_opt_i64(
                row.get_value(7).context("topic_mastery.test_count")?,
            ),
            user_id: row.get::<i64>(8).context("topic_mastery.user_id")?,
        })
    }
}
