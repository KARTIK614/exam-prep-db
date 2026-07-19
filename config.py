"""Application configuration. Reads env vars; fails fast in production if secrets missing."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # Detect Render (auto-set by the platform) as our "production" signal.
    IS_PROD = bool(os.environ.get("RENDER"))

    # Session + JWT secrets — required in prod, dev-only fallback allowed locally.
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
    JWT_SECRET = os.environ.get("JWT_SECRET")
    JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))

    # Cookie flags
    COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1" if IS_PROD else "0") == "1"

    # Filesystem paths
    DB_PATH = os.path.join(BASE_DIR, "data", "exam_prep.db")
    SESSION_TYPE = "filesystem"
    SESSION_FILE_DIR = os.path.join(BASE_DIR, "data", "flask_session")

    # Seed admin credentials (only used when users table is empty on first boot).
    SEED_ADMIN_USER = os.environ.get("EXAM_ADMIN_USER", "admin")
    SEED_ADMIN_PASS = os.environ.get("EXAM_ADMIN_PASS")

    # Notes / AI. Gemini is called via the Generative Language REST API using
    # `GEMINI_API_KEY` (read at call time in ai_utils.call_gemini) — no CLI
    # binary needed. `GEMINI_MODEL` is an optional override (defaults to
    # gemini-2.5-flash in ai_utils).
    NOTES_DIR = os.path.join(BASE_DIR, "study-notes")
