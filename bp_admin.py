"""Admin panel — /admin/*. Every route requires role='admin'."""
import hashlib
import json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app, g
from werkzeug.security import generate_password_hash

from db import get_db
from auth import require_admin
from content_metadata import (
    metadata_from_json_question,
    compute_trigrams,
    keep_better_of,
    extract_reviewer_note,
    SYNTHESIS_PROMPT,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Store extracted questions in memory keyed by upload/batch id. Flask-session's
# filesystem backend rejects payloads this large; the admin panel is single-user
# so in-memory works fine here. Values are either a list[dict] (PDF uploads,
# legacy shape) or a dict with a "questions" key + metadata (synthesis batches).
_EXTRACTION_CACHE: dict = {}


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
    # Plan D §2/§3/§4 quick counts — surface directly on the dashboard.
    try:
        review_counts = _review_counts(db)
    except Exception as exc:  # noqa: BLE001 — schema drift shouldn't 500 the page
        current_app.logger.warning(f"review_counts failed on dashboard: {exc}")
        review_counts = {"medium": 0, "with_notes": 0, "synthetic": 0, "deferred": 0, "non_high": 0}
    stats["review_medium"] = review_counts["medium"]
    stats["review_synthetic"] = review_counts["synthetic"]
    try:
        stats["deficit_topics"] = len(_deficit_report(db))
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f"deficit_report failed on dashboard: {exc}")
        stats["deficit_topics"] = 0
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


# ─── Medium-confidence review UI (Plan D §2) ──────────────────────

def _review_counts(db):
    """Return live counts for the four filter chips on /admin/review."""
    counts = {}
    counts["medium"] = db.execute(
        "SELECT COUNT(*) FROM questions WHERE confidence='medium' "
        "AND (disabled IS NULL OR disabled=0)"
    ).fetchone()[0]
    counts["with_notes"] = db.execute(
        "SELECT COUNT(*) FROM questions "
        "WHERE (explanation LIKE '%[Reviewer note:%' OR (review_notes IS NOT NULL AND review_notes != '')) "
        "AND (disabled IS NULL OR disabled=0)"
    ).fetchone()[0]
    counts["synthetic"] = db.execute(
        "SELECT COUNT(*) FROM questions WHERE source LIKE 'synthetic-%' "
        "AND (disabled IS NULL OR disabled=0)"
    ).fetchone()[0]
    counts["deferred"] = db.execute(
        "SELECT COUNT(*) FROM questions WHERE confidence='deferred' "
        "AND (disabled IS NULL OR disabled=0)"
    ).fetchone()[0]
    counts["non_high"] = db.execute(
        "SELECT COUNT(*) FROM questions "
        "WHERE (confidence IS NULL OR confidence != 'high') "
        "AND (disabled IS NULL OR disabled=0)"
    ).fetchone()[0]
    return counts


@bp.route("/review")
@require_admin
def review_queue():
    db = get_db()
    filt = request.args.get("filter", "medium")
    if filt == "with_notes":
        where = ("(explanation LIKE '%[Reviewer note:%' OR "
                 "(review_notes IS NOT NULL AND review_notes != ''))")
    elif filt == "synthetic":
        where = "source LIKE 'synthetic-%'"
    elif filt == "deferred":
        where = "confidence='deferred'"
    elif filt == "non_high":
        where = "(confidence IS NULL OR confidence != 'high')"
    else:
        filt = "medium"
        where = "confidence='medium'"

    rows = db.execute(
        f"SELECT q.*, t.name AS topic_name FROM questions q "
        f"LEFT JOIN topics t ON q.topic_id=t.id "
        f"WHERE {where} AND (q.disabled IS NULL OR q.disabled=0) "
        f"ORDER BY q.id ASC LIMIT 200"
    ).fetchall()

    counts = _review_counts(db)
    return render_template(
        "admin/review.html",
        rows=rows,
        counts=counts,
        active_filter=filt,
    )


