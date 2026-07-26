//! Leitner-5 spaced-repetition primitives.
//!
//! Ported from `sr.py` — kept as a plain module of pure functions so
//! callers (tests-finish, upcoming /review endpoints in Phase 6) can
//! exercise the schedule without touching axum or the database.
//!
//! Design rules (see `docs/plans/A-study-effectiveness.md` §1.3-1.5 and
//! the Flask `sr.py` for the historical Python side):
//!
//!   * 5 boxes.
//!   * Correct → box+1, capped at 5.
//!   * Wrong  → drop back per `DROP_ON_MISS`. A miss at box 5 falls to
//!     box 3, not box 1 — a lapse at that level is usually momentary,
//!     not a genuine forgetting.
//!   * Interval-days per box are `BOX_INTERVALS_DAYS`.
//!   * `next_due(box)` = today + interval-days(box), formatted as an
//!     ISO date string (`YYYY-MM-DD`) so it slots straight into a
//!     TEXT column.
//!
//! `finish()` in `api::tests` calls `initial_box_and_due()` to seed a
//! fresh error_log row. Phase 6's review endpoints will call
//! `next_box_and_due()` when the user answers a card.

use chrono::{Duration, NaiveDate, Utc};

/// Days until next review per box (1..=5). Falls back to 1 day for any
/// out-of-range box.
pub fn box_interval_days(box_num: i64) -> i64 {
    match box_num {
        1 => 1,
        2 => 3,
        3 => 7,
        4 => 14,
        5 => 30,
        _ => 1,
    }
}

/// Wrong-answer demotion table (matches `sr.py::DROP_ON_MISS`).
fn drop_on_miss(box_num: i64) -> i64 {
    match box_num {
        1 => 1,
        2 => 1,
        3 => 1,
        4 => 2,
        5 => 3,
        _ => 1,
    }
}

pub const MAX_BOX: i64 = 5;

/// Return the box a card moves to after a review.
pub fn next_box(current_box: i64, was_correct: bool) -> i64 {
    let cur = if current_box <= 0 { 1 } else { current_box };
    if was_correct {
        (cur + 1).min(MAX_BOX)
    } else {
        drop_on_miss(cur)
    }
}

/// Compute the ISO-date string (`YYYY-MM-DD`) for a card's next due
/// date given its box. Uses today's UTC date as the anchor.
pub fn next_due(box_num: i64) -> String {
    let today = Utc::now().date_naive();
    let due = today + Duration::days(box_interval_days(box_num));
    due.format("%Y-%m-%d").to_string()
}

/// Convenience: box + due for a fresh error_log row. Called from
/// `finish()` after we detect a wrong answer.
pub fn initial_box_and_due() -> (i64, String) {
    (1, next_due(1))
}

/// Convenience: after a review, return `(new_box, new_due)`.
#[allow(dead_code)]
pub fn next_box_and_due(current_box: i64, was_correct: bool) -> (i64, String) {
    let nb = next_box(current_box, was_correct);
    (nb, next_due(nb))
}

/// Positive = due in the future, 0 = due today, negative = overdue.
/// Accepts both plain `YYYY-MM-DD` and full RFC3339 datetimes (takes
/// the leading date slice).
#[allow(dead_code)]
pub fn days_until_due(sr_due_at: &str) -> i64 {
    let head = &sr_due_at[..sr_due_at.len().min(10)];
    let Ok(due) = NaiveDate::parse_from_str(head, "%Y-%m-%d") else {
        return 0;
    };
    let today = Utc::now().date_naive();
    (due - today).num_days()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn promote_caps_at_five() {
        assert_eq!(next_box(4, true), 5);
        assert_eq!(next_box(5, true), 5);
    }

    #[test]
    fn demote_follows_drop_map() {
        assert_eq!(next_box(1, false), 1);
        assert_eq!(next_box(2, false), 1);
        assert_eq!(next_box(3, false), 1);
        assert_eq!(next_box(4, false), 2);
        assert_eq!(next_box(5, false), 3);
    }

    #[test]
    fn interval_days_known_values() {
        assert_eq!(box_interval_days(1), 1);
        assert_eq!(box_interval_days(2), 3);
        assert_eq!(box_interval_days(3), 7);
        assert_eq!(box_interval_days(4), 14);
        assert_eq!(box_interval_days(5), 30);
    }

    #[test]
    fn initial_seed_is_box_one() {
        let (b, _due) = initial_box_and_due();
        assert_eq!(b, 1);
    }
}
