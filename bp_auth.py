"""Auth blueprint — /login and /logout."""
from flask import Blueprint, request, render_template, redirect, url_for, session, current_app

from auth import create_token, get_user, verify_password, touch_last_login, verify_token

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    # If already authenticated, skip the form.
    existing = request.cookies.get("auth_token") or session.get("auth_token")
    if existing and verify_token(existing):
        return redirect(url_for("main.index"))

    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = get_user(username)
        if user and verify_password(password, user["password_hash"]):
            token = create_token(username)
            resp = redirect(url_for("main.index"))
            resp.set_cookie(
                "auth_token",
                token,
                httponly=True,
                samesite="Lax",
                secure=current_app.config["COOKIE_SECURE"],
                max_age=int(current_app.config["JWT_EXPIRY_HOURS"]) * 3600,
                path="/",
            )
            session["auth_token"] = token
            touch_last_login(username)
            return resp
        error = "Invalid credentials"
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    session.pop("auth_token", None)
    resp = redirect(url_for("auth.login"))
    resp.delete_cookie("auth_token", path="/")
    return resp