@bp.route("/api/review/<int:qid>/<action>", methods=["POST"])
@require_admin
def review_action(qid, action):
    """State machine — confirm / edit / disable / defer.

    On `confirm`: promote confidence='high', strip the [Reviewer note:...]
    blob out of explanation (only if the anchored regex matches), preserve
    the raw note in review_notes, and stamp confidence_reviewed_at.
    """
    db = get_db()
    row = db.execute(
        "SELECT id, explanation, review_notes FROM questions WHERE id=?", (qid,)
    ).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404

    now = datetime.utcnow().isoformat()

    if action == "confirm":
        current_expl = row["explanation"] or ""
        current_notes = row["review_notes"] or ""
        stripped, note = extract_reviewer_note(current_expl)
        # Only overwrite explanation if the strip actually did something.
        if note is not None:
            new_expl = stripped
            new_notes = current_notes or note
        else:
            new_expl = current_expl
            new_notes = current_notes
        db.execute(
            "UPDATE questions SET confidence=?, explanation=?, review_notes=?, "
            "confidence_reviewed_at=?, updated_at=? WHERE id=?",
            ("high", new_expl, new_notes or None, now, now, qid),
        )
        db.commit()
        return jsonify({"status": "ok", "confidence": "high"})

    if action == "disable":
        db.execute(
            "UPDATE questions SET disabled=1, updated_at=? WHERE id=?",
            (now, qid),
        )
        db.commit()
        return jsonify({"status": "ok", "disabled": 1})

    if action == "defer":
        db.execute(
            "UPDATE questions SET confidence='deferred', updated_at=? WHERE id=?",
            (now, qid),
        )
        db.commit()
        return jsonify({"status": "ok", "confidence": "deferred"})

    if action == "edit":
        # Inline edit — accepts JSON body with any subset of the editable
        # fields. Editing implies confidence=high (stronger commitment).
        data = request.get_json(silent=True) or {}
        fields = []
        params = []
        for col in ("question_text", "option_a", "option_b", "option_c",
                    "option_d", "explanation", "correct_option", "difficulty"):
            if col in data:
                fields.append(f"{col}=?")
                val = data[col]
                if col == "correct_option":
                    val = (val or "A").upper()[:1]
                params.append(val)
        # Always promote to high on edit + strip note if present.
        current_expl = row["explanation"] or ""
        current_notes = row["review_notes"] or ""
        stripped, note = extract_reviewer_note(current_expl)
        if note is not None and "explanation" not in data:
            fields.append("explanation=?")
            params.append(stripped)
            fields.append("review_notes=?")
            params.append(current_notes or note)
        fields.append("confidence=?"); params.append("high")
        fields.append("confidence_reviewed_at=?"); params.append(now)
        fields.append("updated_at=?"); params.append(now)
        params.append(qid)
        db.execute(
            f"UPDATE questions SET {', '.join(fields)} WHERE id=?",
            params,
        )
        db.commit()
        return jsonify({"status": "ok"})

    return jsonify({"error": "unknown_action"}), 400


# ─── Duplicate detection (Plan D §3) ──────────────────────────────

