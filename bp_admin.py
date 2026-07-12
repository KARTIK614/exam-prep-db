"""Admin panel — /admin/*. Every route requires role='admin'."""
import json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app, g
from werkzeug.security import generate_password_hash

from db import get_db
from auth import require_admin

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Store extracted questions in memory keyed by upload id. Flask-session's
# filesystem backend rejects payloads this large; the admin panel is single-user
# so in-memory works fine here.
_EXTRACTION_CACHE: dict[int, list[dict]] = {}


@bp.route("/")
@require_admin
def dashboard():
    db = get_db()
    stats = {
        "flags_open": db.execute("SELECT COUNT(*) FROM question_flags WHERE status='open'").fetchone()[0],
        "flags_total": db.execute("SELECT COUNT(*) FROM question_flags").fetchone()[0],
        "questions": db.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
        "questions_disabled": db.execute("SELECT COUNT(*) FROM questions WHERE disabled=1").fetchone()[0],
        "topics": db.execute("SELECT COUNT(*) FROM topics").fetchone()[0],
        "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "uploads": db.execute("SELECT COUNT(*) FROM pdf_uploads").fetchone()[0],
    }
    recent_flags = db.execute(
        "SELECT f.*, q.question_text FROM question_flags f "
        "LEFT JOIN questions q ON f.question_id = q.id "
        "WHERE f.status='open' ORDER BY f.created_at DESC LIMIT 10"
    ).fetchall()
    return render_template("admin/dashboard.html", stats=stats, recent_flags=recent_flags)


# ─── Flags ────────────────────────────────────────────────────────

@bp.route("/flags")
@require_admin
def flags():
    db = get_db()
    status_filter = request.args.get("status", "open")
    if status_filter == "all":
        rows = db.execute(
            "SELECT f.*, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, "
            "q.correct_option, q.disabled, t.name AS topic_name "
            "FROM question_flags f "
            "LEFT JOIN questions q ON f.question_id = q.id "
            "LEFT JOIN topics t ON q.topic_id = t.id "
            "ORDER BY f.created_at DESC LIMIT 200"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT f.*, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, "
            "q.correct_option, q.disabled, t.name AS topic_name "
            "FROM question_flags f "
            "LEFT JOIN questions q ON f.question_id = q.id "
            "LEFT JOIN topics t ON q.topic_id = t.id "
            "WHERE f.status=? ORDER BY f.created_at DESC LIMIT 200",
            (status_filter,),
        ).fetchall()
    return render_template("admin/flags.html", flags=rows, status_filter=status_filter)


@bp.route("/api/flag/<int:flag_id>/<action>", methods=["POST"])
@require_admin
def flag_action(flag_id, action):
    db = get_db()
    if action == "resolve":
        db.execute(
            "UPDATE question_flags SET status='resolved', resolved_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), flag_id),
        )
    elif action == "dismiss":
        db.execute(
            "UPDATE question_flags SET status='dismissed', resolved_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), flag_id),
        )
    elif action == "disable_question":
        row = db.execute("SELECT question_id FROM question_flags WHERE id=?", (flag_id,)).fetchone()
        if row:
            db.execute("UPDATE questions SET disabled=1 WHERE id=?", (row["question_id"],))
            db.execute(
                "UPDATE question_flags SET status='resolved', resolved_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), flag_id),
            )
    else:
        return jsonify({"error": "unknown action"}), 400
    db.commit()
    return jsonify({"status": "ok"})


# ─── Questions CRUD ───────────────────────────────────────────────

