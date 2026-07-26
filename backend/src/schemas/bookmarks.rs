//! Request / response DTOs for `/api/v1/bookmarks*`.
//!
//! Wire contract (per R4 §3.3 + Phase 7 spec):
//!
//!   GET  /api/v1/bookmarks
//!       -> { items: [BookmarkRow], next_cursor: Option<String> }
//!   POST /api/v1/bookmarks/{question_id}
//!       -> { bookmarked: bool }
//!
//! `BookmarkRow` mirrors what `bp_main.py::bookmarks` yields to its
//! template — the FE renders the same cards from the same fields.

use serde::{Deserialize, Serialize};

#[derive(Debug, Default, Deserialize)]
pub struct BookmarkListQuery {
    pub cursor: Option<String>,
    pub limit: Option<u32>,
}

/// The nested `question` object matches the FE `Question` type — the FE
/// bookmark card renders `b.question.topic_id`, `b.question.question_text`,
/// `b.question.difficulty` and so on. We denormalise the fields the FE
/// actually reads (rather than serialising the full 20-column Question)
/// so we don't pay for columns the bookmark card never shows.
#[derive(Debug, Serialize)]
pub struct BookmarkQuestion {
    pub id: i64,
    pub topic_id: Option<i64>,
    pub question_text: Option<String>,
    pub option_a: Option<String>,
    pub option_b: Option<String>,
    pub option_c: Option<String>,
    pub option_d: Option<String>,
    pub correct_option: Option<String>,
    pub difficulty: Option<String>,
    pub topic_name: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct BookmarkRow {
    pub bookmark_id: i64,
    pub question: BookmarkQuestion,
    pub created_at: Option<String>,
    pub note: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct BookmarkListResponse {
    #[serde(rename = "bookmarks")]
    pub items: Vec<BookmarkRow>,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct BookmarkToggleResponse {
    /// Current state after the toggle. `true` = a bookmark row now exists
    /// for `(user_id, question_id)`.
    pub bookmarked: bool,
}
