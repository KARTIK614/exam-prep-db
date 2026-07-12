"""
JWT Authentication for Exam Prep Platform.
Provides: login, logout, require_auth decorator.
Uses HS256 with secret from env or generated.
"""
import os, functools, datetime
import jwt
from flask import request, jsonify, session, redirect, url_for, g

SECRET = os.environ.get("JWT_SECRET", os.urandom(32).hex())
TOKEN_EXPIRY = 24  # hours

def create_token(user: str) -> str:
    """Generate JWT for authenticated user"""
    payload = {
        "user": user,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXPIRY),
        "iat": datetime.datetime.utcnow()
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")

def verify_token(token: str) -> dict | None:
    """Verify JWT, return payload or None"""
    try:
        return jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def require_auth(f):
    """Decorator: protect route with JWT"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("auth_token")
        if not token:
            token = session.get("auth_token")
        if not token:
            return redirect(url_for("login_page"))
        
        payload = verify_token(token)
        if not payload:
            session.pop("auth_token", None)
            resp = redirect(url_for("login_page"))
            resp.delete_cookie("auth_token")
            return resp
        
        g.user = payload.get("user", "unknown")
        return f(*args, **kwargs)
    return decorated

# Default credentials (change via env vars)
DEFAULT_USER = os.environ.get("EXAM_USER", "admin")
DEFAULT_PASS = os.environ.get("EXAM_PASS", "change_me_123")
