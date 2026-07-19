"""Analytics dashboard blueprint.

Phase 5 additions on top of the existing /analytics route:
  * Full mastery grid (18 tiles, grouped by paper).
  * Weakness heatmap: topic × difficulty (primary) + topic × recency (toggle).
  * Pacing benchmarks: user avg vs 5-test moving average vs target.
"""
from datetime import datetime, timedelta
from flask import Blueprint, render_template

from db import get_db

bp = Blueprint("analytics", __name__)


def _mastery_tiles(db, weak_threshold=60, target=75):
    """Same shape as bp_main._mastery_tiles — duplicated to keep blueprints
    independent (each computes its own tile view + tier)."""
    rows = [dict(r) for r in db.execute(
        """
        SELECT t.id AS topic_id, t.name, t.subject, t.paper,
               COALESCE(t.weightage, 5) AS weightage,
               tm.current_score, tm.diagnostic_score, tm.study_hours,
               tm.status, tm.last_studied,
               COALESCE(tm.test_count, 0) AS test_count
        FROM topics t
        LEFT JOIN topic_mastery tm ON tm.topic_id = t.id
        ORDER BY t.paper, t.name
        """
    ).fetchall()]

    today = datetime.now().date()
    for r in rows:
        r["days_since"] = None
        if r.get("last_studied"):
            try:
                d = datetime.fromisoformat(r["last_studied"][:19]).date()
                r["days_since"] = (today - d).days
            except (ValueError, TypeError):
                r["days_since"] = None

        current = r.get("current_score") or 0
        tc = r.get("test_count") or 0
        if tc == 0 or r.get("current_score") is None:
            r["tier"] = "untested"
        elif current < weak_threshold:
            r["tier"] = "weak"
        elif current < target:
            r["tier"] = "on_track"
        else:
            r["tier"] = "mastered"
    return rows


def _heatmap_by_difficulty(db):
    """Return {topic_id: {name, weightage, cells: {difficulty: {attempted,
    correct, accuracy}}}}, sorted by weightage DESC. Only topics with any
    attempts appear."""
    rows = db.execute(
        """
        SELECT t.id AS topic_id, t.name, COALESCE(t.weightage, 5) AS weightage,
               COALESCE(q.difficulty, 'medium') AS difficulty,
               COUNT(*) AS attempted,
               SUM(CASE WHEN tr.is_correct = 1 THEN 1 ELSE 0 END) AS correct
        FROM test_responses tr
        JOIN questions q ON tr.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        WHERE (q.disabled IS NULL OR q.disabled = 0)
        GROUP BY t.id, difficulty
        """
    ).fetchall()

    by_topic = {}
    for r in rows:
        tid = r["topic_id"]
        if tid not in by_topic:
            by_topic[tid] = {
                "topic_id": tid,
                "name": r["name"],
                "weightage": r["weightage"],
                "cells": {"easy": None, "medium": None, "hard": None},
            }
        attempted = int(r["attempted"] or 0)
        correct = int(r["correct"] or 0)
        acc = round(correct / attempted * 100, 1) if attempted else 0
        by_topic[tid]["cells"][r["difficulty"]] = {
            "attempted": attempted,
            "correct": correct,
            "accuracy": acc,
        }
    return sorted(by_topic.values(), key=lambda x: (-x["weightage"], x["name"]))


def _heatmap_by_recency(db):
    """Same shape as _heatmap_by_difficulty but bucketed by days-since-response."""
    rows = db.execute(
        """
        SELECT t.id AS topic_id, t.name, COALESCE(t.weightage, 5) AS weightage,
               CASE
                 WHEN julianday('now') - julianday(mt.completed_at) <= 7  THEN '0-7'
                 WHEN julianday('now') - julianday(mt.completed_at) <= 14 THEN '8-14'
                 WHEN julianday('now') - julianday(mt.completed_at) <= 30 THEN '15-30'
                 ELSE '30+'
               END AS bucket,
               COUNT(*) AS attempted,
               SUM(CASE WHEN tr.is_correct = 1 THEN 1 ELSE 0 END) AS correct
        FROM test_responses tr
        JOIN mock_tests mt ON tr.test_id = mt.id
        JOIN questions q ON tr.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        WHERE mt.status = 'completed' AND (q.disabled IS NULL OR q.disabled = 0)
        GROUP BY t.id, bucket
        """
    ).fetchall()

    buckets = ["0-7", "8-14", "15-30", "30+"]
    by_topic = {}
    for r in rows:
        tid = r["topic_id"]
        if tid not in by_topic:
            by_topic[tid] = {
                "topic_id": tid,
                "name": r["name"],
                "weightage": r["weightage"],
                "cells": {b: None for b in buckets},
            }
        attempted = int(r["attempted"] or 0)
        correct = int(r["correct"] or 0)
        acc = round(correct / attempted * 100, 1) if attempted else 0
        by_topic[tid]["cells"][r["bucket"]] = {
            "attempted": attempted,
            "correct": correct,
            "accuracy": acc,
        }
    return sorted(by_topic.values(), key=lambda x: (-x["weightage"], x["name"]))


