//! Answer grading for the three question types GATE uses.
//!
//! Answers are plain TEXT in both `questions.correct_option` (the key) and
//! `test_responses.selected_option` (the response), so the RSSB rows that
//! pre-date this module keep working unchanged:
//!
//!   * MCQ — key `"B"`; several accepted answers `"A;B"`; marks to all `"MTA"`.
//!   * MSQ — key `"A;C"` (letters, `;`-separated). No partial credit:
//!     the chosen set must equal the key set exactly.
//!   * NAT — key `"lo:hi"`, an inclusive range (`"6:6"` for an exact value).
//!
//! Marking: a correct answer earns `marks`. A wrong answer costs
//! `neg_marks` in exam mode — or, when the question has no `neg_marks`,
//! the legacy rule `marks × test negative_ratio` for MCQ and nothing for
//! MSQ/NAT. Practice mode never deducts. Unanswered is always 0.

use std::collections::BTreeSet;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QType {
    Mcq,
    Msq,
    Nat,
}

impl QType {
    /// Unknown or missing values fall back to MCQ, the legacy default.
    pub fn parse(s: Option<&str>) -> QType {
        match s.map(|v| v.trim().to_ascii_uppercase()).as_deref() {
            Some("MSQ") => QType::Msq,
            Some("NAT") => QType::Nat,
            _ => QType::Mcq,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            QType::Mcq => "MCQ",
            QType::Msq => "MSQ",
            QType::Nat => "NAT",
        }
    }
}

const NAT_EPS: f64 = 1e-9;

fn letters(s: &str) -> BTreeSet<char> {
    s.chars()
        .map(|c| c.to_ascii_uppercase())
        .filter(|c| matches!(c, 'A'..='D'))
        .collect()
}

/// Validate a response and bring it to its canonical stored form.
/// `Ok(None)` means "cleared / unanswered".
pub fn normalize_response(qtype: QType, raw: &str) -> Result<Option<String>, String> {
    let s = raw.trim();
    if s.is_empty() {
        return Ok(None);
    }
    match qtype {
        QType::Mcq => match s.to_ascii_uppercase().as_str() {
            v @ ("A" | "B" | "C" | "D") => Ok(Some(v.to_string())),
            _ => Err(format!("invalid answer for MCQ: {s} (expected A|B|C|D)")),
        },
        QType::Msq => {
            let only_allowed = s
                .chars()
                .all(|c| matches!(c.to_ascii_uppercase(), 'A'..='D') || matches!(c, ';' | ',' | ' '));
            let set = letters(s);
            if !only_allowed || set.is_empty() {
                return Err(format!(
                    "invalid answer for MSQ: {s} (expected letters A-D, e.g. A;C)"
                ));
            }
            Ok(Some(set.iter().map(|c| c.to_string()).collect::<Vec<_>>().join(";")))
        }
        QType::Nat => match s.parse::<f64>() {
            Ok(v) if v.is_finite() && s.len() <= 32 => Ok(Some(s.to_string())),
            _ => Err(format!("invalid answer for NAT: {s} (expected a number)")),
        },
    }
}

/// Parse a NAT key: `"lo:hi"`, `"lo to hi"`, or a single value.
fn nat_range(key: &str) -> Option<(f64, f64)> {
    let k = key.trim();
    let parts: Vec<&str> = if k.contains(':') {
        k.split(':').collect()
    } else if k.contains(" to ") {
        k.split(" to ").collect()
    } else {
        vec![k]
    };
    let nums: Option<Vec<f64>> = parts.iter().map(|p| p.trim().parse::<f64>().ok()).collect();
    match nums?.as_slice() {
        [v] => Some((*v, *v)),
        [a, b] => Some((a.min(*b), a.max(*b))),
        _ => None,
    }
}

/// Is `response` a correct answer for `key`? Unanswered is never correct.
pub fn is_correct(qtype: QType, key: Option<&str>, response: Option<&str>) -> bool {
    let (Some(key), Some(resp)) = (key.map(str::trim), response.map(str::trim)) else {
        return false;
    };
    if resp.is_empty() || key.is_empty() {
        return false;
    }
    if key.eq_ignore_ascii_case("MTA") {
        return true;
    }
    match qtype {
        QType::Mcq => key
            .split(';')
            .any(|k| k.trim().eq_ignore_ascii_case(resp)),
        QType::Msq => {
            let k = letters(key);
            !k.is_empty() && k == letters(resp)
        }
        QType::Nat => match (nat_range(key), resp.parse::<f64>()) {
            (Some((lo, hi)), Ok(v)) => v >= lo - NAT_EPS && v <= hi + NAT_EPS,
            _ => false,
        },
    }
}