@bp.route("/questions")
@require_admin
def questions_list():
    db = get_db()
    topic_id = request.args.get("topic_id", type=int)
    paper = request.args.get("paper")
    difficulty = request.args.get("difficulty")
    show_disabled = request.args.get("disabled") == "1"
    page = request.args.get("page", 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    filters = "WHERE 1=1"
    params = []
    if topic_id:
        filters += " AND q.topic_id=?"; params.append(topic_id)
    if paper:
        filters += " AND t.paper=?"; params.append(paper)
    if difficulty:
        filters += " AND q.difficulty=?"; params.append(difficulty)
    if not show_disabled:
        filters += " AND (q.disabled IS NULL OR q.disabled=0)"

    total = db.execute(
        f"SELECT COUNT(*) FROM questions q JOIN topics t ON q.topic_id=t.id {filters}",
        params,
    ).fetchone()[0]
    rows = db.execute(
        f"SELECT q.*, t.name AS topic_name, t.paper AS paper "
        f"FROM questions q JOIN topics t ON q.topic_id=t.id {filters} "
        f"ORDER BY q.id DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ).fetchall()
    topics = db.execute("SELECT * FROM topics ORDER BY paper, name").fetchall()
    return render_template(
        "admin/questions.html",
        questions=rows, topics=topics, total=total,
        page=page, per_page=per_page,
        topic_id=topic_id, paper=paper, difficulty=difficulty, show_disabled=show_disabled,
    )


@bp.route("/questions/<int:qid>/edit", methods=["GET", "POST"])
@require_admin
def question_edit(qid):
    db = get_db()
    if request.method == "POST":
        db.execute(
            "UPDATE questions SET question_text=?, option_a=?, option_b=?, option_c=?, option_d=?, "
            "correct_option=?, explanation=?, difficulty=?, topic_id=?, disabled=?, updated_at=? WHERE id=?",
            (
                request.form.get("question_text", "").strip(),
                request.form.get("option_a", "").strip(),
                request.form.get("option_b", "").strip(),
                request.form.get("option_c", "").strip(),
                request.form.get("option_d", "").strip(),
                request.form.get("correct_option", "A").strip().upper()[:1],
                request.form.get("explanation", "").strip(),
                request.form.get("difficulty", "medium"),
                int(request.form.get("topic_id", 0)) or None,
                1 if request.form.get("disabled") == "on" else 0,
                datetime.utcnow().isoformat(),
                qid,
            ),
        )
        db.commit()
        return redirect(url_for("admin.questions_list"))
    q = db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not q:
        return redirect(url_for("admin.questions_list"))
    topics = db.execute("SELECT * FROM topics ORDER BY paper, name").fetchall()
    return render_template("admin/question_edit.html", q=q, topics=topics)


@bp.route("/api/question/<int:qid>/toggle_disabled", methods=["POST"])
@require_admin
def question_toggle_disabled(qid):
    db = get_db()
    row = db.execute("SELECT disabled FROM questions WHERE id=?", (qid,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    new_val = 0 if row["disabled"] else 1
    db.execute("UPDATE questions SET disabled=? WHERE id=?", (new_val, qid))
    db.commit()
    return jsonify({"disabled": new_val})


@bp.route("/api/question/<int:qid>/delete", methods=["POST"])
@require_admin
def question_delete(qid):
    db = get_db()
    db.execute("DELETE FROM questions WHERE id=?", (qid,))
    db.commit()
    return jsonify({"status": "ok"})


# ─── Topics CRUD ──────────────────────────────────────────────────

@bp.route("/topics", methods=["GET", "POST"])
@require_admin
def topics_view():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        subject = request.form.get("subject", "").strip()
        paper = request.form.get("paper", "").strip()
        weightage = int(request.form.get("weightage", 5))
        if name:
            db.execute(
                "INSERT OR IGNORE INTO topics (name, subject, paper, weightage) VALUES (?,?,?,?)",
                (name, subject, paper, weightage),
            )
            db.commit()
        return redirect(url_for("admin.topics_view"))
    rows = db.execute(
        "SELECT t.*, "
        "(SELECT COUNT(*) FROM questions q WHERE q.topic_id=t.id) AS n_questions "
        "FROM topics t ORDER BY t.paper, t.name"
    ).fetchall()
    return render_template("admin/topics.html", topics=rows)


@bp.route("/topics/<int:tid>/delete", methods=["POST"])
@require_admin
def topic_delete(tid):
    db = get_db()
    db.execute("DELETE FROM topics WHERE id=?", (tid,))
    db.commit()
    return redirect(url_for("admin.topics_view"))


# ─── Users CRUD ───────────────────────────────────────────────────

@bp.route("/users", methods=["GET", "POST"])
@require_admin
def users_view():
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "user")
        if username and password:
            db.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
                (username, generate_password_hash(password), role),
            )
            db.commit()
        return redirect(url_for("admin.users_view"))
    rows = db.execute(
        "SELECT id, username, role, is_active, created_at, last_login FROM users ORDER BY id"
    ).fetchall()
    return render_template("admin/users.html", users=rows)


@bp.route("/users/<int:uid>/update", methods=["POST"])
@require_admin
def user_update(uid):
    db = get_db()
    new_pw = request.form.get("password", "").strip()
    role = request.form.get("role")
    is_active = request.form.get("is_active")
    if new_pw:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pw), uid))
    if role in ("admin", "user"):
        db.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
    if is_active in ("0", "1"):
        db.execute("UPDATE users SET is_active=? WHERE id=?", (int(is_active), uid))
    db.commit()
    return redirect(url_for("admin.users_view"))


