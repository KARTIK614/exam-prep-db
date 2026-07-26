//! Gemini REST client + response parser for `POST /api/v1/questions/{qid}/deep-dive`.
//!
//! Mirrors the prompt template + section-split logic from
//! `bp_doubt.py::deep_dive` (Python), returning `DeepDiveResponse` shaped
//! for the React front-end.
//!
//! Model: `gemini-2.5-flash` by default (override via GEMINI_MODEL env var).
//! Uses the REST endpoint at `generativelanguage.googleapis.com/v1beta/…`,
//! same shape as `ai_utils.py::call_gemini`.
//!
//! On failure the caller wraps the error with a stable UUID + logs
//! server-side; the public envelope stays `{error: {code, message,
//! request_id}}` with a "AI tutor temporarily unavailable. Ref: <id>"
//! message.

use secrecy::ExposeSecret;
use serde::{Deserialize, Serialize};

use crate::config::LlmConfig;

/// One-shot generation call.
///
/// Returns the raw response text (Gemini's `candidates[0].content.parts`
/// joined). Callers apply `parse_sections` to slice it into the structured
/// DeepDive response.
pub async fn generate(cfg: &LlmConfig, prompt: &str) -> anyhow::Result<String> {
    let api_key = cfg
        .gemini_api_key
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("GEMINI_API_KEY not configured"))?;
    // Optional model override at request time; env is read once at startup
    // via `Config`, so we accept a per-call override here for flexibility.
    let model = std::env::var("GEMINI_MODEL")
        .ok()
        .unwrap_or_else(|| "gemini-2.5-flash".to_string());

    let url = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    );

    let body = serde_json::json!({
        "contents": [{
            "parts": [{ "text": prompt }],
        }],
    });

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()?;

    let resp = client
        .post(&url)
        .query(&[("key", api_key.expose_secret().as_str())])
        .json(&body)
        .send()
        .await?;

    let status = resp.status();
    if !status.is_success() {
        let snippet = resp.text().await.unwrap_or_default();
        return Err(anyhow::anyhow!(
            "gemini {status}: {}",
            snippet.chars().take(400).collect::<String>()
        ));
    }

    let parsed: GeminiResponse = resp.json().await?;
    let cand = parsed
        .candidates
        .into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("gemini: no candidates"))?;
    let text = cand
        .content
        .parts
        .into_iter()
        .filter_map(|p| p.text)
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string();

    if text.is_empty() {
        return Err(anyhow::anyhow!("gemini: empty completion"));
    }
    Ok(text)
}

/// Split the model's markdown reply into (concept explanation, key facts, exam
/// tips, follow-up suggestions). Best-effort — headings that don't match
/// fall into the `explanation` bucket.
pub fn parse_sections(reply: &str) -> ParsedDeepDive {
    let mut out = ParsedDeepDive::default();

    // Section markers we care about. Look for lines starting with either
    // `## Concept`, `1. **Concept`, `### Concept`, etc. Case-insensitive.
    #[derive(Clone, Copy)]
    enum Section {
        Explanation,
        KeyFacts,
        ExamTips,
        FollowUp,
    }

    let mut current: Section = Section::Explanation;
    let mut buf: std::collections::HashMap<u8, String> = std::collections::HashMap::new();

    for raw_line in reply.lines() {
        let line = raw_line;
        let lc = line.to_ascii_lowercase();
        let is_heading =
            lc.contains("concept") || lc.contains("key fact") || lc.contains("key facts")
                || lc.contains("exam tip") || lc.contains("follow-up")
                || lc.contains("follow up") || lc.contains("suggestions");
        if is_heading
            && (line.starts_with('#')
                || line.starts_with("**")
                || line.trim_start().starts_with(|c: char| c.is_ascii_digit()))
        {
            current = if lc.contains("key fact") {
                Section::KeyFacts
            } else if lc.contains("exam tip") {
                Section::ExamTips
            } else if lc.contains("follow") || lc.contains("suggestion") {
                Section::FollowUp
            } else {
                Section::Explanation
            };
            continue;
        }
        let key = match current {
            Section::Explanation => 0u8,
            Section::KeyFacts => 1,
            Section::ExamTips => 2,
            Section::FollowUp => 3,
        };
        buf.entry(key).or_default().push_str(line);
        buf.entry(key).or_default().push('\n');
    }

    out.explanation = buf.remove(&0).unwrap_or_default().trim().to_string();
    let bullets = |s: String| -> Vec<String> {
        s.lines()
            .map(|l| l.trim_start_matches(|c: char| c == '-' || c == '*' || c.is_whitespace()))
            .map(str::trim)
            .filter(|l| !l.is_empty())
            .map(String::from)
            .collect()
    };
    out.key_facts = buf.remove(&1).map(bullets).unwrap_or_default();
    out.exam_tips = buf.remove(&2).map(bullets).unwrap_or_default();
    out.follow_up_suggestions = buf.remove(&3).map(bullets).unwrap_or_default();

    // Guardrail: if the model dumped everything into a single unstructured
    // blob, the whole reply lives in `explanation` and the arrays are empty
    // — the FE handles that gracefully with a `key_facts.length === 0`
    // fallback.
    out
}