def _find_duplicate_pairs(db, threshold=0.7, limit=200):
    """Return list of candidate duplicate pairs at jaccard >= threshold.

    Query joins question_trigrams to itself, groups by pair (a<b), then
    computes jaccard = intersection / (a.n + b.n - intersection).

    Pre-filter: intersection_size >= 15 kills the O(n^2) blowup on
    unrelated pairs. A real dupe with 100+ trigrams typically shares
    80-90, so 15 is very conservative.
    """
    try:
        rows = db.execute(
            """
            WITH pairs AS (
                SELECT a.question_id AS q1, b.question_id AS q2,
                       COUNT(*) AS isize
                  FROM question_trigrams a
                  JOIN question_trigrams b
                    ON a.trigram = b.trigram
                   AND a.question_id < b.question_id
                 GROUP BY a.question_id, b.question_id
                HAVING COUNT(*) >= 15
            ),
            sizes AS (
                SELECT question_id, COUNT(*) AS n
                  FROM question_trigrams
                 GROUP BY question_id
            )
            SELECT p.q1, p.q2,
                   CAST(p.isize AS REAL) / (s1.n + s2.n - p.isize) AS jaccard,
                   p.isize, s1.n AS n1, s2.n AS n2
              FROM pairs p
              JOIN sizes s1 ON s1.question_id = p.q1
              JOIN sizes s2 ON s2.question_id = p.q2
             WHERE CAST(p.isize AS REAL) / (s1.n + s2.n - p.isize) >= ?
             ORDER BY jaccard DESC
             LIMIT ?
            """,
            (threshold, limit),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — surface but don't 500
        current_app.logger.warning(f"duplicate query failed: {exc}")
        return []
    return rows


@bp.route("/duplicates")
@require_admin
def duplicates_view():
    db = get_db()
    try:
        threshold = float(request.args.get("threshold", "0.7"))
    except ValueError:
        threshold = 0.7
    threshold = max(0.5, min(1.0, threshold))

    pair_rows = _find_duplicate_pairs(db, threshold=threshold, limit=200)

    # Fetch full question detail for the referenced ids. One IN-clause per
    # column set — cheap because we cap at 200 pairs = 400 ids.
    ids = set()
    for r in pair_rows:
        ids.add(r["q1"]); ids.add(r["q2"])
    q_map = {}
    if ids:
        placeholders = ",".join("?" * len(ids))
        qrows = db.execute(
            f"SELECT q.*, t.name AS topic_name "
            f"FROM questions q LEFT JOIN topics t ON q.topic_id=t.id "
            f"WHERE q.id IN ({placeholders})",
            list(ids),
        ).fetchall()
        for qr in qrows:
            q_map[qr["id"]] = dict(qr)

    # For each pair: determine keep/discard suggestion via keep_better_of,
    # plus whether either row is referenced in test_responses (informational).
    ref_counts = {}
    if ids:
        placeholders = ",".join("?" * len(ids))
        try:
            rc_rows = db.execute(
                f"SELECT question_id, COUNT(*) AS n FROM test_responses "
                f"WHERE question_id IN ({placeholders}) GROUP BY question_id",
                list(ids),
            ).fetchall()
            for rc in rc_rows:
                ref_counts[rc["question_id"]] = rc["n"]
        except Exception:  # noqa: BLE001
            pass

    pairs = []
    for pr in pair_rows:
        q1 = q_map.get(pr["q1"])
        q2 = q_map.get(pr["q2"])
        if not q1 or not q2:
            continue
        winner, loser = keep_better_of(q1, q2)
        pairs.append({
            "q1": q1, "q2": q2,
            "jaccard": round(float(pr["jaccard"]), 3),
            "isize": pr["isize"], "n1": pr["n1"], "n2": pr["n2"],
            "suggested_keep": winner["id"],
            "suggested_disable": loser["id"],
            "q1_refs": ref_counts.get(q1["id"], 0),
            "q2_refs": ref_counts.get(q2["id"], 0),
        })

    total_trigrams = 0
    try:
        total_trigrams = db.execute(
            "SELECT COUNT(*) FROM question_trigrams"
        ).fetchone()[0]
    except Exception:  # noqa: BLE001
        pass

    return render_template(
        "admin/duplicates.html",
        pairs=pairs,
        threshold=threshold,
        total_trigrams=total_trigrams,
    )


@bp.route("/api/duplicate/disable/<int:qid>", methods=["POST"])
@require_admin
def duplicate_disable(qid):
    db = get_db()
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE questions SET disabled=1, updated_at=? WHERE id=?",
        (now, qid),
    )
    db.commit()
    return jsonify({"status": "ok", "disabled_id": qid})


