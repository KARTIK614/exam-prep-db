//! Pure-ish helper services (no HTTP concerns).
//!
//! `services::*` modules host business logic that handlers call. They
//! never touch axum types directly.

pub mod auth;
pub mod gemini;
pub mod sr;
