"""Integration test — boot the Flask app with turso_patch active + mocked HTTP.

This catches the specific class of bug where the Turso adapter is missing
a method the app calls at startup (e.g. executescript).
"""
import sys
import pytest


@pytest.fixture
def mocked_turso(monkeypatch, tmp_path):
    """Env vars + module reset + mocked requests.post that always returns success."""
    monkeypatch.setenv("TURSO_DB_URL", "libsql://test.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "faketoken")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("JWT_SECRET", "test-jwt")
    monkeypatch.setenv("EXAM_ADMIN_USER", "admin")
    monkeypatch.setenv("EXAM_ADMIN_PASS", "boot-test-pw")
    monkeypatch.setenv("COOKIE_SECURE", "0")

    # Reset any cached modules so config + turso_patch pick up the env
    for mod in list(sys.modules.keys()):
        if mod in ("app", "config", "auth", "db", "seed", "bp_auth", "bp_main",
                   "bp_tests", "bp_analytics", "bp_errorlog", "bp_api", "bp_doubt",
                   "ai_config", "ai_utils", "turso_patch"):
            sys.modules.pop(mod, None)

    import turso_patch
    # Point DB path at exam_prep so the patch triggers.
    import config
    config.Config.DB_PATH = str(tmp_path / "exam_prep.db")
    config.Config.SESSION_FILE_DIR = str(tmp_path / "session")
    (tmp_path / "session").mkdir()

    class FakeResp:
        status_code = 200
        def json(self_inner):
            # Empty-but-valid Hrana response — covers CREATE, INSERT, SELECT COUNT.
            return {
                "results": [{
                    "type": "ok",
                    "response": {
                        "type": "execute",
                        "result": {"cols": [{"name": "n"}], "rows": [[{"type": "integer", "value": "0"}]]},
                    },
                }],
            }
        def raise_for_status(self_inner):
            pass

    monkeypatch.setattr(turso_patch.requests, "post", lambda *a, **kw: FakeResp())
    return turso_patch


def test_create_app_does_not_crash_with_turso_backend(mocked_turso):
    """The specific regression: TR must have executescript, and seed_admin must survive."""
    from app import create_app
    app = create_app()
    assert app is not None
    # Basic sanity — routes registered
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert "auth.login" in endpoints
    assert "main.index" in endpoints
    assert "tests.setup" in endpoints


def test_login_page_renders_with_turso_backend(mocked_turso):
    from app import create_app
    app = create_app()
    client = app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Exam" in resp.data
