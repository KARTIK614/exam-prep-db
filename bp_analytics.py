"""Analytics dashboard blueprint."""
from datetime import datetime, timedelta
from flask import Blueprint, render_template

from db import get_db

bp = Blueprint("analytics", __name__)


@bp.route("/analytics")
def dashboard():
    db = get_db()

    progress = [dict(r) for r in db.execute(
        'SELECT id, date(completed_at) as d, paper, score, time_taken_sec '
        'FROM mock_tests WHERE status="completed" ORDER BY completed_at'
    ).fetchall()]

    topics_data = [dict(r) for r in db.execute(
        """
        SELECT t.name, t.subject, tm.current_score, tm.test_count, tm.status, t.weightage
        FROM topic_mastery tm JOIN topics t ON tm.topic_id = t.id
        ORDER BY t.paper, t.subject
        """
    ).fetchall()]

    paper1 = [dict(r) for r in db.execute(
        'SELECT id, score, time_taken_sec, date(completed_at) as d FROM mock_tests '
        'WHERE paper="I" AND status="completed" ORDER BY completed_at DESC LIMIT 5'
    ).fetchall()]
    paper2 = [dict(r) for r in db.execute(
        'SELECT id, score, time_taken_sec, date(completed_at) as d FROM mock_tests '
        'WHERE paper="II" AND status="completed" ORDER BY completed_at DESC LIMIT 5'
    ).fetchall()]

    error_trends = [dict(r) for r in db.execute(
        """
        SELECT date(el.created_at) as d, el.error_type, COUNT(*) as cnt
        FROM error_log el GROUP BY d, el.error_type ORDER BY d
        """
    ).fetchall()]

    time_trend = [dict(r) for r in db.execute(
        """
        SELECT mt.id, mt.paper, AVG(tr.time_spent_sec) as avg_time, mt.score
        FROM mock_tests mt JOIN test_responses tr ON mt.id = tr.test_id
        WHERE mt.status="completed" GROUP BY mt.id ORDER BY mt.completed_at
        """
    ).fetchall()]

    difficulty_stats = [dict(r) for r in db.execute(
        """
        SELECT q.difficulty,
            COUNT(CASE WHEN tr.is_correct=1 THEN 1 END) as correct,
            COUNT(*) as total
        FROM test_responses tr JOIN questions q ON tr.question_id = q.id
        GROUP BY q.difficulty
        """
    ).fetchall()]

    heatmap = []
    for i in range(30, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        day_data = db.execute(
            'SELECT COUNT(*) as tests, AVG(score) as avg FROM mock_tests '
            'WHERE date(completed_at)=? AND status="completed"',
            (d,),
        ).fetchone()
        heatmap.append({"date": d, "tests": day_data["tests"], "avg": round(day_data["avg"] or 0, 1)})

    settings = dict(db.execute("SELECT key, value FROM settings").fetchall())

    return render_template(
        "analytics.html",
        progress=progress, topics_data=topics_data, paper1=paper1, paper2=paper2,
        error_trends=error_trends, time_trend=time_trend, difficulty_stats=difficulty_stats,
        heatmap=heatmap, settings=settings,
    )
