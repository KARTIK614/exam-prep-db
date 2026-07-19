"""Real-Turso smoke tests for the Hrana HTTP adapter (turso_patch).

These tests exercise the actual `TURSO_DB_URL` endpoint, not a mock. They
regression-guard the exact silent-failure that hit the extraction-push:
Hrana returning `{"type":"error", ...}` inside a 200-OK envelope while
`turso_patch` swallowed it and produced an empty cursor with `lastrowid=None`.

Requirements:
- TURSO_DB_URL and TURSO_AUTH_TOKEN in the environment (or a dedicated
  TURSO_TEST_URL / TURSO_TEST_TOKEN pair which take precedence).
- The tests create/drop a small `_probe_smoke` scratch table and insert 3
  rows into `questions` tagged `source='__smoke_test__'`, then clean up.
  Safe to run against prod — cleanup runs even on failure via fixtures.

Skipped if no Turso credentials are set.
"""
import importlib
import os
import sqlite3
import sys

import pytest

# Prefer a dedicated test branch if configured, otherwise fall back to the
# main Turso URL. Tests are still isolated by the scratch table + cleanup.
_TEST_URL = os.environ.get("TURSO_TEST_URL") or os.environ.get("TURSO_DB_URL")
_TEST_TOKEN = os.environ.get("TURSO_TEST_TOKEN") or os.environ.get("TURSO_AUTH_TOKEN")


pytestmark = pytest.mark.skipif(
    not (_TEST_URL and _TEST_TOKEN),
    reason="TURSO_DB_URL / TURSO_AUTH_TOKEN not set — skipping real-Turso smoke tests",
)


@pytest.fixture(scope="module")
def turso_conn():
    """Set env vars, (re)load turso_patch so its module-level URL/AUTH pick
    them up, then hand back a routed sqlite3 connection to the shared DB.

    We reload turso_patch because the module reads TURSO_DB_URL/AUTH at
    import time — if it was imported earlier under different env, its REST
    URL will be stale.
    """
    os.environ["TURSO_DB_URL"] = _TEST_URL
    os.environ["TURSO_AUTH_TOKEN"] = _TEST_TOKEN
    if "turso_patch" in sys.modules:
        importlib.reload(sys.modules["turso_patch"])
    else:
        import turso_patch  # noqa: F401
    # `exam_prep` in the path triggers the patched connect → TR.
    con = sqlite3.connect("data/exam_prep.db")
    yield con
    con.close()


@pytest.fixture
def probe_table(turso_conn):
    """Create a fresh `_probe_smoke` table, drop it on teardown."""
    turso_conn.execute("DROP TABLE IF EXISTS _probe_smoke")
    turso_conn.execute(
        "CREATE TABLE _probe_smoke (id INTEGER PRIMARY KEY AUTOINCREMENT, a TEXT)"
    )
    yield turso_conn
    turso_conn.execute("DROP TABLE IF EXISTS _probe_smoke")


# ─── Regression tests for silent-failure ──────────────────────────────────


def test_insert_with_unknown_column_raises(probe_table):
    """The exact bug that hit extraction-push: INSERT referencing a column
    that doesn't exist should raise, not silently no-op with lastrowid=None."""
    with pytest.raises(sqlite3.DatabaseError):
        probe_table.execute(
            "INSERT INTO _probe_smoke (id, a, bogus_col) VALUES (1, 'x', 'y')"
        )


def test_valid_insert_returns_lastrowid(probe_table):
    """A well-formed INSERT must return a non-None lastrowid — the caller-side
    guard in push_extracted_to_turso relies on this to detect silent losses."""
    res = probe_table.execute("INSERT INTO _probe_smoke (a) VALUES (?)", ("v1",))
    assert res.lastrowid is not None, "lastrowid should not be None for successful INSERT"
    assert isinstance(res.lastrowid, int)
    assert res.lastrowid > 0


def test_select_from_missing_table_raises(turso_conn):
    """Reading from a table that doesn't exist should raise. Historically this
    also silently produced empty cursors."""
    with pytest.raises(sqlite3.DatabaseError):
        turso_conn.execute("SELECT * FROM _definitely_not_a_table_xyz").fetchall()


# ─── Bonus: end-to-end schema check against real `questions` table ────────


def test_questions_table_has_new_columns(turso_conn):
    """After the migration, `disabled` and `updated_at` must be present.
    This is the schema-drift sentinel — if someone drops the columns or a
    fresh Turso branch is used without running the migration, this test
    turns red."""
    rows = turso_conn.execute("PRAGMA table_info(questions)").fetchall()
    col_names = {r[1] for r in rows}
    assert "disabled" in col_names, f"missing 'disabled' column; have: {sorted(col_names)}"
    assert "updated_at" in col_names, f"missing 'updated_at' column; have: {sorted(col_names)}"


def test_insert_with_disabled_and_updated_at_persists(turso_conn):
    """Full bulk-insert smoke: the `bp_admin.upload_import` INSERT shape
    (10 base columns + `disabled` + `updated_at`) must round-trip. This is
    the exact statement that failed silently pre-fix."""
    before = turso_conn.execute(
        "SELECT COUNT(*) FROM questions WHERE source = '__smoke_test__'"
    ).fetchone()[0]

    inserted_ids = []
    try:
        for i in range(3):
            res = turso_conn.execute(
                "INSERT INTO questions (topic_id, question_text, option_a, option_b, "
                "option_c, option_d, correct_option, explanation, difficulty, source, "
                "disabled, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    25, f"smoke {i}", "a", "b", "c", "d", "A", "",
                    "medium", "__smoke_test__", 0, "2026-07-18T00:00:00",
                ),
            )
            assert res.lastrowid is not None, f"row {i} lastrowid was None"
            inserted_ids.append(res.lastrowid)

        after = turso_conn.execute(
            "SELECT COUNT(*) FROM questions WHERE source = '__smoke_test__'"
        ).fetchone()[0]
        assert after == before + 3, f"expected {before + 3} rows, got {after}"

        # Verify the new columns actually persisted the values we sent.
        sample = turso_conn.execute(
            "SELECT disabled, updated_at FROM questions WHERE id = ?", (inserted_ids[0],)
        ).fetchone()
        assert sample is not None
        assert sample["disabled"] == 0
        assert sample["updated_at"] == "2026-07-18T00:00:00"
    finally:
        turso_conn.execute("DELETE FROM questions WHERE source = '__smoke_test__'")
