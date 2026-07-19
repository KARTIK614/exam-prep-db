"""Main blueprint — the / dashboard.

Phase 5 additions:
  * Mastery grid — 18 tiles keyed by tier (weak / on_track / mastered / untested)
    plus weightage badge + recency meta.
  * Consistency score — 28-day rolling / 20-day denominator (Plan C §2).
  * Next weak topic — gap × weightage × recency × confidence picker (Plan C §3).
  * SR "N due today" pill — pulled from `error_log.sr_due_at` via sr.py.

Phase 7 additions:
  * Global question search — /search (page) + /api/search (JSON) using
    the FTS5 virtual table set up in db.py, with LIKE fallback if FTS5
    isn't available on the current build.
  * Bookmarks list stays here.
"""
from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, render_template, request

from db import get_db

bp = Blueprint("main", __name__)


# ─── Next-weak-topic ranker (Plan C §3) ─────────────────────────────────────
def _rank_next_topic(topics, target=75):
    """Return the top-3 topic dicts with a `next_score` + `reason` field.

    Scoring (Plan C §3):
        score = gap × weightage × recency × confidence
      where
        gap        = max(0, target - current_score)
        recency    = 0.3 (<3 days), 0.7 (<7), 1.0 (>=7)
        confidence = min(1.0, test_count / 5)   # damp untrusted low scores

    Untested topics (test_count == 0) get `weightage * 2.0` — a boost so we
    surface unexplored high-weight territory before over-tuning known-weak.
    """
    scored = []
    for t in topics:
        score, reason = _score_topic(t, target=target)
        if score <= 0:
            continue
        scored.append({**t, "next_score": score, "reason": reason})
    scored.sort(key=lambda r: r["next_score"], reverse=True)
    return scored


def _score_topic(t, target=75):
    """Return (score, human-readable reason). Score can be 0 (skip)."""
    weightage = t.get("weightage") or 5
    test_count = t.get("test_count") or 0
    current = t.get("current_score") or 0
    days = t.get("days_since")
    if days is None:
        days = 9999

    if test_count == 0:
        score = weightage * 2.0
        reason = f"untested &middot; {weightage} exam pts if mastered"
        return score, reason

    # Recently studied → don't cram same topic.
    if days < 1:
        return 0, ""
    if days < 3:
        recency = 0.3
    elif days < 7:
        recency = 0.7
    else:
        recency = 1.0

    gap = max(0, target - current)
    if gap <= 0:
        return 0, ""

    confidence = min(1.0, test_count / 5.0)
    score = gap * weightage * recency * confidence
    # Rough "exam points if you close the gap" — gap/100 × weightage.
    est_points = round((gap / 100.0) * weightage, 1)
    reason = (
        f"current {int(current)}% &middot; weight {weightage} &middot; "
        f"studied {int(days)}d ago &middot; could gain +{est_points} exam pts"
    )
    return score, reason


def _consistency(db, days_window=28, denom=20):
    """Return (score_int, active_days_int, activity_28d_list).

    A day counts if there is either a completed mock_test OR a study_session
    with duration_min >= 10 (per Plan C §2). Denominator 20 makes 5 study
    days/week hit 100 %.
    """
    today = date.today()
    start = today - timedelta(days=days_window - 1)

    days_active = set()
    try:
        rows = db.execute(
            "SELECT DISTINCT date(completed_at) AS d FROM mock_tests "
            "WHERE status='completed' AND date(completed_at) >= ?",
            (start.isoformat(),),
        ).fetchall()
        for r in rows:
            if r and r[0]:
                days_active.add(r[0])
    except Exception:  # noqa: BLE001
        pass

    try:
        rows = db.execute(
            "SELECT DISTINCT date(date) AS d FROM study_sessions "
            "WHERE date(date) >= ? AND COALESCE(duration_min, 0) >= 10",
            (start.isoformat(),),
        ).fetchall()
        for r in rows:
            if r and r[0]:
                days_active.add(r[0])
    except Exception:  # noqa: BLE001
        pass

    active_count = len(days_active)
    score = min(100, int(round(active_count * (100.0 / denom))))

    activity = []
    for i in range(days_window):
        d = (start + timedelta(days=i)).isoformat()
        has = d in days_active
        activity.append({"date": d, "has_activity": has})

    return score, active_count, activity


