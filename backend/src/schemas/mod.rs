//! Request / response DTOs for the HTTP layer.
//!
//! Kept separate from `models::*` (which mirror the DB schema) so we can
//! evolve the wire contract independently of the storage layout. Every
//! type here derives `serde::Serialize` and/or `Deserialize` plus, where
//! useful, `validator::Validate`.

pub mod admin;
pub mod analytics;
pub mod auth;
pub mod bookmarks;
pub mod content;
pub mod deep_dive;
pub mod exam_presets;
pub mod flags;
pub mod review;
pub mod tests;
