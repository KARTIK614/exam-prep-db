//! Cursor pagination helpers shared by list endpoints.
//!
//! The cursor is a base64url-encoded (no padding) `i64` — the last row's
//! primary key from the previous page. Handlers use this to build a
//! `WHERE id < ?` (DESC) or `WHERE id > ?` (ASC) clause; only ASC is
//! used at the moment (topics/questions/search all order by `id ASC`).
//!
//! Format choice: a single-integer cursor is trivial to decode and
//! survives across schema evolutions as long as the primary key is still
//! `i64`. If we ever need multi-column sorts we can widen this to a
//! struct + JSON payload (see R4 §5.2 for the plan-doc's format).

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;

use crate::error::AppError;

/// Default page size for list endpoints when the caller omits `limit`.
pub const DEFAULT_LIMIT: u32 = 20;
/// Hard maximum enforced regardless of what the caller asked for.
pub const MAX_LIMIT: u32 = 100;

/// Clamp caller-supplied `limit` into `[1, MAX_LIMIT]`, defaulting to
/// `DEFAULT_LIMIT` when absent.
pub fn clamp_limit(requested: Option<u32>) -> u32 {
    match requested {
        Some(n) if n >= 1 => n.min(MAX_LIMIT),
        Some(_) => 1,
        None => DEFAULT_LIMIT,
    }
}

/// Decode a caller-supplied cursor back into an `i64` id.
///
/// Returns `Ok(None)` when the cursor is absent or empty. Returns
/// `Err(AppError::BadRequest)` when the string is present but malformed —
/// mirrors "your pagination state is stale, restart" rather than silently
/// dropping the filter.
pub fn decode_cursor(cursor: Option<&str>) -> Result<Option<i64>, AppError> {
    let Some(s) = cursor.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(None);
    };
    let bytes = URL_SAFE_NO_PAD
        .decode(s)
        .map_err(|_| AppError::BadRequest("invalid cursor".into()))?;
    let text = std::str::from_utf8(&bytes)
        .map_err(|_| AppError::BadRequest("invalid cursor".into()))?;
    let id: i64 = text
        .parse()
        .map_err(|_| AppError::BadRequest("invalid cursor".into()))?;
    Ok(Some(id))
}

/// Encode a row id as an opaque cursor for the client to feed back on
/// the next page.
pub fn encode_cursor(id: i64) -> String {
    URL_SAFE_NO_PAD.encode(id.to_string().as_bytes())
}

/// Given the number of rows returned and the requested page size, decide
/// whether to emit a `next_cursor` and what its value is.
///
/// Contract: if `rows.len() == limit` we assume there *may* be another
/// page — the caller feeds `next_cursor` back and the next query
/// returns 0 rows (`None`) if that assumption was wrong. This trades a
/// possibly-empty terminal fetch for avoiding a second `COUNT(*)` round
/// trip per list request.
pub fn next_cursor(last_id: Option<i64>, returned: usize, limit: u32) -> Option<String> {
    if returned as u32 == limit {
        last_id.map(encode_cursor)
    } else {
        None
    }
}
