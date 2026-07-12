"""Mocked tests for the Turso HTTP adapter (turso_patch)."""
import importlib
import json
import sqlite3
import sys
import pytest


def _mk_response(payload, status=200):
    """Build a requests.Response stand-in with .json(), .raise_for_status(), .status_code."""
    class R:
        status_code = status
        def json(self_inner):
            return payload
        def raise_for_status(self_inner):
            if not (200 <= status < 300):
                raise Exception(f"HTTP {status}")
    return R()


def _hrana_exec_result(cols, rows, last_insert_rowid=None):
    """Build a Hrana v2 pipeline response for one execute statement."""
    return {
        "results": [{
            "type": "ok",
            "response": {
                "type": "execute",
                "result": {
                    "cols": [{"name": c} for c in cols],
                    "rows": [[{"type": _guess_type(v), "value": None if v is None else str(v)} for v in row] for row in rows],
                    "last_insert_rowid": str(last_insert_rowid) if last_insert_rowid else None,
                }
            }
        }]
    }


def _guess_type(v):
    if v is None: return "null"
    if isinstance(v, bool) or isinstance(v, int): return "integer"
    if isinstance(v, float): return "float"
    return "text"


@pytest.fixture
def turso_env(monkeypatch):
    """Reload turso_patch with real-looking env vars so its module code activates."""
    monkeypatch.setenv("TURSO_DB_URL", "libsql://test.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "faketoken")
    # Reload so module-level TURSO_URL/AUTH pick up the env
    if "turso_patch" in sys.modules:
        del sys.modules["turso_patch"]
    import turso_patch  # re-imports and re-installs the sqlite3.connect patch
    return turso_patch


def test_connect_returns_TR_for_exam_prep_path(turso_env, monkeypatch):
    """sqlite3.connect(path-with-exam_prep) should give us a TR when Turso env is set."""
    monkeypatch.setattr(turso_env.requests, "post", lambda *a, **kw: _mk_response({"results": [{}]}))
    conn = sqlite3.connect("/tmp/data/exam_prep.db")
    assert isinstance(conn, turso_env.TR)


def test_connect_passes_through_for_other_paths(turso_env):
    """Paths without 'exam_prep' fall through to real sqlite3."""
    conn = sqlite3.connect(":memory:")
    assert not isinstance(conn, turso_env.TR)
    conn.close()


def test_row_supports_int_and_string_indexing(turso_env, monkeypatch):
    monkeypatch.setattr(
        turso_env.requests, "post",
        lambda *a, **kw: _mk_response(_hrana_exec_result(["id", "name"], [[1, "alpha"]])),
    )
    conn = sqlite3.connect("/tmp/data/exam_prep.db")
    row = conn.execute("SELECT id, name FROM t").fetchone()
    assert row[0] == 1
    assert row["name"] == "alpha"
    assert row.get("missing") is None
    assert "name" in row
    assert list(row.keys()) == ["id", "name"]
    assert len(row) == 2


def test_fetchall_returns_list_of_rows(turso_env, monkeypatch):
    monkeypatch.setattr(
        turso_env.requests, "post",
        lambda *a, **kw: _mk_response(_hrana_exec_result(["id"], [[1], [2], [3]])),
    )
    conn = sqlite3.connect("/tmp/data/exam_prep.db")
    rows = conn.execute("SELECT id FROM t").fetchall()
    assert len(rows) == 3
    assert [r["id"] for r in rows] == [1, 2, 3]


def test_executescript_splits_and_sends(turso_env, monkeypatch):
    """executescript should break the script on semicolons and send each stmt."""
    captured = []
    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append(json)
        return _mk_response({"results": [{"type": "ok"}]})
    monkeypatch.setattr(turso_env.requests, "post", fake_post)

    conn = sqlite3.connect("/tmp/data/exam_prep.db")
    conn.executescript(
        "CREATE TABLE a (id INTEGER); "
        "CREATE TABLE b (name TEXT); "
        "INSERT INTO b (name) VALUES ('has ; inside string');"
    )
    # Should have posted at least one batch containing all 3 statements
    assert captured, "no HTTP request was made"
    all_stmts = [req["stmt"]["sql"] for batch in captured for req in batch["requests"]]
    assert any("CREATE TABLE a" in s for s in all_stmts)
    assert any("CREATE TABLE b" in s for s in all_stmts)
    assert any("has ; inside string" in s for s in all_stmts)


def test_execute_with_tuple_params_sends_typed_args(turso_env, monkeypatch):
    seen = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        seen["json"] = json
        return _mk_response(_hrana_exec_result([], []))
    monkeypatch.setattr(turso_env.requests, "post", fake_post)

    conn = sqlite3.connect("/tmp/data/exam_prep.db")
    conn.execute("INSERT INTO t VALUES (?, ?, ?)", (1, "alpha", None))

    args = seen["json"]["requests"][0]["stmt"]["args"]
    assert args[0] == {"type": "integer", "value": "1"}
    assert args[1] == {"type": "text", "value": "alpha"}
    assert args[2] == {"type": "null"}


def test_split_sql_respects_quoted_semicolons(turso_env):
    stmts = turso_env._split_sql(
        "CREATE TABLE x (n TEXT); INSERT INTO x VALUES ('a;b'); INSERT INTO x VALUES ('c')"
    )
    assert len(stmts) == 3
    assert "a;b" in stmts[1]


def test_split_sql_handles_escaped_single_quote(turso_env):
    stmts = turso_env._split_sql("INSERT INTO t VALUES ('it''s'); SELECT 1")
    assert len(stmts) == 2
    assert "it''s" in stmts[0]
