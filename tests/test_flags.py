"""E2E tests for the question-flagging flow."""
import pytest


@pytest.fixture
def logged_in(client):
    client.post("/login", data={"username": "testadmin", "password": "testpass123"})
    return client


def test_flag_question_creates_row(logged_in, app):
    resp = logged_in.post(
        "/api/flag_question",
        json={"question_id": 1, "test_id": None, "category": "bad_latex", "note": "sqrt broken"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}

    import sqlite3
    db = sqlite3.connect(app.config["DB_PATH"])
    row = db.execute(
        "SELECT question_id, category, note, status FROM question_flags ORDER BY id DESC LIMIT 1"
    ).fetchone()
    db.close()
    assert row == (1, "bad_latex", "sqrt broken", "open")


def test_flag_requires_question_id(logged_in):
    resp = logged_in.post("/api/flag_question", json={})
    assert resp.status_code == 400
    assert "question_id" in resp.get_json()["error"]


def test_flag_bad_category_falls_back_to_other(logged_in, app):
    logged_in.post(
        "/api/flag_question",
        json={"question_id": 1, "category": "not_a_real_category"},
    )
    import sqlite3
    db = sqlite3.connect(app.config["DB_PATH"])
    row = db.execute("SELECT category FROM question_flags ORDER BY id DESC LIMIT 1").fetchone()
    db.close()
    assert row[0] == "other"


def test_flag_endpoint_requires_auth(client):
    resp = client.post("/api/flag_question", json={"question_id": 1})
    assert resp.status_code == 401