# ─── PDF uploads → LLM extraction → import ────────────────────────

def _get_default_prompt(db):
    row = db.execute(
        "SELECT * FROM master_prompts WHERE is_default=1 ORDER BY id LIMIT 1"
    ).fetchone()
    if not row:
        row = db.execute("SELECT * FROM master_prompts ORDER BY id LIMIT 1").fetchone()
    return row


@bp.route("/uploads", methods=["GET", "POST"])
@require_admin
def uploads_view():
    db = get_db()

    if request.method == "POST":
        f = request.files.get("pdf")
        topic_id_str = request.form.get("topic_id", "").strip()
        prompt_name = request.form.get("prompt_name", "default")
        if not f or not f.filename:
            return redirect(url_for("admin.uploads_view"))

        pdf_bytes = f.read()
        prompt_row = db.execute(
            "SELECT * FROM master_prompts WHERE name=?", (prompt_name,)
        ).fetchone() or _get_default_prompt(db)
        if not prompt_row:
            return redirect(url_for("admin.uploads_view"))

        upload_id = db.execute(
            "INSERT INTO pdf_uploads (filename, uploaded_by, uploaded_at, topic_id, "
            "status, prompt_id, model) VALUES (?, ?, ?, ?, 'processing', ?, ?)",
            (
                f.filename,
                getattr(g, "user", None),
                datetime.utcnow().isoformat(),
                int(topic_id_str) if topic_id_str else None,
                prompt_row["id"],
                prompt_row["model"],
            ),
        ).lastrowid
        db.commit()

        topic_hint = ""
        if topic_id_str:
            trow = db.execute(
                "SELECT name FROM topics WHERE id=?", (int(topic_id_str),)
            ).fetchone()
            if trow:
                topic_hint = trow["name"]

        from ai_anthropic import extract_questions_from_pdf
        result = extract_questions_from_pdf(
            pdf_bytes=pdf_bytes,
            master_prompt=prompt_row["template"],
            model=prompt_row["model"] or "claude-sonnet-4-6",
            topic_hint=topic_hint,
        )

        if not result.get("ok"):
            db.execute(
                "UPDATE pdf_uploads SET status='error', num_extracted=0 WHERE id=?",
                (upload_id,),
            )
            db.commit()
            return render_template(
                "admin/upload_error.html", error=result.get("error"), upload_id=upload_id
            )

        questions = result["questions"]
        _EXTRACTION_CACHE[upload_id] = questions
        db.execute(
            "UPDATE pdf_uploads SET status='extracted', num_extracted=? WHERE id=?",
            (len(questions), upload_id),
        )
        db.commit()
        return redirect(url_for("admin.upload_preview", upload_id=upload_id))

    uploads = db.execute(
        "SELECT u.*, t.name AS topic_name FROM pdf_uploads u "
        "LEFT JOIN topics t ON u.topic_id = t.id "
        "ORDER BY u.uploaded_at DESC LIMIT 50"
    ).fetchall()
    topics = db.execute("SELECT * FROM topics ORDER BY paper, name").fetchall()
    prompts = db.execute(
        "SELECT name, model, is_default FROM master_prompts ORDER BY is_default DESC, name"
    ).fetchall()
    return render_template(
        "admin/uploads.html", uploads=uploads, topics=topics, prompts=prompts
    )