def _sr_due_count(db):
    """Return count of SR cards due today, or 0 on any error (fresh dev DB)."""
    try:
        r = db.execute(
            "SELECT COUNT(*) FROM error_log el JOIN questions q ON q.id=el.question_id "
            "WHERE (q.disabled IS NULL OR q.disabled = 0) "
            "AND date(el.sr_due_at) <= date('now')"
        ).fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


def _mastery_tiles(db, weak_threshold=60, target=75):
    """Return every topic × mastery join with computed `tier` + `days_since`.

    Uses LEFT JOIN so untested topics still appear. Sorted by
    (tier priority, weightage DESC) so weak/high-value tiles float up.
    """
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


@bp.route("/")
def index():
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

    tests = db.execute(
        'SELECT COUNT(*) as total, AVG(score) as avg_score, SUM(time_taken_sec) as total_time '
        'FROM mock_tests WHERE status="completed"'
    ).fetchone()
    last_test = db.execute(
        'SELECT * FROM mock_tests WHERE status="completed" '
        'ORDER BY completed_at DESC LIMIT 1'
    ).fetchone()

    tiles = _mastery_tiles(db, weak_threshold=weak_threshold, target=target)

    # Grid sort: weak → on_track → untested → mastered, weightage DESC in each.
    tier_priority = {"weak": 0, "on_track": 1, "untested": 2, "mastered": 3}
    tiles.sort(key=lambda r: (
        tier_priority.get(r["tier"], 9),
        -(r.get("weightage") or 5),
        r.get("name") or "",
    ))

    weak_topics = [t for t in tiles if t["tier"] == "weak"]
    untested = [t for t in tiles if t["tier"] == "untested"]

    # Next-weak-topic recommendation (top-3).
    next_topics = _rank_next_topic(tiles, target=target)[:3]

    # Consistency (28-day / 20-day denom, Plan C §2).
    consistency_score, active_days, activity_28d = _consistency(db)

    # SR pill count.
    sr_due_today = _sr_due_count(db)

    recent_errors = db.execute(
        """
        SELECT el.*, t.name as topic_name, q.question_text
        FROM error_log el JOIN topics t ON el.topic_id = t.id
        JOIN questions q ON el.question_id = q.id
        WHERE el.resolved = 0 ORDER BY el.created_at DESC LIMIT 10
        """
    ).fetchall()

    error_dist = db.execute(
        "SELECT error_type, COUNT(*) as cnt FROM error_log GROUP BY error_type ORDER BY cnt DESC"
    ).fetchall()

    paper_perf = db.execute(
        'SELECT paper, COUNT(*) as tests, AVG(score) as avg FROM mock_tests '
        'WHERE status="completed" GROUP BY paper'
    ).fetchall()

    return render_template(
        "index.html",
        tests=tests,
        last_test=last_test,
        tiles=tiles,
        weak_topics=weak_topics,
        untested=untested,
        next_topics=next_topics,
        consistency_score=consistency_score,
        active_days=active_days,
        activity_28d=activity_28d,
        sr_due_today=sr_due_today,
        recent_errors=recent_errors,
        error_dist=error_dist,
        paper_perf=paper_perf,
        settings=settings,
        weak_threshold=weak_threshold,
        target_score=target,
    )


@bp.route("/bookmarks")
def bookmarks():
    """List starred questions with topic + a short preview."""
    db = get_db()
    try:
        rows = db.execute(
            """
            SELECT b.id AS bookmark_id, b.created_at, b.note,
                   q.id AS question_id, q.question_text, q.difficulty,
                   t.name AS topic_name, t.subject AS subject, t.paper AS paper
            FROM bookmarks b
            JOIN questions q ON q.id = b.question_id
            LEFT JOIN topics t ON t.id = q.topic_id
            WHERE (q.disabled IS NULL OR q.disabled = 0)
            ORDER BY b.created_at DESC
            """
        ).fetchall()
    except Exception as e:  # noqa: BLE001 — table may not exist in a fresh dev DB
        rows = []
        print(f"[bookmarks] query failed: {e}")

    return render_template("bookmarks.html", bookmarks=rows)


# ─── Global search (Plan E §2.18) ───────────────────────────────────────────