# ─── Under-represented topic backfill (Plan D §4) ─────────────────

def _deficit_report(db):
    """Return list of Paper-II topics with < 20 active rows, plus counts.

    Ordered by weightage DESC so the highest-impact deficits float up.
    """
    try:
        rows = db.execute(
            """
            SELECT t.id, t.name, t.weightage,
                   COUNT(CASE WHEN (q.disabled IS NULL OR q.disabled=0) THEN q.id END) AS n_rows,
                   COUNT(CASE WHEN q.source LIKE 'synthetic-%' AND (q.disabled IS NULL OR q.disabled=0) THEN q.id END) AS n_synthetic
              FROM topics t
              LEFT JOIN questions q ON q.topic_id = t.id
             WHERE t.paper = 'II'
             GROUP BY t.id, t.name, t.weightage
             HAVING n_rows < 20
             ORDER BY t.weightage DESC, n_rows ASC
            """
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f"deficit query failed: {exc}")
        rows = []
    return rows


def _topic_row_counts(db):
    """Return [(topic_id, name, weightage, n_active, n_synthetic)] for
    every Paper-II topic — needed by /admin/synthesize for the cap
    calculation."""
    try:
        rows = db.execute(
            """
            SELECT t.id, t.name, t.weightage,
                   COUNT(CASE WHEN (q.disabled IS NULL OR q.disabled=0) THEN q.id END) AS n_active,
                   COUNT(CASE WHEN q.source LIKE 'synthetic-%' AND (q.disabled IS NULL OR q.disabled=0) THEN q.id END) AS n_synthetic
              FROM topics t
              LEFT JOIN questions q ON q.topic_id = t.id
             WHERE t.paper = 'II'
             GROUP BY t.id, t.name, t.weightage
             ORDER BY t.weightage DESC, n_active ASC
            """
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f"topic counts failed: {exc}")
        rows = []
    return rows


@bp.route("/synthesize", methods=["GET"])
@require_admin
def synthesize_view():
    db = get_db()
    deficit = _deficit_report(db)
    topics = _topic_row_counts(db)
    # Recent batches (last 20).
    try:
        batches = db.execute(
            "SELECT b.*, t.name AS topic_name FROM synthesis_batches b "
            "LEFT JOIN topics t ON b.topic_id=t.id "
            "ORDER BY b.id DESC LIMIT 20"
        ).fetchall()
    except Exception:  # noqa: BLE001
        batches = []
    return render_template(
        "admin/synthesize.html",
        deficit=deficit,
        topics=topics,
        batches=batches,
    )


