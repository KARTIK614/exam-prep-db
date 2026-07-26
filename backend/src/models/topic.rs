//! `topics` — global taxonomy shared across users.
//!
//!   id INTEGER PRIMARY KEY
//!   name TEXT UNIQUE
//!   subject TEXT
//!   paper TEXT
//!   weightage INTEGER DEFAULT 5

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Topic {
    pub id: i64,
    pub name: Option<String>,
    pub subject: Option<String>,
    pub paper: Option<String>,
    pub weightage: Option<i64>,
}

impl Topic {
    pub const COLUMNS: &'static [&'static str] =
        &["id", "name", "subject", "paper", "weightage"];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("topics.id")?,
            name: value_to_opt_string(row.get_value(1).context("topics.name")?),
            subject: value_to_opt_string(row.get_value(2).context("topics.subject")?),
            paper: value_to_opt_string(row.get_value(3).context("topics.paper")?),
            weightage: value_to_opt_i64(row.get_value(4).context("topics.weightage")?),
        })
    }
}