def _fts5_available(db):
    """Cheap probe — does the questions_fts virtual table exist?"""
    try:
        r = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='questions_fts'"
        ).fetchone()
        return bool(r)
    except Exception:  # noqa: BLE001
        return False


def _search_topics(db):
    """Load topic list for the filter dropdown."""
    try:
        return db.execute(
            "SELECT id, name, paper FROM topics ORDER BY paper, name"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []


@bp.route("/search")
def search_page():
    """Standalone search page — also reachable via Cmd/Ctrl-K modal on any page."""
    db = get_db()
    topics = _search_topics(db)
    q = (request.args.get("q") or "").strip()
    return render_template("search.html", topics=topics, initial_query=q)


def _sanitize_fts_query(raw):
    """Turn a user query into an FTS5 MATCH string.

    Simple rule: split on whitespace, strip FTS5 punctuation, wrap each token
    in double-quotes so hyphens and other operators are treated as literals.
    Append `*` for prefix matching on the last token so partial queries work
    while typing.
    """
    if not raw:
        return ""
    # Drop chars FTS5 treats as operators; keep alnum + a few safe ones.
    import re
    tokens = re.findall(r"[A-Za-z0-9]+", raw)
    if not tokens:
        return ""
    # Quote each token; add prefix wildcard on last for autocomplete feel.
    quoted = [f'"{t}"' for t in tokens[:-1]]
    quoted.append(f'"{tokens[-1]}"*')
    return " ".join(quoted)


@bp.route("/api/search")
def api_search():
    """JSON search endpoint. Returns {total, results:[{id, topic_name, ...}]}.

    Query params:
      q          text query (required, min 2 chars)
      topic_id   filter by topic
      difficulty filter (easy/medium/hard)
      confidence filter (Plan D column — safe if absent)
      pyq_exam   filter (Plan D column — safe if absent)
      pyq_year   filter (Plan D column — safe if absent)
      limit      default 20, max 100
      offset     default 0
    """
    db = get_db()
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"total": 0, "results": [], "error": "query too short"})

    try:
        limit = max(1, min(100, int(request.args.get("limit", 20))))
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0

    topic_id = request.args.get("topic_id")
    difficulty = request.args.get("difficulty")
    confidence = request.args.get("confidence")
    pyq_exam = request.args.get("pyq_exam")
    pyq_year = request.args.get("pyq_year")

    filters_sql = []
    filters_args = []
    if topic_id and topic_id.isdigit():
        filters_sql.append("q.topic_id = ?")
        filters_args.append(int(topic_id))
    if difficulty in ("easy", "medium", "hard"):
        filters_sql.append("q.difficulty = ?")
        filters_args.append(difficulty)
    # Optional Plan D columns — wrap in try to be resilient.
    if confidence in ("high", "medium", "low"):
        filters_sql.append("COALESCE(q.confidence, '') = ?")
        filters_args.append(confidence)
    if pyq_exam:
        filters_sql.append("COALESCE(q.pyq_exam, '') = ?")
        filters_args.append(pyq_exam)
    if pyq_year and pyq_year.isdigit():
        filters_sql.append("COALESCE(q.pyq_year, 0) = ?")
        filters_args.append(int(pyq_year))
    filters_sql.append("(q.disabled IS NULL OR q.disabled = 0)")
    where_extra = " AND " + " AND ".join(filters_sql)

    results = []
    total = 0

    if _fts5_available(db):
        fts_q = _sanitize_fts_query(q)
        if not fts_q:
            return jsonify({"total": 0, "results": []})

        # Count
        try:
            count_sql = (
                "SELECT COUNT(*) FROM questions_fts "
                "JOIN questions q ON q.id = questions_fts.rowid "
                "LEFT JOIN topics t ON t.id = q.topic_id "
                "WHERE questions_fts MATCH ?" + where_extra
            )
            row = db.execute(count_sql, [fts_q] + filters_args).fetchone()
            total = int(row[0]) if row else 0
        except Exception as e:  # noqa: BLE001
            print(f"[search count fallback] {e}")
            return _like_fallback(db, q, filters_sql, filters_args, limit, offset)

        # Rows
        try:
            sql = (
                "SELECT q.id, q.question_text, q.difficulty, q.correct_option, "
                "q.option_a, q.option_b, q.option_c, q.option_d, "
                "t.name AS topic_name, "
                "snippet(questions_fts, 0, '<mark>', '</mark>', ' … ', 12) AS snippet, "
                "bm25(questions_fts) AS rank "
                "FROM questions_fts "
                "JOIN questions q ON q.id = questions_fts.rowid "
                "LEFT JOIN topics t ON t.id = q.topic_id "
                "WHERE questions_fts MATCH ?" + where_extra +
                " ORDER BY rank LIMIT ? OFFSET ?"
            )
            rows = db.execute(sql, [fts_q] + filters_args + [limit, offset]).fetchall()
            for r in rows:
                results.append({
                    "id": r["id"],
                    "question_text": r["question_text"],
                    "difficulty": r["difficulty"],
                    "correct_option": r["correct_option"],
                    "option_a": r["option_a"], "option_b": r["option_b"],
                    "option_c": r["option_c"], "option_d": r["option_d"],
                    "topic_name": r["topic_name"],
                    "snippet": r["snippet"],
                    "rank": r["rank"] if "rank" in r.keys() else None,
                })
        except Exception as e:  # noqa: BLE001
            print(f"[search rows fallback] {e}")
            return _like_fallback(db, q, filters_sql, filters_args, limit, offset)
        return jsonify({"total": total, "results": results, "backend": "fts5"})

    return _like_fallback(db, q, filters_sql, filters_args, limit, offset)


