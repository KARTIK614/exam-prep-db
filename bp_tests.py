"""Tests blueprint — /test/setup, /test/take, /test/finish, /results/<id>."""
import random
import time
from datetime import datetime
from flask import (
    Blueprint, request, render_template, redirect, url_for, session,
)

from db import get_db

bp = Blueprint("tests", __name__)


@bp.route("/test/setup", methods=["GET", "POST"])
def setup():
    db = get_db()
    if request.method == "POST":
        paper = request.form.get("paper", "II")
        num_qs = int(request.form.get("num_questions", 50))
        topics_str = request.form.get("topics", "")
        difficulty = request.form.get("difficulty", "all")
        focus_weak = request.form.get("focus_weak") == "on"

        query = (
            "SELECT q.*, t.name as topic_name FROM questions q "
            "JOIN topics t ON q.topic_id = t.id WHERE 1=1"
        )
        params = []

        if paper != "both":
            query += " AND t.paper = ?"
            params.append(paper)
        if topics_str:
            topic_ids = [x.strip() for x in topics_str.split(",") if x.strip()]
            placeholders = ",".join("?" * len(topic_ids))
            query += f" AND t.id IN ({placeholders})"
            params.extend(topic_ids)
        if difficulty != "all":
            query += " AND q.difficulty = ?"
            params.append(difficulty)
        if focus_weak:
            weak_topic_ids = [
                str(t["topic_id"]) for t in db.execute(
                    "SELECT topic_id FROM topic_mastery "
                    "WHERE current_score < 60 OR current_score IS NULL"
                ).fetchall()
            ]
            if weak_topic_ids:
                query += f' AND t.id IN ({",".join(weak_topic_ids)})'

        all_qs = db.execute(query, params).fetchall()
        if len(all_qs) < num_qs:
            num_qs = len(all_qs)
        selected = random.sample(list(all_qs), min(num_qs, len(all_qs)))

        test_id = db.execute(
            'INSERT INTO mock_tests (started_at, paper, total_questions, max_score, status) '
            'VALUES (?,?,?,?,"in_progress")',
            (datetime.now().isoformat(), paper, len(selected), len(selected)),
        ).lastrowid
        db.commit()

        session["test_id"] = test_id
        session["questions"] = [dict(q) for q in selected]
        session["current_q"] = 0
        session["responses"] = {}
        session["q_start_time"] = time.time()

        return redirect(url_for("tests.take"))

    topics = db.execute("SELECT * FROM topics ORDER BY paper, subject").fetchall()
    return render_template("test_setup.html", topics=topics)


@bp.route("/test/take")
def take():
    if "test_id" not in session or "questions" not in session or not session["questions"]:
        session.pop("test_id", None)
        session.pop("questions", None)
        return redirect(url_for("tests.setup"))
    return render_template(
        "test.html",
        questions=session["questions"],
        current=session["current_q"],
        total=len(session["questions"]),
        test_id=session["test_id"],
    )


