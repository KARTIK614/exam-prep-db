//! `/api/v1/admin/*` handlers — every route requires `RequireAdmin`.
//!
//! Grouped by resource for clarity; route wiring lives in the parent
//! `api::mod::router`.

pub mod duplicates;
pub mod flags;
pub mod questions;
pub mod review;
pub mod synthesize;
pub mod uploads;
pub mod users;

/// Convert a caller-supplied disabled bool into the SQLite integer form
/// used throughout the schema.
#[inline]
pub(crate) fn bool_to_int(b: bool) -> i64 {
    if b {
        1
    } else {
        0
    }
}