#[derive(Default, Debug, Clone)]
pub struct ParsedDeepDive {
    pub explanation: String,
    pub key_facts: Vec<String>,
    pub exam_tips: Vec<String>,
    pub follow_up_suggestions: Vec<String>,
}

/// Build the exam-prep-tutor prompt (mirrors `bp_doubt.py`).
pub fn build_prompt(
    question_text: &str,
    topic_name: Option<&str>,
    subject: Option<&str>,
    correct_option: Option<&str>,
    official_explanation: Option<&str>,
) -> String {
    let topic = topic_name.unwrap_or("(unknown)");
    let subject = subject.unwrap_or("(unknown)");
    let correct = correct_option.unwrap_or("?");
    let expl = official_explanation.unwrap_or("None provided");
    let qtext: String = question_text.chars().take(500).collect();

    format!(
        "You are an expert tutor for Rajasthan competitive exams (Computer Anudeshak / Computer Instructor). Analyze this question deeply.\n\n\
QUESTION: {qtext}\n\
TOPIC: {topic}\n\
SUBJECT: {subject}\n\
CORRECT ANSWER: {correct}\n\
OFFICIAL EXPLANATION: {expl}\n\n\
Give a structured response with these exact sections:\n\
1. **Concept Explanation** — 2-3 paragraphs explaining the concept in depth. Include background, context, and why the correct answer is right.\n\
2. **Key Facts** — 3-5 bullet points of must-remember facts related to this topic.\n\
3. **Exam Tips** — How this topic is typically tested, common traps, and what similar questions to expect.\n\
4. **Follow-Up Suggestions** — 2-3 short clarifying questions a student might ask next.\n\n\
Use markdown formatting. Keep each section concise but thorough. IMPORTANT: Write the ENTIRE response in English only. Do NOT use Hindi or any other language."
    )
}

// ---------- Gemini REST wire types -----------------------------------------

#[derive(Deserialize)]
struct GeminiResponse {
    #[serde(default)]
    candidates: Vec<GeminiCandidate>,
}

#[derive(Deserialize)]
struct GeminiCandidate {
    #[serde(default)]
    content: GeminiContent,
}

#[derive(Default, Deserialize)]
struct GeminiContent {
    #[serde(default)]
    parts: Vec<GeminiPart>,
}

#[derive(Deserialize)]
struct GeminiPart {
    text: Option<String>,
}

// Also useful for admin/synthesize (DeepSeek is OpenAI-compat).
#[derive(Serialize)]
pub struct OpenAiChatMessage<'a> {
    pub role: &'a str,
    pub content: &'a str,
}
