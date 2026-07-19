"""Spaced-repetition review blueprint — /review + /api/review_answer.

Design (per Plan A F1):
  * GET /review — renders review.html with today's due queue (cards where
    date(sr_due_at) <= today).
  * POST /api/review_answer — client sends {error_id, was_correct}; server
    advances the Leitner box + due date and returns the new state so the UI
    can show "next review in N days" before moving to the next card.
"""
from flask import Blueprint, render_template, request, jsonify

from db import get_db
from sr import (
    BOX_INTERVALS_DAYS,
    MAX_BOX,
    get_due_reviews,
    get_queue_summary,
    next_box,
    record_review,
)

bp = Blueprint("review", __name__)


@bp.route("/review")
def index():
    """Daily review queue. Empty state = nothing due today."""
    db = get_db()
    try:
        cards = [dict(r) for r in get_due_reviews(db, limit=100)]
    except Exception as exc:  # noqa: BLE001 — schema drift shouldn't 500 the page
        cards = []
        print(f"[review] get_due_reviews failed: {exc}")

    summary = get_queue_summary(db)

    # Pre-compute the "if correct" / "if wrong" interval hints for the two
    # big buttons on each card. Rendered per-card in the template.
    for c in cards:
        cur = int(c.get("sr_box") or 1)
        if_ok = next_box(cur, True)
        if_no = next_box(cur, False)
        c["if_ok_box"] = if_ok
        c["if_ok_days"] = BOX_INTERVALS_DAYS.get(if_ok, 1)
        c["if_no_box"] = if_no
        c["if_no_days"] = BOX_INTERVALS_DAYS.get(if_no, 1)

    return render_template(
        "review.html",
        cards=cards,
        summary=summary,
        max_box=MAX_BOX,
    )


@bp.route("/api/review_answer", methods=["POST"])
def api_review_answer():
    """Advance one card. Body: {error_id: int, was_correct: bool}."""
    data = request.json or {}
    try:
        error_id = int(data.get("error_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "error_id required"}), 400
    was_correct = bool(data.get("was_correct"))

    db = get_db()
    result = record_review(db, error_id, was_correct)
    if result is None:
        return jsonify({"error": "not_found"}), 404
    db.commit()
    return jsonify(result)