@bp.route("/uploads/<int:upload_id>/preview")
@require_admin
def upload_preview(upload_id):
    db = get_db()
    upload = db.execute("SELECT * FROM pdf_uploads WHERE id=?", (upload_id,)).fetchone()
    if not upload:
        return redirect(url_for("admin.uploads_view"))
    questions = _EXTRACTION_CACHE.get(upload_id, [])
    topics = db.execute("SELECT * FROM topics ORDER BY paper, name").fetchall()
    return render_template(
        "admin/upload_preview.html", upload=upload, questions=questions, topics=topics
    )


@bp.route("/uploads/<int:upload_id>/import", methods=["POST"])
@require_admin
def upload_import(upload_id):
    db = get_db()
    upload = db.execute("SELECT * FROM pdf_uploads WHERE id=?", (upload_id,)).fetchone()
    if not upload:
        return redirect(url_for("admin.uploads_view"))

    questions = _EXTRACTION_CACHE.get(upload_id, [])
    if not questions:
        return redirect(url_for("admin.upload_preview", upload_id=upload_id))

    # form contains selected[]=<idx> for each row the admin checked
    selected_idx = {int(x) for x in request.form.getlist("selected") if x.isdigit()}
    topic_id = upload["topic_id"]
    imported = 0

    for i, q in enumerate(questions):
        if i not in selected_idx:
            continue
        db.execute(
            "INSERT INTO questions (topic_id, question_text, option_a, option_b, option_c, "
            "option_d, correct_option, explanation, difficulty, source, disabled, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                topic_id,
                q.get("question_text", ""),
                q.get("option_a", ""),
                q.get("option_b", ""),
                q.get("option_c", ""),
                q.get("option_d", ""),
                (q.get("correct_option") or "").upper()[:1] or "A",
                q.get("explanation", ""),
                q.get("difficulty", "medium"),
                f"pdf_upload:{upload_id}",
                datetime.utcnow().isoformat(),
            ),
        )
        imported += 1

    db.execute(
        "UPDATE pdf_uploads SET num_imported=?, status='imported' WHERE id=?",
        (imported, upload_id),
    )
    db.commit()
    _EXTRACTION_CACHE.pop(upload_id, None)
    return redirect(url_for("admin.uploads_view"))


# ─── Master prompts ───────────────────────────────────────────────

@bp.route("/prompts", methods=["GET", "POST"])
@require_admin
def prompts_view():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "default").strip() or "default"
        template = request.form.get("template", "").strip()
        model = request.form.get("model", "claude-sonnet-4-6").strip()
        is_default = 1 if request.form.get("is_default") == "on" else 0
        existing = db.execute("SELECT id FROM master_prompts WHERE name=?", (name,)).fetchone()
        if existing:
            db.execute(
                "UPDATE master_prompts SET template=?, model=?, is_default=?, updated_at=? WHERE name=?",
                (template, model, is_default, datetime.utcnow().isoformat(), name),
            )
        else:
            db.execute(
                "INSERT INTO master_prompts (name, template, model, is_default, updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, template, model, is_default, datetime.utcnow().isoformat()),
            )
        if is_default:
            db.execute("UPDATE master_prompts SET is_default=0 WHERE name != ?", (name,))
        db.commit()
        return redirect(url_for("admin.prompts_view"))
    rows = db.execute("SELECT * FROM master_prompts ORDER BY is_default DESC, name").fetchall()
    return render_template("admin/prompts.html", prompts=rows)