def _like_fallback(db, q, filters_sql, filters_args, limit, offset):
    """LIKE-based fallback used when FTS5 is unavailable or errors out.

    Slower and unranked, but keeps the feature usable. Searches text +
    options + explanation.
    """
    like = f"%{q}%"
    where_text = (
        "(q.question_text LIKE ? OR q.option_a LIKE ? OR q.option_b LIKE ? "
        "OR q.option_c LIKE ? OR q.option_d LIKE ? OR COALESCE(q.explanation,'') LIKE ?)"
    )
    args_text = [like, like, like, like, like, like]
    full_where = where_text + " AND " + " AND ".join(filters_sql)
    try:
        count_sql = (
            "SELECT COUNT(*) FROM questions q "
            "LEFT JOIN topics t ON t.id = q.topic_id "
            f"WHERE {full_where}"
        )
        row = db.execute(count_sql, args_text + filters_args).fetchone()
        total = int(row[0]) if row else 0
    except Exception as e:  # noqa: BLE001
        return jsonify({"total": 0, "results": [], "error": str(e)})

    try:
        sql = (
            "SELECT q.id, q.question_text, q.difficulty, q.correct_option, "
            "q.option_a, q.option_b, q.option_c, q.option_d, "
            "t.name AS topic_name "
            "FROM questions q LEFT JOIN topics t ON t.id = q.topic_id "
            f"WHERE {full_where} "
            "ORDER BY q.id DESC LIMIT ? OFFSET ?"
        )
        rows = db.execute(sql, args_text + filters_args + [limit, offset]).fetchall()
    except Exception as e:  # noqa: BLE001
        return jsonify({"total": 0, "results": [], "error": str(e)})

    out = []
    for r in rows:
        text = r["question_text"] or ""
        # Cheap highlight — case-insensitive first-match wrap in <mark>.
        snippet = text[:220]
        try:
            idx = text.lower().find(q.lower())
            if idx >= 0:
                start = max(0, idx - 40)
                end = min(len(text), idx + len(q) + 120)
                pre = ("… " if start > 0 else "") + text[start:idx]
                mid = "<mark>" + text[idx:idx + len(q)] + "</mark>"
                post = text[idx + len(q):end] + (" …" if end < len(text) else "")
                snippet = pre + mid + post
        except Exception:  # noqa: BLE001
            pass
        out.append({
            "id": r["id"],
            "question_text": text,
            "difficulty": r["difficulty"],
            "correct_option": r["correct_option"],
            "option_a": r["option_a"], "option_b": r["option_b"],
            "option_c": r["option_c"], "option_d": r["option_d"],
            "topic_name": r["topic_name"],
            "snippet": snippet,
        })
    return jsonify({"total": total, "results": out, "backend": "like"})
