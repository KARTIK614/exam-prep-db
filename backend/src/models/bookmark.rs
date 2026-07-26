//! `bookmarks` — user-flagged questions to revisit.
//!
//! Post-migration UNIQUE index is (user_id, question_id).
//!
//! Schema:
//!   id, question_id, created_at, note, user_id

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bookmark {
    pub id: i64,
    pub question_id: Option<i64>,
    pub created_at: Option<String>,
    pub note: Option<String>,
    pub user_id: i64,
}

impl Bookmark {
    pub const COLUMNS: &'static [&'static str] =
        &["id", "question_id", "created_at", "note", "user_id"];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("bookmarks.id")?,
            question_id: value_to_opt_i64(row.get_value(1).context("bookmarks.question_id")?),
            created_at: value_to_opt_string(row.get_value(2).context("bookmarks.created_at")?),
            note: value_to_opt_string(row.get_value(3).context("bookmarks.note")?),
            user_id: row.get::<i64>(4).context("bookmarks.user_id")?,
        })
    }
}
