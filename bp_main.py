"""Main blueprint — the / dashboard."""
from datetime import datetime, timedelta
from flask import Blueprint, render_template

from db import get_db

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    db = get_db()
    tests = db.execute(
        'SELECT COUNT(*) as total, AVG(score) as avg_score, SUM(time_taken_sec) as total_time '
        'FROM mock_tests WHERE status="completed"'
    ).fetchone()
    last_test = db.execute(
        'SELECT * FROM mock_tests WHERE status="completed" '
        'ORDER BY completed_at DESC LIMIT 1'
    ).fetchone()

    topics = db.execute(
        """
        SELECT tm.*, t.name, t.subject, t.paper, t.weightage
        FROM topic_mastery tm JOIN topics t ON tm.topic_id = t.id
        ORDER BY tm.current_score ASC NULLS FIRST
        """
    ).fetchall()

    weak_topics = [t for t in topics if (t["current_score"] or 0) < 60 and t["test_count"] > 0]
    strong_topics = [t for t in topics if (t["current_score"] or 0) >= 70]
    untested = [t for t in topics if t["test_count"] == 0]

    recent_errors = db.execute(
        """
        SELECT el.*, t.name as topic_name, q.question_text
        FROM error_log el JOIN topics t ON el.topic_id = t.id
        JOIN questions q ON el.question_id = q.id
        WHERE el.resolved = 0 ORDER BY el.created_at DESC LIMIT 10
        """
    ).fetchall()

    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    weekly_tests = db.execute(
        'SELECT date(completed_at) as d, AVG(score) as avg FROM mock_tests '
        'WHERE status="completed" AND completed_at >= ? GROUP BY d ORDER BY d',
        (week_ago,),
    ).fetchall()

    error_dist = db.execute(
        "SELECT error_type, COUNT(*) as cnt FROM error_log GROUP BY error_type ORDER BY cnt DESC"
    ).fetchall()

    paper_perf = db.execute(
        'SELECT paper, COUNT(*) as tests, AVG(score) as avg FROM mock_tests '
        'WHERE status="completed" GROUP BY paper'
    ).fetchall()

    settings = dict(db.execute("SELECT key, value FROM settings").fetchall())

    return render_template(
        "index.html",
        tests=tests,
        last_test=last_test,
        weak_topics=weak_topics,
        strong_topics=strong_topics,
        untested=untested,
        recent_errors=recent_errors,
        weekly_tests=weekly_tests,
        error_dist=error_dist,
        paper_perf=paper_perf,
        settings=settings,
    )
