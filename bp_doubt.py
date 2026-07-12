"""Doubt blueprint — AI deep-dive + follow-up chat. url_prefix='/api/doubt'."""
import json
import re
from datetime import datetime
from flask import Blueprint, request, jsonify

from db import get_db
from ai_utils import get_notes_context, call_gemini, get_chat_history, append_chat

bp = Blueprint("doubt", __name__)


@bp.route("/deep-dive", methods=["POST"])
def deep_dive():
    data = request.json
    question_id = data.get("question_id")
    test_id = data.get("test_id")

    if not question_id:
        return jsonify({"error": "question_id is required"}), 400

    cache_key = f"deep_dive:{question_id}:{test_id}"
    db = get_db()
    cached = db.execute(
        "SELECT response_json FROM doubt_cache WHERE cache_key=?", (cache_key,)
    ).fetchone()
    if cached:
        return jsonify({"analysis": json.loads(cached["response_json"]), "cached": True})

    q = db.execute(
        """
        SELECT q.*, t.name as topic_name, t.subject
        FROM questions q JOIN topics t ON q.topic_id = t.id
        WHERE q.id=?
        """,
        (question_id,),
    ).fetchone()
    if not q:
        return jsonify({"error": "Question not found"}), 404

    notes_ctx = get_notes_context(q["topic_name"], q["subject"], q["question_text"])

    storyline_instruction = ""
    if q["subject"] == "History":
        storyline_instruction = (
            "4. **Storyline** — A short memorable story or mnemonic (2-3 sentences) "
            "that makes these facts easy to recall."
        )

    prompt = f'''You are an expert tutor for Rajasthan competitive exams (Computer Anudeshak / Computer Instructor). Analyze this question deeply.

QUESTION: {q["question_text"][:500]}
TOPIC: {q["topic_name"]}
SUBJECT: {q["subject"]}
CORRECT ANSWER: {q["correct_option"]}
OFFICIAL EXPLANATION: {q["explanation"] or "None provided"}

RELEVANT STUDY NOTES:
{notes_ctx[:3000]}

Give a structured response with these exact sections:
1. **Concept Explanation** — 2-3 paragraphs explaining the concept in depth. Include background, context, and why the correct answer is right.
2. **Key Facts** — 3-5 bullet points of must-remember facts related to this topic.
3. **Exam Tips** — How this topic is typically tested, common traps, and what similar questions to expect.
{storyline_instruction}

Use markdown formatting. Keep each section concise but thorough. IMPORTANT: Write the ENTIRE response in English only. Do NOT use Hindi or any other language.'''

    response = call_gemini(prompt)

    analysis = {
        "explanation": "",
        "key_facts": [],
        "exam_tips": "",
        "storyline": "",
    }

    sections = re.split(
        r"\n(?=(?:###\s+)?\d+\.\s*(?:Concept|Key|Exam|Story))",
        response,
        flags=re.IGNORECASE,
    )
    if len(sections) <= 1:
        sections = response.split("\n---\n")

    for sec in sections:
        sec = sec.strip()
        heading_lower = sec.split("\n")[0].lower()

        if "concept explanation" in heading_lower or "concept" in heading_lower:
            analysis["explanation"] = re.sub(
                r"^(?:###\s+)?\d+\.\s*Concept[^)]*\)?\s*\n*", "", sec
            ).strip()
        elif "key fact" in heading_lower:
            body = re.sub(
                r"^(?:###\s+)?\d+\.\s*Key\s*Facts?[^)]*\)?\s*\n*", "", sec
            ).strip()
            lines = [l for l in body.split("\n") if l.strip() and not l.strip().startswith("---")]
            analysis["key_facts"] = [re.sub(r"^[*-]\s*", "", l).strip() for l in lines if l.strip()]
        elif "exam tip" in heading_lower:
            analysis["exam_tips"] = re.sub(
                r"^(?:###\s+)?\d+\.\s*Exam\s*Tips?[^)]*\)?\s*\n*", "", sec
            ).strip()
        elif "storyline" in heading_lower or "story" in heading_lower:
            analysis["storyline"] = re.sub(
                r"^(?:###\s+)?\d+\.\s*Storyline[^)]*\)?\s*\n*", "", sec
            ).strip()

    if not analysis["explanation"] and not analysis["key_facts"]:
        analysis["explanation"] = response

    db.execute(
        "INSERT INTO doubt_cache (cache_key, response_json, created_at) VALUES (?,?,?)",
        (cache_key, json.dumps(analysis), datetime.now().isoformat()),
    )
    db.commit()

    return jsonify({"analysis": analysis, "cached": False})


@bp.route("/chat", methods=["POST"])
def chat():
    data = request.json
    question_id = data.get("question_id")
    test_id = data.get("test_id")
    message = (data.get("message") or "").strip()

    if not question_id or not message:
        return jsonify({"error": "question_id and message are required"}), 400

    db = get_db()
    q = db.execute(
        """
        SELECT q.*, t.name as topic_name, t.subject
        FROM questions q JOIN topics t ON q.topic_id = t.id
        WHERE q.id=?
        """,
        (question_id,),
    ).fetchone()
    if not q:
        return jsonify({"error": "Question not found"}), 404

    cache_key = f"deep_dive:{question_id}:{test_id}"
    cached = db.execute(
        "SELECT response_json FROM doubt_cache WHERE cache_key=?", (cache_key,)
    ).fetchone()
    analysis_text = cached["response_json"][:2000] if cached else ""

    chat_id = f"{question_id}:{test_id}"
    history = get_chat_history(chat_id)[-6:]
    history_text = "\n".join(
        f"{'User' if h['role'] == 'user' else 'Tutor'}: {h['content']}" for h in history
    )

    prompt = f'''You are an expert tutor helping with Rajasthan Computer Anudeshak exam preparation.

TOPIC: {q["topic_name"]}
SUBJECT: {q["subject"]}
QUESTION: {q["question_text"][:300]}

PREVIOUS ANALYSIS SUMMARY:
{analysis_text[:1500]}

CONVERSATION SO FAR:
{history_text}

User's new question: {message}

Provide a clear, exam-focused answer. Reference study material and Rajasthan-specific context where relevant. Keep it 2-3 paragraphs. Use markdown. IMPORTANT: Write in English only. Do NOT use Hindi or any other language.'''

    response = call_gemini(prompt, timeout=45)

    append_chat(chat_id, "user", message)
    append_chat(chat_id, "assistant", response)

    return jsonify({"response": response})
