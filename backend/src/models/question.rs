//! `questions` — global content, NO user_id.
//!
//! 21 columns (base 12 + 9 additions from earlier phases):
//!   base:      id, topic_id, question_text,
//!              option_a, option_b, option_c, option_d,
//!              correct_option, explanation, difficulty, source, language
//!   phase 2:   disabled, updated_at
//!   phase 6/7: confidence, section, sub_topic, pyq_exam, pyq_year,
//!              review_notes, confidence_reviewed_at

use anyhow::Context;
use serde::{Deserialize, Serialize};

use super::{int_to_bool, value_to_opt_i64, value_to_opt_string};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Question {
    pub id: i64,
    pub topic_id: Option<i64>,
    pub question_text: Option<String>,
    pub option_a: Option<String>,
    pub option_b: Option<String>,
    pub option_c: Option<String>,
    pub option_d: Option<String>,
    pub correct_option: Option<String>,
    pub explanation: Option<String>,
    pub difficulty: Option<String>,
    pub source: Option<String>,
    pub language: Option<String>,
    pub disabled: bool,
    pub updated_at: Option<String>,
    pub confidence: Option<String>,
    pub section: Option<String>,
    pub sub_topic: Option<String>,
    pub pyq_exam: Option<String>,
    pub pyq_year: Option<i64>,
    pub review_notes: Option<String>,
    pub confidence_reviewed_at: Option<String>,
}

impl Question {
    pub const COLUMNS: &'static [&'static str] = &[
        "id",
        "topic_id",
        "question_text",
        "option_a",
        "option_b",
        "option_c",
        "option_d",
        "correct_option",
        "explanation",
        "difficulty",
        "source",
        "language",
        "disabled",
        "updated_at",
        "confidence",
        "section",
        "sub_topic",
        "pyq_exam",
        "pyq_year",
        "review_notes",
        "confidence_reviewed_at",
    ];

    pub fn from_row(row: &libsql::Row) -> anyhow::Result<Self> {
        Ok(Self {
            id: row.get::<i64>(0).context("questions.id")?,
            topic_id: value_to_opt_i64(row.get_value(1).context("questions.topic_id")?),
            question_text: value_to_opt_string(
                row.get_value(2).context("questions.question_text")?,
            ),
            option_a: value_to_opt_string(row.get_value(3).context("questions.option_a")?),
            option_b: value_to_opt_string(row.get_value(4).context("questions.option_b")?),
            option_c: value_to_opt_string(row.get_value(5).context("questions.option_c")?),
            option_d: value_to_opt_string(row.get_value(6).context("questions.option_d")?),
            correct_option: value_to_opt_string(
                row.get_value(7).context("questions.correct_option")?,
            ),
            explanation: value_to_opt_string(
                row.get_value(8).context("questions.explanation")?,
            ),
            difficulty: value_to_opt_string(row.get_value(9).context("questions.difficulty")?),
            source: value_to_opt_string(row.get_value(10).context("questions.source")?),
            language: value_to_opt_string(row.get_value(11).context("questions.language")?),
            disabled: int_to_bool(value_to_opt_i64(
                row.get_value(12).context("questions.disabled")?,
            )),
            updated_at: value_to_opt_string(
                row.get_value(13).context("questions.updated_at")?,
            ),
            confidence: value_to_opt_string(
                row.get_value(14).context("questions.confidence")?,
            ),
            section: value_to_opt_string(row.get_value(15).context("questions.section")?),
            sub_topic: value_to_opt_string(row.get_value(16).context("questions.sub_topic")?),
            pyq_exam: value_to_opt_string(row.get_value(17).context("questions.pyq_exam")?),
            pyq_year: value_to_opt_i64(row.get_value(18).context("questions.pyq_year")?),
            review_notes: value_to_opt_string(
                row.get_value(19).context("questions.review_notes")?,
            ),
            confidence_reviewed_at: value_to_opt_string(
                row.get_value(20).context("questions.confidence_reviewed_at")?,
            ),
        })
    }
}
