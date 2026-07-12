"""Diagnostic + manual admin seed endpoints.

Both routes require the URL to contain the first 16 chars of JWT_SECRET,
so only someone with dashboard access can call them. Removed once the
platform is stable — kept for one-time bootstrap.
"""
import sqlite3
from flask import Blueprint, jsonify, current_app, request
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db

bp = Blueprint("diag", __name__)


def _authorized(token):
    secret = current_app.config.get("JWT_SECRET") or ""
    return bool(secret) and token == secret[:16]


@bp.route("/diag/<token>")
def diag(token):
    if not _authorized(token):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    out = {"tables": {}, "config": {
        "SEED_ADMIN_USER": current_app.config.get("SEED_ADMIN_USER"),
        "SEED_ADMIN_PASS_set": bool(current_app.config.get("SEED_ADMIN_PASS")),
        "IS_PROD": current_app.config.get("IS_PROD"),
        "DB_PATH": current_app.config.get("DB_PATH"),
    }}
    for tbl in ("topics", "questions", "mock_tests", "users", "settings"):
        try:
            row = db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
            out["tables"][tbl] = row[0] if row else None
        except Exception as exc:
            out["tables"][tbl] = f"ERROR: {exc}"
    try:
        users = db.execute("SELECT id, username, role, is_active, length(password_hash) as pwlen FROM users").fetchall()
        out["users_list"] = [{"id": u[0], "username": u[1], "role": u[2], "is_active": u[3], "pwlen": u[4]} for u in users]
    except Exception as exc:
        out["users_list"] = f"ERROR: {exc}"

    # Optional probes to debug the seed<->login password mismatch.
    # ?probe_env=1     — report length + first/last char of EXAM_ADMIN_PASS as seen by the app
    # ?probe_pw=<val>  — check if the given password matches the stored admin hash
    if request.args.get("probe_env") == "1":
        pw = current_app.config.get("SEED_ADMIN_PASS") or ""
        out["env_probe"] = {
            "len": len(pw),
            "first": pw[:1],
            "last": pw[-1:] if pw else "",
            "sha256_prefix": __import__("hashlib").sha256(pw.encode()).hexdigest()[:16],
        }
    probe_pw = request.args.get("probe_pw")
    if probe_pw is not None:
        row = db.execute(
            "SELECT password_hash FROM users WHERE username=?",
            (current_app.config.get("SEED_ADMIN_USER", "admin"),),
        ).fetchone()
        stored = row[0] if row else None
        out["pw_probe"] = {
            "supplied_len": len(probe_pw),
            "stored_hash_present": bool(stored),
            "matches": bool(stored and check_password_hash(stored, probe_pw)),
        }
    return jsonify(out)


@bp.route("/setup/seed/<token>", methods=["POST", "GET"])
def force_seed(token):
    """Force-seed or update the admin user from env vars. Idempotent."""
    if not _authorized(token):
        return jsonify({"error": "forbidden"}), 403
    username = current_app.config.get("SEED_ADMIN_USER")
    password = current_app.config.get("SEED_ADMIN_PASS")
    if not (username and password):
        return jsonify({"error": "EXAM_ADMIN_USER or EXAM_ADMIN_PASS not set"}), 400

    db = get_db()
    # Make sure users table exists
    try:
        db.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "username TEXT UNIQUE NOT NULL, "
            "password_hash TEXT NOT NULL, "
            "role TEXT DEFAULT 'user', "
            "is_active INTEGER DEFAULT 1, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
            "last_login TEXT)"
        )
    except Exception as exc:
        return jsonify({"error": f"table create: {exc}"}), 500

    pw_hash = generate_password_hash(password)
    existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        db.execute(
            "UPDATE users SET password_hash=?, role='admin', is_active=1 WHERE username=?",
            (pw_hash, username),
        )
        action = "updated"
    else:
        db.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, 'admin', 1)",
            (username, pw_hash),
        )
        action = "inserted"
    db.commit()
    return jsonify({"status": "ok", "username": username, "action": action})
