"""E2E route smoke tests. Uses the seeded admin from conftest."""
import pytest


@pytest.fixture
def logged_in(client):
    client.post("/login", data={"username": "testadmin", "password": "testpass123"})
    return client


def test_dashboard_renders(logged_in):
    resp = logged_in.get("/")
    assert resp.status_code == 200


def test_test_setup_renders(logged_in):
    resp = logged_in.get("/test/setup")
    assert resp.status_code == 200


def test_analytics_renders(logged_in):
    resp = logged_in.get("/analytics")
    assert resp.status_code == 200


def test_errorlog_renders(logged_in):
    resp = logged_in.get("/errorlog")
    assert resp.status_code == 200


def test_api_settings_accepts_json(logged_in):
    resp = logged_in.post("/api/settings", json={"target_score": "80"})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_take_without_active_test_redirects_to_setup(logged_in):
    resp = logged_in.get("/test/take", follow_redirects=False)
    assert resp.status_code == 302
    assert "/test/setup" in resp.headers["Location"]


def test_results_for_missing_test_redirects_home(logged_in):
    resp = logged_in.get("/results/999999", follow_redirects=False)
    assert resp.status_code == 302


def test_static_asset_served(logged_in):
    resp = logged_in.get("/static/script.js")
    assert resp.status_code == 200
    assert b"fetch" in resp.data
