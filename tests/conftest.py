"""Pytest fixtures. Each test gets a fresh temp DB + fresh app."""
import os
import sys
import tempfile
import shutil
import pytest

# Ensure project root is importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def tmp_env(monkeypatch, tmp_path):
    """Set required env vars + isolate DB + session dir to a temp path."""
    session_dir = tmp_path / "flask_session"
    session_dir.mkdir()
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("EXAM_ADMIN_USER", "testadmin")
    monkeypatch.setenv("EXAM_ADMIN_PASS", "testpass123")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")

    # Reset any cached Config values by reimporting
    for mod in list(sys.modules.keys()):
        if mod in ("app", "config", "auth", "db", "seed", "bp_auth", "bp_main",
                   "bp_tests", "bp_analytics", "bp_errorlog", "bp_api", "bp_doubt",
                   "bp_review", "sr",
                   "ai_config", "ai_utils"):
            sys.modules.pop(mod, None)

    # Rewrite config.DB_PATH / SESSION_FILE_DIR to point at tmp
    import config
    config.Config.DB_PATH = str(tmp_path / "test.db")
    config.Config.SESSION_FILE_DIR = str(session_dir)
    yield tmp_path


@pytest.fixture
def app(tmp_env):
    """Return a freshly created Flask app rooted at a temp DB."""
    from app import create_app
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()