def _pace_by_difficulty(db):
    """Mean seconds-per-question grouped by difficulty."""
    rows = db.execute(
        """
        SELECT COALESCE(q.difficulty, 'medium') AS difficulty,
               AVG(tr.time_spent_sec) AS avg_time,
               COUNT(*) AS n
        FROM test_responses tr
        JOIN questions q ON tr.question_id = q.id
        JOIN mock_tests mt ON tr.test_id = mt.id
        WHERE mt.status = 'completed'
        GROUP BY difficulty
        """
    ).fetchall()
    return [dict(r) for r in rows]


@bp.route("/analytics")
def dashboard():
    db = get_db()
    settings = dict(db.execute("SELECT key, value FROM settings").fetchall())
    try:
        weak_threshold = int(float(settings.get("weakness_threshold", 60)))
    except (TypeError, ValueError):
        weak_threshold = 60
    try:
        target = int(float(settings.get("target_score", 75)))
    except (TypeError, ValueError):
        target = 75
    try:
        target_sec = int(float(settings.get("target_seconds_per_q", 72)))
    except (TypeError, ValueError):
        target_sec = 72

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
        SELECT mt.id, mt.paper, AVG(tr.time_spent_sec) as avg_time, mt.score,
               date(mt.completed_at) AS d
        FROM mock_tests mt JOIN test_responses tr ON mt.id = tr.test_id
        WHERE mt.status="completed" GROUP BY mt.id ORDER BY mt.completed_at
        """
    ).fetchall()]

    # 5-test moving average of avg_time — Chart.js dataset.
    ma_pace = []
    window = 5
    for i in range(len(time_trend)):
        lo = max(0, i - window + 1)
        chunk = [t["avg_time"] for t in time_trend[lo:i + 1] if t.get("avg_time") is not None]
        ma_pace.append(round(sum(chunk) / len(chunk), 2) if chunk else None)

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

    # Phase 5 additions.
    tiles = _mastery_tiles(db, weak_threshold=weak_threshold, target=target)
    # Group tiles by paper for the analytics view.
    tiles_by_paper = {}
    for t in tiles:
        p = t.get("paper") or "?"
        tiles_by_paper.setdefault(p, []).append(t)
    # Within each paper, sort by tier priority then weightage.
    tier_priority = {"weak": 0, "on_track": 1, "untested": 2, "mastered": 3}
    for p in tiles_by_paper:
        tiles_by_paper[p].sort(key=lambda r: (
            tier_priority.get(r["tier"], 9),
            -(r.get("weightage") or 5),
            r.get("name") or "",
        ))
    paper_keys = sorted(tiles_by_paper.keys())

    heatmap_diff = _heatmap_by_difficulty(db)
    heatmap_recency = _heatmap_by_recency(db)
    pace_diff = _pace_by_difficulty(db)

    # Slow-and-wrong top 10 (Plan C §4c).
    try:
        slow_wrong = [dict(r) for r in db.execute(
            """
            SELECT q.id AS question_id, q.question_text, q.difficulty,
                   tr.time_spent_sec, t.name AS topic
            FROM test_responses tr
            JOIN questions q ON tr.question_id = q.id
            JOIN topics t ON q.topic_id = t.id
            WHERE tr.is_correct = 0 AND tr.time_spent_sec > 2 * ?
            ORDER BY tr.time_spent_sec DESC
            LIMIT 10
            """,
            (target_sec,),
        ).fetchall()]
    except Exception:  # noqa: BLE001
        slow_wrong = []

    return render_template(
        "analytics.html",
        progress=progress, topics_data=topics_data, paper1=paper1, paper2=paper2,
        error_trends=error_trends, time_trend=time_trend, difficulty_stats=difficulty_stats,
        heatmap=heatmap, settings=settings,
        # Phase 5:
        tiles_by_paper=tiles_by_paper,
        paper_keys=paper_keys,
        heatmap_diff=heatmap_diff,
        heatmap_recency=heatmap_recency,
        pace_diff=pace_diff,
        ma_pace=ma_pace,
        target_sec=target_sec,
        weak_threshold=weak_threshold,
        target_score=target,
        slow_wrong=slow_wrong,
    )
