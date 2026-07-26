//! Cross-cutting request middleware + extractors.
//!
//! Currently just auth (RequireAuth, RequireAdmin). Rate limiting lives
//! in `api::mod` because it wires into the router builder directly.

pub mod auth;
