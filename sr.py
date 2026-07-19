"""Leitner-5 spaced-repetition primitives.

Design (per docs/plans/A-study-effectiveness.md §1.3-1.5):

  * 5 boxes; correct → box+1 (capped at 5), wrong → drop back one step down
    the ladder. The drop-on-miss map is `DROP_ON_MISS` — box 5 misses fall to
    box 3, not box 1, because a lapse at that level is usually momentary.
  * Interval days per box are `BOX_INTERVALS_DAYS`.
  * Everything is pure functions + one row-manipulation helper so we can
    unit-test without a Flask app context.

Callers:
  - `bp_review.py` — /review page + /api/review_answer.
  - `bp_tests.finish()` — writes a fresh row into `error_log` with `sr_box=1,
    sr_due_at = date('now', '+1 day')`.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta


BOX_INTERVALS_DAYS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
DROP_ON_MISS = {1: 1, 2: 1, 3: 1, 4: 2, 5: 3}
MAX_BOX = 5


def next_box(current_box: int, was_correct: bool) -> int:
    """Return the box a card moves to after a review.

    * Correct: promote by one, capped at MAX_BOX (5).
    * Wrong: drop back per DROP_ON_MISS (box 5 lapses fall to 3, not 1).
    """
    box = current_box or 1
    if was_correct:
        return min(MAX_BOX, box + 1)
    return DROP_ON_MISS.get(box, 1)


def next_due(box: int, from_date=None) -> str:
    """Return an ISO-date string for when a card in `box` is next due."""
    d = from_date or date.today()
    return (d + timedelta(days=BOX_INTERVALS_DAYS.get(box, 1))).isoformat()


def days_until_due(sr_due_at: str) -> int:
    """Positive = due in the future, 0 = due today, negative = overdue."""
    if not sr_due_at:
        return 0
    try:
        # Accept both plain 'YYYY-MM-DD' and full ISO datetimes.
        due = date.fromisoformat(sr_due_at[:10])
    except ValueError:
        return 0
    return (due - date.today()).days


def get_due_reviews(db, limit: int = 50):
    """Errors due today or earlier, oldest-due first, joined for display.

    Filters disabled questions. Sorts overdue first (older sr_due_at at top).
    """
    return db.execute(
        """
        SELECT el.id AS error_id, el.sr_box, el.sr_due_at, el.sr_last_reviewed,
               el.created_at AS logged_at, el.selected_option AS prev_selected,
               el.correct_option AS prev_correct,
               q.id AS question_id, q.question_text,
               q.option_a, q.option_b, q.option_c, q.option_d,
               q.correct_option, q.explanation, q.difficulty,
               t.id AS topic_id, t.name AS topic_name, t.paper AS paper
        FROM error_log el
        JOIN questions q ON q.id = el.question_id
        JOIN topics t ON t.id = el.topic_id
        WHERE (q.disabled IS NULL OR q.disabled = 0)
          AND date(el.sr_due_at) <= date('now')
        ORDER BY el.sr_due_at ASC, el.sr_box ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def get_queue_summary(db):
    """Return {due_today, total, by_box} where by_box is {1..5: count}.

    `due_today` counts every card whose sr_due_at is today or earlier (i.e.
    the number of cards `/review` will render). `total` is every non-null
    row in the queue. `by_box` counts every row regardless of due date.
    """
    try:
        due_today = db.execute(
            "SELECT COUNT(*) FROM error_log el "
            "JOIN questions q ON q.id = el.question_id "
            "WHERE (q.disabled IS NULL OR q.disabled = 0) "
            "  AND date(el.sr_due_at) <= date('now')"
        ).fetchone()
        due_today = due_today[0] if due_today else 0
    except Exception:
        due_today = 0

    try:
        total = db.execute("SELECT COUNT(*) FROM error_log").fetchone()
        total = total[0] if total else 0
    except Exception:
        total = 0

    by_box = {i: 0 for i in range(1, MAX_BOX + 1)}
    try:
        rows = db.execute(
            "SELECT COALESCE(sr_box, 1) AS b, COUNT(*) FROM error_log GROUP BY b"
        ).fetchall()
        for r in rows:
            b = int(r[0] or 1)
            if 1 <= b <= MAX_BOX:
                by_box[b] = int(r[1] or 0)
    except Exception:
        pass

    return {"due_today": due_today, "total": total, "by_box": by_box}


def record_review(db, error_id: int, was_correct: bool):
    """Advance a single error_log row per the Leitner rules.

    Returns {"new_box": int, "next_due": str, "was_correct": bool} or None if
    the row does not exist. Caller is responsible for db.commit() — mirrors
    the pattern used elsewhere in bp_api.py.
    """
    row = db.execute(
        "SELECT sr_box FROM error_log WHERE id = ?", (error_id,)
    ).fetchone()
    if row is None:
        return None
    raw = None
    try:
        raw = row["sr_box"]
    except (KeyError, IndexError, TypeError):
        raw = row[0] if len(row) else None
    current = int(raw) if raw not in (None, "") else 1
    new_box = next_box(current, was_correct)
    new_due = next_due(new_box)
    db.execute(
        "UPDATE error_log SET sr_box = ?, sr_due_at = ?, sr_last_reviewed = ? "
        "WHERE id = ?",
        (new_box, new_due, datetime.now().isoformat(), error_id),
    )
    return {"new_box": new_box, "next_due": new_due, "was_correct": was_correct}
