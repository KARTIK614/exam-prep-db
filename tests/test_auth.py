"""E2E tests for the auth flow."""


def test_unauthenticated_root_redirects_to_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_unauthenticated_api_returns_401_json(client):
    resp = client.get("/api/question/0")
    assert resp.status_code == 401
    assert resp.is_json
    assert resp.get_json() == {"error": "Unauthorized"}


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Exam" in resp.data
    assert b"password" in resp.data.lower()


def test_login_with_bad_credentials(client):
    resp = client.post("/login", data={"username": "wrong", "password": "wrong"})
    assert resp.status_code == 200
    assert b"Invalid credentials" in resp.data


def test_login_with_seeded_admin(client):
    resp = client.post(
        "/login",
        data={"username": "testadmin", "password": "testpass123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/") or resp.headers["Location"].endswith("/index")
    cookies = resp.headers.getlist("Set-Cookie")
    assert any("auth_token=" in c for c in cookies)


def test_login_then_access_dashboard(client):
    client.post("/login", data={"username": "testadmin", "password": "testpass123"})
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data or b"dashboard" in resp.data.lower()


def test_logout_clears_cookie(client):
    client.post("/login", data={"username": "testadmin", "password": "testpass123"})
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    # After logout the dashboard should redirect again
    dash = client.get("/", follow_redirects=False)
    assert dash.status_code == 302
    assert "/login" in dash.headers["Location"]


def test_login_when_already_logged_in_redirects_home(client):
    client.post("/login", data={"username": "testadmin", "password": "testpass123"})
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/") or "/index" in resp.headers["Location"]


def test_invalid_jwt_cookie_redirects_to_login(client):
    client.set_cookie(key="auth_token", value="not-a-real-jwt")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
