"""Anthropic Claude Sonnet 4.6 integration for PDF → question extraction.

The API key is read from ANTHROPIC_API_KEY at call time. When the key is
missing, `extract_questions_from_pdf` returns a structured error dict so the
admin UI can surface it without crashing.
"""
import base64
import json
import os
from typing import Any


DEFAULT_MODEL = "claude-sonnet-4-6"


QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_text": {"type": "string"},
                    "option_a": {"type": "string"},
                    "option_b": {"type": "string"},
                    "option_c": {"type": "string"},
                    "option_d": {"type": "string"},
                    "correct_option": {"type": "string", "enum": ["A", "B", "C", "D", ""]},
                    "explanation": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "notes": {"type": "string"},
                },
                "required": [
                    "question_text", "option_a", "option_b", "option_c", "option_d",
                    "correct_option", "explanation", "difficulty", "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


def extract_questions_from_pdf(
    pdf_bytes: bytes,
    master_prompt: str,
    model: str = DEFAULT_MODEL,
    topic_hint: str = "",
) -> dict[str, Any]:
    """Send a PDF to Claude and get back a list of extracted MCQs.

    Returns a dict:
        {"ok": True,  "questions": [...], "usage": {...}, "model": "..."}
        {"ok": False, "error": "..."}

    Uses prompt caching on the master prompt so repeat uploads reuse the
    cached prefix.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "ANTHROPIC_API_KEY env var is not set. Add it in Render dashboard.",
        }

    try:
        import anthropic
    except ImportError:
        return {
            "ok": False,
            "error": "anthropic package not installed. Run: pip install anthropic",
        }

    client = anthropic.Anthropic(api_key=api_key)

    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    user_instruction = "Extract every MCQ from this PDF as strict JSON per the schema."
    if topic_hint:
        user_instruction += f"\n\nThe questions belong to the topic: {topic_hint}."

    try:
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=[
                {
                    "type": "text",
                    "text": master_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": user_instruction},
                    ],
                }
            ],
            output_config={"format": {"type": "json_schema", "schema": QUESTIONS_SCHEMA}},
        )
    except anthropic.BadRequestError as exc:
        return {"ok": False, "error": f"Bad request to Anthropic: {exc.message}"}
    except anthropic.AuthenticationError:
        return {"ok": False, "error": "Anthropic auth failed. Check ANTHROPIC_API_KEY."}
    except anthropic.RateLimitError:
        return {"ok": False, "error": "Anthropic rate limit hit. Wait and retry."}
    except anthropic.APIStatusError as exc:
        return {"ok": False, "error": f"Anthropic API error {exc.status_code}: {exc.message}"}
    except anthropic.APIConnectionError:
        return {"ok": False, "error": "Network error contacting Anthropic. Retry."}
    except Exception as exc:
        return {"ok": False, "error": f"Unexpected error: {exc}"}

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return {"ok": False, "error": "Empty response from Claude."}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"Failed to parse Claude JSON: {exc}", "raw": text[:2000]}

    questions = parsed.get("questions", [])
    return {
        "ok": True,
        "questions": questions,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
        },
        "model": model,
    }


# ─── Plan D §4 — Claude synthesis for under-represented topics ────────

SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_text": {"type": "string"},
                    "option_a": {"type": "string"},
                    "option_b": {"type": "string"},
                    "option_c": {"type": "string"},
                    "option_d": {"type": "string"},
                    "correct_option": {"type": "string", "enum": ["A", "B", "C", "D"]},
                    "explanation": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "source": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": [
                    "question_text", "option_a", "option_b", "option_c", "option_d",
                    "correct_option", "explanation", "difficulty",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


def synthesize_questions(
    prompt: str,
    n: int,
    model: str = "claude-opus-4-7",
) -> dict[str, Any]:
    """Call Claude to generate synthetic MCQs for a specific topic.

    The prompt is fully assembled by the caller (see content_metadata.SYNTHESIS_PROMPT).
    We use adaptive thinking since this is a quality-sensitive generation
    task — the model benefits from thinking budget on hard sub-topics.

    Returns:
        {"ok": True,  "questions": [...], "usage": {...}, "model": "..."}
        {"ok": False, "error": "..."}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY env var is not set."}

    try:
        import anthropic
    except ImportError:
        return {"ok": False, "error": "anthropic package not installed."}

    client = anthropic.Anthropic(api_key=api_key)

    # Output budget scales with question count: ~500 tok/question is
    # generous for a bilingual MCQ + explanation.
    max_tokens = max(4000, min(32000, 800 * max(n, 1)))

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
            output_config={"format": {"type": "json_schema", "schema": SYNTHESIS_SCHEMA}},
        )
    except anthropic.BadRequestError as exc:
        return {"ok": False, "error": f"Bad request to Anthropic: {exc.message}"}
    except anthropic.AuthenticationError:
        return {"ok": False, "error": "Anthropic auth failed. Check ANTHROPIC_API_KEY."}
    except anthropic.RateLimitError:
        return {"ok": False, "error": "Anthropic rate limit hit. Wait and retry."}
    except anthropic.APIStatusError as exc:
        return {"ok": False, "error": f"Anthropic API error {exc.status_code}: {exc.message}"}
    except anthropic.APIConnectionError:
        return {"ok": False, "error": "Network error contacting Anthropic. Retry."}
    except Exception as exc:  # noqa: BLE001 — the caller wants a structured error
        return {"ok": False, "error": f"Unexpected error: {exc}"}

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return {"ok": False, "error": "Empty response from Claude."}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"Failed to parse Claude JSON: {exc}", "raw": text[:2000]}

    questions = parsed.get("questions", [])
    return {
        "ok": True,
        "questions": questions,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "model": model,
    }