/// Marks for one question. See the module docs for the rules.
pub fn marks_for(
    qtype: QType,
    answered: bool,
    correct: bool,
    marks: f64,
    neg_marks: Option<f64>,
    test_negative_ratio: f64,
    exam_mode: bool,
) -> f64 {
    if !answered {
        return 0.0;
    }
    if correct {
        return marks;
    }
    if !exam_mode {
        return 0.0;
    }
    let penalty = match (neg_marks, qtype) {
        (Some(n), _) => n,
        (None, QType::Mcq) => marks * test_negative_ratio,
        (None, _) => 0.0,
    };
    -penalty.abs()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mcq_legacy_and_multi_key() {
        assert!(is_correct(QType::Mcq, Some("B"), Some("B")));
        assert!(!is_correct(QType::Mcq, Some("B"), Some("C")));
        assert!(is_correct(QType::Mcq, Some("A;B"), Some("B")));
        assert!(is_correct(QType::Mcq, Some("MTA"), Some("D")));
        assert!(!is_correct(QType::Mcq, Some("B"), None));
        assert_eq!(normalize_response(QType::Mcq, " c ").unwrap().as_deref(), Some("C"));
        assert!(normalize_response(QType::Mcq, "E").is_err());
        assert_eq!(normalize_response(QType::Mcq, "").unwrap(), None);
    }

    #[test]
    fn msq_needs_exact_set() {
        assert!(is_correct(QType::Msq, Some("A;C"), Some("C;A")));
        assert!(!is_correct(QType::Msq, Some("A;C"), Some("A")));
        assert!(!is_correct(QType::Msq, Some("A;C"), Some("A;B;C")));
        assert!(is_correct(QType::Msq, Some("D"), Some("D")));
        assert_eq!(normalize_response(QType::Msq, "c, a ,c").unwrap().as_deref(), Some("A;C"));
        assert!(normalize_response(QType::Msq, "A;X").is_err());
        assert!(normalize_response(QType::Msq, ";").is_err());
    }

    #[test]
    fn nat_ranges() {
        assert!(is_correct(QType::Nat, Some("2:2"), Some("2")));
        assert!(is_correct(QType::Nat, Some("2:2"), Some("2.0")));
        assert!(is_correct(QType::Nat, Some("0.32:0.34"), Some("0.33")));
        assert!(!is_correct(QType::Nat, Some("0.32:0.34"), Some("0.35")));
        assert!(is_correct(QType::Nat, Some("16 to 16"), Some("16")));
        assert!(is_correct(QType::Nat, Some("5:3"), Some("4")));
        assert!(!is_correct(QType::Nat, Some("garbage"), Some("4")));
        assert!(normalize_response(QType::Nat, "abc").is_err());
        assert!(normalize_response(QType::Nat, "inf").is_err());
        assert_eq!(normalize_response(QType::Nat, " -1.5 ").unwrap().as_deref(), Some("-1.5"));
    }

    #[test]
    fn marking_rules() {
        // GATE 2-mark MCQ wrong in exam mode: −2/3.
        let m = marks_for(QType::Mcq, true, false, 2.0, Some(2.0 / 3.0), 0.0, true);
        assert!((m + 2.0 / 3.0).abs() < 1e-9);
        // GATE MSQ/NAT wrong: 0.
        assert_eq!(marks_for(QType::Msq, true, false, 2.0, Some(0.0), 0.33, true), 0.0);
        assert_eq!(marks_for(QType::Nat, true, false, 1.0, None, 0.33, true), 0.0);
        // Legacy RSSB MCQ: marks 1, no neg_marks → test ratio.
        let m = marks_for(QType::Mcq, true, false, 1.0, None, 1.0 / 3.0, true);
        assert!((m + 1.0 / 3.0).abs() < 1e-9);
        // Practice mode never deducts; unanswered is 0; correct earns marks.
        assert_eq!(marks_for(QType::Mcq, true, false, 1.0, Some(0.33), 0.33, false), 0.0);
        assert_eq!(marks_for(QType::Mcq, false, false, 1.0, None, 0.33, true), 0.0);
        assert_eq!(marks_for(QType::Nat, true, true, 2.0, None, 0.0, true), 2.0);
    }

    #[test]
    fn qtype_parse_defaults_to_mcq() {
        assert_eq!(QType::parse(None), QType::Mcq);
        assert_eq!(QType::parse(Some("msq")), QType::Msq);
        assert_eq!(QType::parse(Some(" NAT ")), QType::Nat);
        assert_eq!(QType::parse(Some("weird")), QType::Mcq);
    }
}
