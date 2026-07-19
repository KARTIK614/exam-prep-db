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
        test_mode = request.form.get("test_mode", "practice")
        if test_mode not in {"practice", "exam"}:
            test_mode = "practice"

        # Negative marking is only meaningful in Exam Mode. The setup form now
        # ships a `neg_marking_preset` radio (none / third / quarter / fifth /
        # custom) instead of a separate on/off checkbox — "none" = disabled,
        # "custom" reads the freeform `negative_ratio` decimal. Defaults to
        # 1/3 (BCI/RPSC) when the preset field is missing.
        NEG_PRESETS = {
            "none": 0.0,
            "third": 1.0 / 3.0,
            "quarter": 0.25,
            "fifth": 0.20,
        }
        if test_mode == "exam":
            preset = (request.form.get("neg_marking_preset") or "third").strip().lower()
            if preset == "custom":
                try:
                    negative_ratio = float(
                        request.form.get("negative_ratio")
                        or (db.execute(
                            "SELECT value FROM settings WHERE key='default_neg_ratio'"
                        ).fetchone() or [None])[0]
                        or 0.333333
                    )
                except (TypeError, ValueError):
                    negative_ratio = 0.333333
            else:
                negative_ratio = NEG_PRESETS.get(preset, 1.0 / 3.0)
            # Clamp to [0, 1].
            negative_ratio = max(0.0, min(1.0, negative_ratio))
        else:
            negative_ratio = 0.0

        pyq_only = request.form.get("pyq_only") == "on"
        try:
            pyq_year_min = int(request.form.get("pyq_year_min") or 0) or None
        except ValueError:
            pyq_year_min = None
        try:
            pyq_year_max = int(request.form.get("pyq_year_max") or 0) or None
        except ValueError:
            pyq_year_max = None

        query = (
            "SELECT q.*, t.name as topic_name FROM questions q "
            "JOIN topics t ON q.topic_id = t.id "
            "WHERE (q.disabled IS NULL OR q.disabled = 0)"
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
        if pyq_only:
            query += " AND q.pyq_exam IS NOT NULL"
            if pyq_year_min is not None and pyq_year_max is not None:
                if pyq_year_min > pyq_year_max:
                    pyq_year_min, pyq_year_max = pyq_year_max, pyq_year_min
                query += " AND q.pyq_year BETWEEN ? AND ?"
                params.extend([pyq_year_min, pyq_year_max])
            elif pyq_year_min is not None:
                query += " AND q.pyq_year >= ?"
                params.append(pyq_year_min)
            elif pyq_year_max is not None:
                query += " AND q.pyq_year <= ?"
                params.append(pyq_year_max)

        all_qs = db.execute(query, params).fetchall()
        if len(all_qs) < num_qs:
            num_qs = len(all_qs)
        selected = random.sample(list(all_qs), min(num_qs, len(all_qs)))

        test_id = db.execute(
            'INSERT INTO mock_tests (started_at, paper, total_questions, max_score, status, '
            'test_mode, negative_ratio) '
            'VALUES (?,?,?,?,"in_progress",?,?)',
            (datetime.now().isoformat(), paper, len(selected), len(selected),
             test_mode, negative_ratio),
        ).lastrowid
        db.commit()

        session["test_id"] = test_id
        session["test_mode"] = test_mode
        session["negative_ratio"] = negative_ratio
        session["questions"] = [dict(q) for q in selected]
        session["current_q"] = 0
        session["responses"] = {}
        session["review_marks"] = {}
        session["q_start_time"] = time.time()

        return redirect(url_for("tests.take"))

    topics = db.execute("SELECT * FROM topics ORDER BY paper, subject").fetchall()

    # "Practice weakest" from the dashboard hero passes ?topic_id=<id>; the
    # template pre-checks that topic. Silently ignored if the id doesn't exist.
    prefill_ids = set()
    raw = request.args.get("topic_id")
    if raw:
        for tok in raw.split(","):
            tok = tok.strip()
            if tok.isdigit():
                prefill_ids.add(int(tok))

    # Bounds for the PYQ year range slider. Falls back to a sensible default
    # if the metadata columns exist but no rows have pyq_year populated yet.
    try:
        yr_row = db.execute(
            "SELECT MIN(pyq_year) AS lo, MAX(pyq_year) AS hi, COUNT(*) AS n "
            "FROM questions WHERE pyq_year IS NOT NULL"
        ).fetchone()
        pyq_year_lo = yr_row["lo"] if yr_row and yr_row["lo"] else 2005
        pyq_year_hi = yr_row["hi"] if yr_row and yr_row["hi"] else 2025
        pyq_count = yr_row["n"] if yr_row and yr_row["n"] else 0
    except Exception:  # noqa: BLE001 — column may not exist yet in dev DBs
        pyq_year_lo, pyq_year_hi, pyq_count = 2005, 2025, 0

    # Default negative-marking ratio from settings (⅓ per BCI standard).
    try:
        row = db.execute(
            "SELECT value FROM settings WHERE key='default_neg_ratio'"
        ).fetchone()
        default_neg_ratio = float(row["value"]) if row and row["value"] else 0.333333
    except Exception:  # noqa: BLE001 — settings table missing in dev is tolerable
        default_neg_ratio = 0.333333

    return render_template(
        "test_setup.html",
        topics=topics,
        pyq_year_lo=pyq_year_lo,
        pyq_year_hi=pyq_year_hi,
        pyq_count=pyq_count,
        default_neg_ratio=default_neg_ratio,
        prefill_topic_ids=prefill_ids,
    )


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
    review_marks = session.get("review_marks", {})
    questions = session.get("questions", [])
    test_mode = session.get("test_mode", "practice")

    # Look up the per-test negative_ratio. `negative_ratio` and `test_mode` are
    # both guaranteed to exist by the ALTER migrations in db.py + the Phase-4
    # migration script — schema errors will raise (Plan 00, not swallowed).
    row = db.execute(
        "SELECT negative_ratio, test_mode FROM mock_tests WHERE id=?", (test_id,)
    ).fetchone()
    stored_neg_ratio = 0.0
    if row is not None:
        try:
            stored_neg_ratio = float(row["negative_ratio"] or 0)
        except (TypeError, ValueError):
            stored_neg_ratio = 0.0
        db_mode = row["test_mode"] if "test_mode" in row.keys() else test_mode
        if db_mode:
            test_mode = db_mode

    total = len(questions)
    correct = sum(1 for r in responses.values() if r["is_correct"])
    wrong = sum(
        1 for r in responses.values()
        if not r["is_correct"] and r.get("selected")
    )
    unanswered = max(0, total - correct - wrong)

    # Score maths: raw_marks = correct − wrong × neg_ratio (Exam Mode only).
    # Practice Mode always shows raw accuracy without penalty.
    effective_ratio = stored_neg_ratio if test_mode == "exam" else 0.0
    raw_marks = correct - (wrong * effective_ratio)
    # Never clip below 0 for display sanity — some exams allow negative totals,
    # but for a percentage we floor at 0 so the score stat card doesn't go red-negative.
    score_pct = round(max(0.0, raw_marks) / total * 100, 1) if total > 0 else 0
    total_time = sum(r.get("time_spent", 0) for r in responses.values())

    # Migrations (init_db._run_alter_migrations + scripts/migrate_add_neg_marking_and_timer.py)
    # must have added raw_marks/wrong_count/unanswered_count. Per Plan 00, we do
    # NOT swallow schema errors — a missing column here means the migration
    # never ran, and we want the failure to be loud.
    db.execute(
        'UPDATE mock_tests SET completed_at=?, score=?, time_taken_sec=?, '
        'raw_marks=?, wrong_count=?, unanswered_count=?, '
        'status="completed" WHERE id=?',
        (datetime.now().isoformat(), score_pct, int(total_time),
         round(raw_marks, 2), wrong, unanswered, test_id),
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
            "time_spent_sec, error_type, marked_for_review, visit_count) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (test_id, r["question_id"], r["selected"], 1 if r["is_correct"] else 0,
             r.get("time_spent", 0), error_type,
             1 if review_marks.get(q_idx_str) else 0,
             int(r.get("visit_count", 1) or 1)),
        )

        if not r["is_correct"]:
            # Seed the Leitner queue: every fresh error starts in box 1 due
            # tomorrow. See sr.py for the schedule.
            from sr import next_due, next_box  # noqa: F401 — kept for future use
            db.execute(
                "INSERT INTO error_log (test_id, question_id, topic_id, selected_option, "
                "correct_option, error_type, created_at, sr_box, sr_due_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (test_id, r["question_id"], r.get("topic_id"), r["selected"], r["correct"],
                 error_type, datetime.now().isoformat(),
                 1, next_due(1)),
            )

    # Note: unanswered questions are NOT inserted into test_responses. This
    # preserves the historical invariant that `test_responses.is_correct = 0`
    # implies "attempted and wrong" (not "skipped"). Unanswered counts live on
    # `mock_tests.unanswered_count` for the results-page breakdown. A side
    # effect: mark-for-review flags on questions that were marked but never
    # answered are lost at finish time. Acceptable — palette is ephemeral.

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
        "test_id": test_id, "score": score_pct, "correct": correct, "total": total,
        "wrong": wrong, "unanswered": unanswered,
        "raw_marks": round(raw_marks, 2), "negative_ratio": effective_ratio,
        "time_taken": int(total_time),
        "paper": "I" if questions and questions[0].get("topic_name", "").startswith("Raj") else "II",
    }
    # Clear the in-progress review-marks flag so a fresh test starts clean.
    session.pop("review_marks", None)

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
