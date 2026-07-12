"""API blueprint — small JSON endpoints for the frontend. url_prefix='/api'."""
import time
from datetime import datetime
from flask import Blueprint, request, jsonify, session, g

from db import get_db

bp = Blueprint("api", __name__)

FLAG_CATEGORIES = {"data_inconsistency", "bad_latex", "typo", "wrong_answer", "other"}


@bp.route("/flag_question", methods=["POST"])
def flag_question():
    """Report an issue with a question during a test. Doesn't affect scoring."""
    data = request.json or {}
    question_id = data.get("question_id")
    category = data.get("category", "other")
    note = (data.get("note") or "").strip()[:1000]
    test_id = data.get("test_id") or session.get("test_id")

    if not question_id:
        return jsonify({"error": "question_id is required"}), 400
    if category not in FLAG_CATEGORIES:
        category = "other"

    db = get_db()
    db.execute(
        "INSERT INTO question_flags (question_id, test_id, reporter, category, note, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'open', ?)",
        (
            int(question_id),
            int(test_id) if test_id else None,
            getattr(g, "user", None),
            category,
            note,
            datetime.utcnow().isoformat(),
        ),
    )
    db.commit()
    return jsonify({"status": "ok"})


@bp.route("/question/<int:idx>")
def get_question(idx):
    if "questions" not in session or idx >= len(session["questions"]):
        return jsonify({"error": "Invalid index"}), 404
    q = session["questions"][idx]
    session["current_q"] = idx
    session["q_start_time"] = time.time()
    session.modified = True
    return jsonify({
        "id": q["id"], "text": q["question_text"],
        "options": [q["option_a"], q["option_b"], q["option_c"], q["option_d"]],
        "index": idx, "total": len(session["questions"]),
        "topic": q.get("topic_name", ""),
        "difficulty": q.get("difficulty", "medium"),
    })


@bp.route("/submit_answer", methods=["POST"])
def submit_answer():
    data = request.json
    q_idx = data.get("question_index", session.get("current_q", 0))
    selected = data.get("selected_option")
    time_spent = data.get("time_spent", 0)

    if "questions" not in session or q_idx >= len(session["questions"]):
        return jsonify({"error": "Invalid"}), 400

    q = session["questions"][q_idx]
    is_correct = (selected == q["correct_option"])

    session["responses"][str(q_idx)] = {
        "question_id": q["id"],
        "selected": selected,
        "correct": q["correct_option"],
        "is_correct": is_correct,
        "time_spent": time_spent,
        "topic_id": q.get("topic_id"),
        "topic_name": q.get("topic_name", ""),
    }
    session["current_q"] = q_idx
    session.modified = True

    return jsonify({
        "is_correct": is_correct,
        "correct_option": q["correct_option"],
        "explanation": q.get("explanation", ""),
        "answered": len(session["responses"]),
        "total": len(session["questions"]),
    })


@bp.route("/resolve_error", methods=["POST"])
def resolve_error():
    data = request.json
    db = get_db()
    db.execute(
        "UPDATE error_log SET resolved=1, root_cause=? WHERE id=?",
        (data.get("root_cause", ""), data["error_id"]),
    )
    db.commit()
    return jsonify({"status": "ok"})


@bp.route("/redo_error", methods=["POST"])
def redo_error():
    data = request.json
    db = get_db()
    field = "redo_1_score" if data.get("attempt") == 1 else "redo_2_score"
    db.execute(f"UPDATE error_log SET {field}=? WHERE id=?", (data["score"], data["error_id"]))
    db.commit()
    return jsonify({"status": "ok"})


@bp.route("/settings", methods=["POST"])
def update_settings():
    data = request.json
    db = get_db()
    for k, v in data.items():
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (k, str(v)))
    db.commit()
    return jsonify({"status": "ok"})


@bp.route("/study_session", methods=["POST"])
def log_study_session():
    data = request.json
    db = get_db()
    db.execute(
        "INSERT INTO study_sessions (date, topic_id, duration_min, mcqs_solved, score, notes) "
        "VALUES (?,?,?,?,?,?)",
        (datetime.now().isoformat(), data["topic_id"], data["duration"], data["mcqs"],
         data.get("score", 0), data.get("notes", "")),
    )
    db.execute(
        "UPDATE topic_mastery SET study_hours = study_hours + ? WHERE topic_id = ?",
        (data["duration"] / 60.0, data["topic_id"]),
    )
    db.commit()
    return jsonify({"status": "ok"})
