"""JWT authentication + users-table password verification."""
import datetime
import sqlite3
from flask import request, jsonify, session, redirect, url_for, g, current_app
import jwt
from werkzeug.security import generate_password_hash, check_password_hash


def create_token(username: str) -> str:
    payload = {
        "user": username,
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=current_app.config["JWT_EXPIRY_HOURS"]
        ),
        "iat": datetime.datetime.now(datetime.timezone.utc),
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm="HS256")


def verify_token(token: str):
    try:
        return jwt.decode(
            token,
            current_app.config["JWT_SECRET"],
            algorithms=["HS256"],
            options={"verify_exp": True, "verify_iat": True},
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def hash_password(pw: str) -> str:
    return generate_password_hash(pw)


def verify_password(pw: str, pw_hash: str) -> bool:
    return check_password_hash(pw_hash, pw)


def get_user(username: str):
    from db import get_db
    return get_db().execute(
        "SELECT * FROM users WHERE username=? AND is_active=1",
        (username,),
    ).fetchone()


def touch_last_login(username: str):
    from db import get_db
    db = get_db()
    db.execute(
        "UPDATE users SET last_login=? WHERE username=?",
        (datetime.datetime.now(datetime.timezone.utc).isoformat(), username),
    )
    db.commit()


def seed_admin_if_empty(app):
    """Seed one admin from env vars if the users table is empty."""
    db = sqlite3.connect(app.config["DB_PATH"])
    db.row_factory = sqlite3.Row
    try:
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count > 0:
            return
        username = app.config.get("SEED_ADMIN_USER")
        password = app.config.get("SEED_ADMIN_PASS")
        if not password:
            app.logger.warning(
                "Users table empty and EXAM_ADMIN_PASS not set — no admin seeded. "
                "Set EXAM_ADMIN_USER and EXAM_ADMIN_PASS env vars."
            )
            return
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), "admin"),
        )
        db.commit()
        app.logger.info(f"Seeded admin user: {username}")
    finally:
        db.close()


# Endpoints that should NOT trigger the auth check.
_PUBLIC_ENDPOINTS = {None, "static", "auth.login", "auth.logout", "diag.diag", "diag.force_seed"}


def check_auth():
    """`before_request` handler: reject unauthenticated requests to protected routes."""
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return
    token = request.cookies.get("auth_token") or session.get("auth_token")
    if not token:
        return _reject()
    payload = verify_token(token)
    if not payload:
        session.pop("auth_token", None)
        return _reject()
    g.user = payload.get("user")


def _reject():
    if request.path.startswith("/api/"):
        return jsonify({"error": "Unauthorized"}), 401
    return redirect(url_for("auth.login"))