@bp.route("/api/synthesize/preview", methods=["POST"])
@require_admin
def synthesize_preview():
    """Trigger Claude generation for a topic. Does NOT insert into
    questions — caches the batch in _EXTRACTION_CACHE keyed by the new
    batch id and returns the preview URL. Admin reviews before commit.

    Body (JSON): {topic_id: int, count: int, sub_topics: str (opt)}
    """
    db = get_db()
    data = request.get_json(silent=True) or request.form.to_dict()
    try:
        topic_id = int(data.get("topic_id"))
        count = int(data.get("count"))
    except (TypeError, ValueError):
        return jsonify({"error": "topic_id and count required"}), 400
    if count < 1 or count > 40:
        return jsonify({"error": "count must be between 1 and 40"}), 400

    topic_row = db.execute(
        "SELECT * FROM topics WHERE id=?", (topic_id,)
    ).fetchone()
    if not topic_row:
        return jsonify({"error": "topic not found"}), 404

    # Enforce the 40%-synthetic cap.
    counts_row = db.execute(
        "SELECT COUNT(CASE WHEN (disabled IS NULL OR disabled=0) THEN 1 END) AS active, "
        "COUNT(CASE WHEN source LIKE 'synthetic-%' AND (disabled IS NULL OR disabled=0) THEN 1 END) AS synth "
        "FROM questions WHERE topic_id=?",
        (topic_id,),
    ).fetchone()
    active = counts_row["active"] or 0
    synth = counts_row["synth"] or 0
    max_new = max(0, int((active + count) * 0.4) - synth)
    if count > max_new and active > 0:
        return jsonify({
            "error": f"cap exceeded: at most {max_new} synthetic rows allowed for this topic "
                     f"({synth}/{active} already synthetic, 40% ceiling)."
        }), 400

    # Gather few-shot examples: up to 10 existing enabled questions on this topic.
    fewshot_rows = db.execute(
        "SELECT question_text, option_a, option_b, option_c, option_d, "
        "correct_option, explanation, difficulty "
        "FROM questions WHERE topic_id=? "
        "AND (disabled IS NULL OR disabled=0) "
        "AND (source IS NULL OR source NOT LIKE 'synthetic-%') "
        "ORDER BY id DESC LIMIT 10",
        (topic_id,),
    ).fetchall()
    fewshot = [dict(r) for r in fewshot_rows]

    sub_topics = data.get("sub_topics") or "general"

    prompt = SYNTHESIS_PROMPT.format(
        topic=topic_row["name"],
        n=count,
        sub_topics=sub_topics,
        existing_questions_json=json.dumps(fewshot, ensure_ascii=False, indent=2),
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

    # Record the batch as pending BEFORE the API call so failures are
    # still visible.
    batch_id = db.execute(
        "INSERT INTO synthesis_batches (topic_id, n_requested, prompt_hash, model, status) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (topic_id, count, prompt_hash, "claude-opus-4-7"),
    ).lastrowid
    db.commit()

    # Call Claude.
    try:
        from ai_anthropic import synthesize_questions
        result = synthesize_questions(
            prompt=prompt,
            n=count,
            model="claude-opus-4-7",
        )
    except ImportError:
        result = {"ok": False, "error": "synthesize_questions helper not available"}

    if not result.get("ok"):
        db.execute(
            "UPDATE synthesis_batches SET status='error', notes=? WHERE id=?",
            (result.get("error", "unknown")[:500], batch_id),
        )
        db.commit()
        return jsonify({"error": result.get("error"), "batch_id": batch_id}), 502

    questions = result.get("questions") or []
    db.execute(
        "UPDATE synthesis_batches SET n_generated=?, status='ready' WHERE id=?",
        (len(questions), batch_id),
    )
    db.commit()

    _EXTRACTION_CACHE[f"synth:{batch_id}"] = {
        "topic_id": topic_id,
        "questions": questions,
        "prompt_hash": prompt_hash,
        "model": "claude-opus-4-7",
        "kind": "synthesis",
    }
    return jsonify({
        "status": "ok",
        "batch_id": batch_id,
        "n_generated": len(questions),
        "preview_url": url_for("admin.synthesize_preview_view", batch_id=batch_id),
    })


@bp.route("/synthesize/<int:batch_id>/preview")
@require_admin
def synthesize_preview_view(batch_id):
    db = get_db()
    batch = db.execute(
        "SELECT b.*, t.name AS topic_name FROM synthesis_batches b "
        "LEFT JOIN topics t ON b.topic_id=t.id WHERE b.id=?",
        (batch_id,),
    ).fetchone()
    if not batch:
        return redirect(url_for("admin.synthesize_view"))
    cache_entry = _EXTRACTION_CACHE.get(f"synth:{batch_id}") or {}
    questions = cache_entry.get("questions") if isinstance(cache_entry, dict) else []
    return render_template(
        "admin/synthesize_preview.html",
        batch=batch,
        questions=questions or [],
    )


@bp.route("/synthesize/<int:batch_id>/commit", methods=["POST"])
@require_admin
def synthesize_commit(batch_id):
    """Insert the selected synthetic questions with source='synthetic-v1'
    and confidence='medium' so they land in the /admin/review queue."""
    db = get_db()
    batch = db.execute(
        "SELECT * FROM synthesis_batches WHERE id=?", (batch_id,)
    ).fetchone()
    if not batch:
        return redirect(url_for("admin.synthesize_view"))
    entry = _EXTRACTION_CACHE.get(f"synth:{batch_id}") or {}
    questions = entry.get("questions") if isinstance(entry, dict) else []
    if not questions:
        return redirect(url_for("admin.synthesize_view"))

    selected_idx = {int(x) for x in request.form.getlist("selected") if x.isdigit()}
    topic_id = batch["topic_id"]
    imported = 0
    now = datetime.utcnow().isoformat()

    for i, q in enumerate(questions):
        if i not in selected_idx:
            continue
        explanation = q.get("explanation", "") or ""
        if q.get("notes"):
            explanation = f"{explanation}\n\n[Reviewer note: {q['notes']}]"

        db.execute(
            "INSERT INTO questions (topic_id, question_text, option_a, option_b, option_c, "
            "option_d, correct_option, explanation, difficulty, source, disabled, updated_at, "
            "confidence, review_notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'synthetic-v1', 0, ?, 'medium', ?)",
            (
                topic_id,
                q.get("question_text", ""),
                q.get("option_a", ""),
                q.get("option_b", ""),
                q.get("option_c", ""),
                q.get("option_d", ""),
                (q.get("correct_option") or "A").upper()[:1] or "A",
                explanation,
                q.get("difficulty", "medium"),
                now,
                q.get("notes") or None,
            ),
        )
        imported += 1

    db.execute(
        "UPDATE synthesis_batches SET n_pending=?, status='committed' WHERE id=?",
        (imported, batch_id),
    )
    db.commit()
    _EXTRACTION_CACHE.pop(f"synth:{batch_id}", None)
    return redirect(url_for("admin.review_queue", filter="synthetic"))


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

    new_question_ids = []
    for i, q in enumerate(questions):
        if i not in selected_idx:
            continue

        # Preserve reviewer notes in the explanation blob (test-time
        # visibility) AND record them structurally in review_notes.
        explanation = q.get("explanation", "") or ""
        if q.get("notes"):
            explanation = f"{explanation}\n\n[Reviewer note: {q['notes']}]"

        meta = metadata_from_json_question(q)

        cur = db.execute(
            "INSERT INTO questions (topic_id, question_text, option_a, option_b, option_c, "
            "option_d, correct_option, explanation, difficulty, source, disabled, updated_at, "
            "confidence, section, sub_topic, pyq_exam, pyq_year, review_notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
            (
                topic_id,
                q.get("question_text", ""),
                q.get("option_a", ""),
                q.get("option_b", ""),
                q.get("option_c", ""),
                q.get("option_d", ""),
                (q.get("correct_option") or "").upper()[:1] or "A",
                explanation,
                q.get("difficulty", "medium"),
                q.get("source") or f"pdf_upload:{upload_id}",
                datetime.utcnow().isoformat(),
                meta["confidence"],
                meta["section"],
                meta["sub_topic"],
                meta["pyq_exam"],
                meta["pyq_year"],
                meta["review_notes"],
            ),
        )
        try:
            if cur.lastrowid:
                new_question_ids.append((cur.lastrowid, q.get("question_text", "")))
        except Exception:  # noqa: BLE001 — lastrowid may be missing on some adapters
            pass
        imported += 1

    # Incremental trigram compute for the freshly inserted rows so
    # /admin/duplicates sees them without a full rebuild.
    for qid, qtext in new_question_ids:
        try:
            grams = compute_trigrams(qtext)
            if len(grams) < 20:
                continue
            db.executemany(
                "INSERT OR IGNORE INTO question_trigrams (question_id, trigram) VALUES (?, ?)",
                [(qid, g) for g in grams],
            )
        except Exception as exc:  # noqa: BLE001 — do not fail the import
            current_app.logger.warning(f"trigram compute failed for qid={qid}: {exc}")

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
