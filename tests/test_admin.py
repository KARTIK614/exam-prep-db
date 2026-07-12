"""Admin panel — auth gate + basic CRUD."""
import sqlite3
import pytest


@pytest.fixture
def as_admin(client):
    """testadmin was seeded as role='admin' via conftest."""
    client.post("/login", data={"username": "testadmin", "password": "testpass123"})
    return client


@pytest.fixture
def as_user(client, app):
    """Create a non-admin user directly, then log in as them."""
    from werkzeug.security import generate_password_hash
    db = sqlite3.connect(app.config["DB_PATH"])
    db.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role, is_active) "
        "VALUES ('regular', ?, 'user', 1)",
        (generate_password_hash("regularpw"),),
    )
    db.commit()
    db.close()
    client.post("/login", data={"username": "regular", "password": "regularpw"})
    return client


def test_admin_root_redirects_when_not_logged_in(client):
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_admin_root_forbids_regular_user(as_user):
    resp = as_user.get("/admin/", follow_redirects=False)
    # Non-admin gets bounced to /login by the reject path
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_admin_pages_render_for_admin(as_admin):
    for path in ("/admin/", "/admin/flags", "/admin/questions", "/admin/topics",
                 "/admin/users", "/admin/prompts", "/admin/uploads"):
        r = as_admin.get(path)
        assert r.status_code == 200, path


def test_admin_can_add_and_delete_topic(as_admin, app):
    r = as_admin.post(
        "/admin/topics",
        data={"name": "Test Topic New", "subject": "Test", "paper": "I", "weightage": "5"},
    )
    assert r.status_code in (302, 200)

    db = sqlite3.connect(app.config["DB_PATH"])
    row = db.execute("SELECT id FROM topics WHERE name=?", ("Test Topic New",)).fetchone()
    db.close()
    assert row is not None
    topic_id = row[0]

    r = as_admin.post(f"/admin/topics/{topic_id}/delete")
    assert r.status_code in (302, 200)


def test_flag_action_endpoint_gated_by_admin(as_user):
    r = as_user.post("/admin/api/flag/999/resolve")
    # Non-admin JSON endpoints get 403
    assert r.status_code in (302, 403)


def test_admin_disable_question_flow(as_admin, app):
    # Disable question 1
    r = as_admin.post("/admin/api/question/1/toggle_disabled")
    assert r.status_code == 200
    assert r.get_json()["disabled"] == 1

    db = sqlite3.connect(app.config["DB_PATH"])
    row = db.execute("SELECT disabled FROM questions WHERE id=1").fetchone()
    db.close()
    assert row[0] == 1

    # Toggle back
    as_admin.post("/admin/api/question/1/toggle_disabled")
