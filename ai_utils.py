"""AI helpers — notes lookup + Gemini REST API wrapper.

Uses Google's Generative Language REST endpoint (not the Node CLI) so we don't
need any binary on the deploy host (Render). `GEMINI_API_KEY` must be set in
the environment; missing key raises a clear RuntimeError so callers can surface
it with an error ID instead of leaking the raw exception.
"""
import os
import re

import requests

from ai_config import NOTES_DIR, NOTES_FILES, SUPPLEMENTARY_FILES


# gemini-2.5-flash is the current stable Flash tier (per Google's docs). If the
# model gets deprecated/renamed, override via GEMINI_MODEL env var without a
# code change.
DEFAULT_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


def get_notes_context(topic_name, subject, question_text):
    """Search relevant markdown files for context about this question."""
    files_to_search = list(set(
        NOTES_FILES.get(subject, []) + SUPPLEMENTARY_FILES
    ))
    candidates = []

    for fname in files_to_search:
        fpath = os.path.join(NOTES_DIR, fname)
        if not os.path.exists(fpath):
            continue
        try:
            content = open(fpath, 'r', encoding='utf-8', errors='ignore').read()
        except Exception:
            continue

        sections = re.split(r'\n(?=##\s)', content)
        for sec in sections:
            if len(sec.strip()) < 40:
                continue
            keywords = set(re.findall(r'\w+', (topic_name + ' ' + question_text).lower()))
            sec_words = set(re.findall(r'\w+', sec.lower()))
            score = len(keywords & sec_words)
            if score > 0:
                candidates.append((score, sec[:2000]))

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = [c[1] for c in candidates[:5]]
    context = '\n\n---\n\n'.join(top)
    return context[:4000]


def call_gemini(prompt, timeout=60):
    """POST `prompt` to Gemini's REST endpoint and return the assistant text.

    Raises:
        RuntimeError: if GEMINI_API_KEY is missing, the HTTP call fails, or
            the response schema doesn't include the expected text block. The
            caller (bp_doubt) wraps this in a try/except and surfaces a
            user-friendly error-ID message.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY env var is not set")

    model = DEFAULT_GEMINI_MODEL
    url = GEMINI_API_URL.format(model=model)
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    resp = requests.post(
        url,
        params={"key": api_key},
        json=body,
        timeout=timeout,
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code != 200:
        # Include status + short snippet of body so server logs are useful,
        # but never let this bubble to the UI unfiltered (bp_doubt wraps).
        snippet = (resp.text or "")[:400]
        raise RuntimeError(
            f"Gemini API returned HTTP {resp.status_code}: {snippet}"
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Gemini API returned non-JSON body: {exc}") from exc

    # Expected shape: data["candidates"][0]["content"]["parts"][0]["text"].
    # Some responses (safety blocks, empty completions) omit parts — treat as
    # empty text and let the caller decide whether to show a fallback.
    try:
        candidates = data.get("candidates") or []
        if not candidates:
            # promptFeedback.blockReason is the usual culprit here.
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            if reason:
                raise RuntimeError(f"Gemini blocked the prompt: {reason}")
            raise RuntimeError("Gemini returned no candidates")

        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        text = "\n".join(t for t in texts if t).strip()
        if not text:
            finish_reason = candidates[0].get("finishReason")
            raise RuntimeError(
                f"Gemini returned empty text (finishReason={finish_reason})"
            )
        return text
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface unexpected schema drift
        raise RuntimeError(f"Unexpected Gemini response shape: {exc}") from exc


# In-memory chat history keyed by (question_id, test_id).
# Single-user assumption; not persisted across restarts.
_chat_histories = {}


def get_chat_history(chat_id):
    return _chat_histories.setdefault(chat_id, [])


def append_chat(chat_id, role, content, max_len=20):
    hist = get_chat_history(chat_id)
    hist.append({'role': role, 'content': content})
    if len(hist) > max_len:
        _chat_histories[chat_id] = hist[-max_len:]
