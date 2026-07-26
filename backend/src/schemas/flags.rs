//! Request / response DTOs for `POST /api/v1/questions/{qid}/flag`.
//!
//! Category enum mirrors `bp_api.FLAG_CATEGORIES` exactly — the FE Chip
//! group is built off this same list.

use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
pub struct FlagCreateRequest {
    /// One of: `wrong_answer | ambiguous | typo_question | typo_options |
    /// explanation_missing | duplicate | other`.
    pub category: String,
    /// Freeform user note. Required when `category == "other"`. Server
    /// truncates to 1000 chars to match the Flask semantics.
    pub note: Option<String>,
    /// Optional link back to the mock_test the flag was raised from.
    pub test_id: Option<i64>,
}

#[derive(Debug, Serialize)]
pub struct FlagCreateResponse {
    pub flag_id: i64,
}
