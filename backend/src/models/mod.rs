//! Domain structs mirroring the Turso schema after the v3 Phase 2
//! multi-user migration (see `scripts/migrate_v3_add_user_id.py`).
//!
//! Each struct provides:
//!   - `#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]` for
//!     wire + logging use.
//!   - A hand-rolled `from_row(row: &libsql::Row) -> anyhow::Result<Self>`
//!     that maps column positions to fields.
//!
//! Column order in each `from_row` MUST match the SELECT list the caller
//! uses. To keep this hand-mapping honest we expose a `COLUMNS` &'static
//! [&'static str] on each type — callers should write:
//!
//! ```rust,ignore
//! let sql = format!("SELECT {} FROM users WHERE id = ?", User::COLUMNS.join(", "));
//! ```
//!
//! This means adding a column is a two-line change: (1) push into
//! `COLUMNS`, (2) push into the struct + `from_row`.
//!
//! Type-mapping conventions (per R2 §9.1):
//!   - SQLite `INTEGER` boolean flags (`is_active`, `is_correct`,
//!     `disabled`, `resolved`, `marked_for_review`) surface as `bool`.
//!     Deserialised via `int_to_bool()` helper below.
//!   - Date/time columns stay as `Option<String>` here — the domain layer
//!     does the ISO parse where it needs a `chrono::DateTime`. Keeping
//!     these as strings at the struct boundary avoids a chrono dep leak
//!     through every module.
//!   - Nullable columns are `Option<T>`. `NOT NULL DEFAULT ...` columns
//!     are the bare `T`.

pub mod bookmark;
pub mod error_log;
pub mod mock_test;
pub mod question;
pub mod question_flag;
pub mod study_session;
pub mod test_response;
pub mod topic;
pub mod topic_mastery;
pub mod user;

pub use bookmark::Bookmark;
pub use error_log::ErrorLog;
pub use mock_test::MockTest;
pub use question::Question;
pub use question_flag::QuestionFlag;
pub use study_session::StudySession;
pub use test_response::TestResponse;
pub use topic::Topic;
pub use topic_mastery::TopicMastery;
pub use user::User;

/// Coerce SQLite's 0/1 integer boolean columns into `bool`. `NULL` and
/// any nonzero integer become `true`/`false` respectively (SQLite
/// convention: zero is false).
#[allow(dead_code)]
pub(crate) fn int_to_bool(v: Option<i64>) -> bool {
    matches!(v, Some(n) if n != 0)
}

/// Read a `libsql::Value` column and coerce it to `Option<String>`.
/// TEXT-null columns come across as `Value::Null`; TEXT non-null as
/// `Value::Text`. Any other value type is stringified via `format!`
/// (defensive — should not happen for TEXT columns).
#[allow(dead_code)]
pub(crate) fn value_to_opt_string(v: libsql::Value) -> Option<String> {
    match v {
        libsql::Value::Null => None,
        libsql::Value::Text(s) => Some(s),
        libsql::Value::Integer(i) => Some(i.to_string()),
        libsql::Value::Real(f) => Some(f.to_string()),
        libsql::Value::Blob(b) => Some(format!("<blob:{} bytes>", b.len())),
    }
}

/// Same idea for `Option<i64>` — accepts Null / Integer / a numeric-looking
/// Text (Hrana occasionally serialises integers as strings on the wire).
#[allow(dead_code)]
pub(crate) fn value_to_opt_i64(v: libsql::Value) -> Option<i64> {
    match v {
        libsql::Value::Null => None,
        libsql::Value::Integer(i) => Some(i),
        libsql::Value::Text(s) => s.parse().ok(),
        libsql::Value::Real(f) => Some(f as i64),
        libsql::Value::Blob(_) => None,
    }
}

/// Same for `Option<f64>`.
#[allow(dead_code)]
pub(crate) fn value_to_opt_f64(v: libsql::Value) -> Option<f64> {
    match v {
        libsql::Value::Null => None,
        libsql::Value::Real(f) => Some(f),
        libsql::Value::Integer(i) => Some(i as f64),
        libsql::Value::Text(s) => s.parse().ok(),
        libsql::Value::Blob(_) => None,
    }
}
