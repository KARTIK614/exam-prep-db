"""API blueprint — small JSON endpoints for the frontend. url_prefix='/api'."""
import time
from datetime import datetime
from flask import Blueprint, request, jsonify, session, g

from db import get_db

bp = Blueprint("api", __name__)

FLAG_CATEGORIES = {
    "wrong_answer",         # answer key is wrong
    "ambiguous",            # multiple correct or no correct
    "typo_question",        # typo in question stem
    "typo_options",         # typo in options
    "explanation_missing",  # explanation empty/wrong
    "duplicate",            # this Q already exists
    "other",                # freeform reason in note
}


@bp.route("/flag_question", methods=["POST"])
def flag_question():
    """Report an issue with a question during a test. Doesn't affect scoring."""
    data = request.json or {}
    question_id = data.get("question_id")
    category = data.get("category")
    note = (data.get("note") or "").strip()[:1000]
    test_id = data.get("test_id") or session.get("test_id")

    if not question_id:
        return jsonify({"error": "question_id is required"}), 400
    if not category or category not in FLAG_CATEGORIES:
        return jsonify({"error": f"category must be one of {sorted(FLAG_CATEGORIES)}"}), 400
    if category == "other" and not note:
        return jsonify({"error": "note is required when category is 'other'"}), 400

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

    # Track visit_count for post-hoc analytics of flip-flopping.
    responses = session.setdefault("responses", {})
    key = str(idx)
    if key in responses:
        responses[key]["visit_count"] = int(responses[key].get("visit_count", 1) or 1) + 1
    session.modified = True

    # Cheap single-row bookmark lookup — the unique index makes this O(log n).
    bookmarked = False
    try:
        row = get_db().execute(
            "SELECT 1 FROM bookmarks WHERE question_id = ? LIMIT 1", (q["id"],)
        ).fetchone()
        bookmarked = row is not None
    except Exception:  # noqa: BLE001 — bookmarks table may not exist in dev DBs
        pass

    review_marks = session.get("review_marks", {}) or {}
    return jsonify({
        "id": q["id"], "text": q["question_text"],
        "options": [q["option_a"], q["option_b"], q["option_c"], q["option_d"]],
        "index": idx, "total": len(session["questions"]),
        "topic": q.get("topic_name", ""),
        "difficulty": q.get("difficulty", "medium"),
        "bookmarked": bookmarked,
        "marked_for_review": bool(review_marks.get(key)),
        "test_mode": session.get("test_mode", "practice"),
    })


@bp.route("/mark_for_review", methods=["POST"])
def mark_for_review():
    """Toggle the marked-for-review flag on the current question. Stored in
    session until /test/finish flushes it to the test_responses row."""
    if "questions" not in session:
        return jsonify({"error": "No active test"}), 400
    data = request.json or {}
    try:
        idx = int(data.get("question_index", session.get("current_q", 0)))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid question_index"}), 400
    if idx < 0 or idx >= len(session["questions"]):
        return jsonify({"error": "Invalid question_index"}), 400

    marks = session.setdefault("review_marks", {})
    key = str(idx)
    marks[key] = not marks.get(key, False)
    session.modified = True
    return jsonify({"marked": bool(marks[key]), "question_index": idx})


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


@bp.route("/bookmark/<int:qid>", methods=["POST"])
def toggle_bookmark(qid):
    """Idempotent bookmark toggle. Returns {"bookmarked": bool}."""
    db = get_db()
    existing = db.execute(
        "SELECT id FROM bookmarks WHERE question_id = ?", (qid,)
    ).fetchone()
    if existing:
        db.execute("DELETE FROM bookmarks WHERE question_id = ?", (qid,))
        db.commit()
        return jsonify({"status": "removed", "bookmarked": False})
    db.execute(
        "INSERT INTO bookmarks (question_id, created_at) VALUES (?, ?)",
        (qid, datetime.utcnow().isoformat()),
    )
    db.commit()
    return jsonify({"status": "added", "bookmarked": True})


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
