"""Error log blueprint — /errorlog (browser view)."""
from flask import Blueprint, request, render_template

from db import get_db

bp = Blueprint("errorlog", __name__)


@bp.route("/errorlog")
def view():
    db = get_db()
    page = request.args.get("page", 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    topic_filter = request.args.get("topic")
    type_filter = request.args.get("type")
    resolved_filter = request.args.get("resolved", "all")

    base_select = (
        "SELECT el.*, t.name as topic_name, q.question_text FROM error_log el "
        "JOIN topics t ON el.topic_id = t.id "
        "JOIN questions q ON el.question_id = q.id WHERE 1=1"
    )
    filters = ""
    params = []
    if topic_filter:
        filters += " AND el.topic_id=?"
        params.append(topic_filter)
    if type_filter:
        filters += " AND el.error_type=?"
        params.append(type_filter)
    if resolved_filter == "yes":
        filters += " AND el.resolved=1"
    elif resolved_filter == "no":
        filters += " AND el.resolved=0"

    total = db.execute(
        "SELECT COUNT(*) FROM error_log el "
        "JOIN topics t ON el.topic_id = t.id "
        "JOIN questions q ON el.question_id = q.id WHERE 1=1" + filters,
        params,
    ).fetchone()[0]

    errors = db.execute(
        base_select + filters + " ORDER BY el.created_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ).fetchall()

    topics = db.execute("SELECT * FROM topics ORDER BY name").fetchall()

    return render_template(
        "errorlog.html", errors=errors, topics=topics,
        total=total, page=page, per_page=per_page,
        topic_filter=topic_filter, type_filter=type_filter, resolved_filter=resolved_filter,
    )