@bp.route("/test/finish", methods=["POST"])
def finish():
    if "test_id" not in session:
        return redirect(url_for("main.index"))

    db = get_db()
    test_id = session["test_id"]
    responses = session.get("responses", {})
    questions = session.get("questions", [])

    correct = sum(1 for r in responses.values() if r["is_correct"])
    total = len(questions)
    score = round((correct / total * 100) if total > 0 else 0, 1)
    total_time = sum(r.get("time_spent", 0) for r in responses.values())

    db.execute(
        'UPDATE mock_tests SET completed_at=?, score=?, time_taken_sec=?, '
        'status="completed" WHERE id=?',
        (datetime.now().isoformat(), score, int(total_time), test_id),
    )

    for q_idx_str, r in responses.items():
        q_idx = int(q_idx_str)
        error_type = None
        if not r["is_correct"]:
            if r.get("time_spent", 0) < 10:
                error_type = "time_pressure"
            else:
                error_type = "concept_gap"

        db.execute(
            "INSERT INTO test_responses (test_id, question_id, selected_option, is_correct, "
            "time_spent_sec, error_type) VALUES (?,?,?,?,?,?)",
            (test_id, r["question_id"], r["selected"], 1 if r["is_correct"] else 0,
             r.get("time_spent", 0), error_type),
        )

        if not r["is_correct"]:
            db.execute(
                "INSERT INTO error_log (test_id, question_id, topic_id, selected_option, "
                "correct_option, error_type, created_at) VALUES (?,?,?,?,?,?,?)",
                (test_id, r["question_id"], r.get("topic_id"), r["selected"], r["correct"],
                 error_type, datetime.now().isoformat()),
            )

    topic_scores = {}
    for r in responses.values():
        tid = r.get("topic_id")
        if tid not in topic_scores:
            topic_scores[tid] = {"correct": 0, "total": 0}
        topic_scores[tid]["total"] += 1
        if r["is_correct"]:
            topic_scores[tid]["correct"] += 1

    for tid, scores in topic_scores.items():
        pct = round(scores["correct"] / scores["total"] * 100, 1)
        existing = db.execute("SELECT * FROM topic_mastery WHERE topic_id=?", (tid,)).fetchone()
        if existing:
            new_score = (
                round((existing["current_score"] or 0) * 0.6 + pct * 0.4, 1)
                if existing["current_score"] else pct
            )
            db.execute(
                "UPDATE topic_mastery SET current_score=?, test_count=test_count+1, "
                "last_studied=?, status=? WHERE topic_id=?",
                (new_score, datetime.now().isoformat(),
                 "in_progress" if new_score < 70 else "stable", tid),
            )
        else:
            db.execute(
                "INSERT INTO topic_mastery (topic_id, current_score, test_count, status, last_studied) "
                "VALUES (?,?,1,?,?)",
                (tid, pct, "in_progress" if pct < 70 else "stable", datetime.now().isoformat()),
            )

    db.commit()

    session["last_result"] = {
        "test_id": test_id, "score": score, "correct": correct, "total": total,
        "time_taken": int(total_time),
        "paper": "I" if questions and questions[0].get("topic_name", "").startswith("Raj") else "II",
    }

    return redirect(url_for("tests.results", test_id=test_id))


@bp.route("/results/<int:test_id>")
def results(test_id):
    db = get_db()
    test = db.execute("SELECT * FROM mock_tests WHERE id=?", (test_id,)).fetchone()
    if not test:
        return redirect(url_for("main.index"))

    responses = db.execute(
        """
        SELECT tr.*, q.question_text, q.correct_option, q.explanation,
               q.option_a, q.option_b, q.option_c, q.option_d,
               t.name as topic_name, t.subject as subject
        FROM test_responses tr JOIN questions q ON tr.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        WHERE tr.test_id=? ORDER BY tr.id
        """,
        (test_id,),
    ).fetchall()

    timings = [r["time_spent_sec"] for r in responses]
    avg_time = sum(timings) / len(timings) if timings else 0
    fastest = min(timings) if timings else 0
    slowest = max(timings) if timings else 0

    topic_breakdown = {}
    for r in responses:
        tn = r["topic_name"]
        if tn not in topic_breakdown:
            topic_breakdown[tn] = {"correct": 0, "total": 0, "total_time": 0}
        topic_breakdown[tn]["total"] += 1
        topic_breakdown[tn]["total_time"] += r["time_spent_sec"] or 0
        if r["is_correct"]:
            topic_breakdown[tn]["correct"] += 1

    errors = [r for r in responses if not r["is_correct"]]
    error_types = {"concept_gap": 0, "memory_lapse": 0, "misread": 0, "calculation": 0, "time_pressure": 0}
    for e in errors:
        et = e["error_type"] or "concept_gap"
        if et in error_types:
            error_types[et] += 1

    n = len(responses)
    early = [r for r in responses if r["id"] <= n * 0.33]
    mid = [r for r in responses if n * 0.33 < r["id"] <= n * 0.66]
    late = [r for r in responses if r["id"] > n * 0.66]

    return render_template(
        "results.html", test=test, responses=responses,
        avg_time=avg_time, fastest=fastest, slowest=slowest,
        topic_breakdown=topic_breakdown, errors=errors, error_types=error_types,
        early=early, mid=mid, late=late,
    )
