"""Unit tests for the Leitner-5 primitives in sr.py."""
from datetime import date, timedelta

import sqlite3

from sr import (
    BOX_INTERVALS_DAYS,
    DROP_ON_MISS,
    MAX_BOX,
    next_box,
    next_due,
    days_until_due,
    record_review,
    get_queue_summary,
    get_due_reviews,
)


def test_next_box_correct_promotes():
    for b in range(1, MAX_BOX):
        assert next_box(b, True) == b + 1


def test_next_box_correct_caps_at_5():
    assert next_box(5, True) == 5


def test_next_box_wrong_drops_per_map():
    assert next_box(1, False) == 1
    assert next_box(2, False) == 1
    assert next_box(3, False) == 1
    assert next_box(4, False) == 2
    assert next_box(5, False) == 3
    assert DROP_ON_MISS == {1: 1, 2: 1, 3: 1, 4: 2, 5: 3}


def test_next_due_uses_box_intervals():
    today = date(2026, 7, 18)
    for box, days in BOX_INTERVALS_DAYS.items():
        got = next_due(box, from_date=today)
        expected = (today + timedelta(days=days)).isoformat()
        assert got == expected, f"box {box}: got {got}, expected {expected}"


def test_days_until_due():
    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()
    assert days_until_due(tomorrow) == 1
    assert days_until_due(today.isoformat()) == 0
    assert days_until_due(yesterday) == -1
    assert days_until_due("") == 0
    assert days_until_due(None) == 0
    assert days_until_due("not-a-date") == 0


def _make_test_db():
    """Fresh in-memory sqlite with error_log + questions + topics stubs."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE topics (id INTEGER PRIMARY KEY, name TEXT, paper TEXT);
        CREATE TABLE questions (
            id INTEGER PRIMARY KEY, topic_id INTEGER, question_text TEXT,
            option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
            correct_option TEXT, explanation TEXT, difficulty TEXT,
            disabled INTEGER DEFAULT 0
        );
        CREATE TABLE error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER, question_id INTEGER, topic_id INTEGER,
            selected_option TEXT, correct_option TEXT, error_type TEXT,
            root_cause TEXT, resolved INTEGER DEFAULT 0, created_at TEXT,
            redo_1_score REAL, redo_2_score REAL,
            sr_box INTEGER DEFAULT 1,
            sr_due_at TEXT,
            sr_last_reviewed TEXT
        );
        """
    )
    con.execute("INSERT INTO topics (id, name, paper) VALUES (1, 'DBMS', 'II')")
    con.execute(
        "INSERT INTO questions (id, topic_id, question_text, correct_option) "
        "VALUES (10, 1, 'q?', 'A')"
    )
    return con


def test_record_review_promotes_on_correct():
    con = _make_test_db()
    today = date.today()
    con.execute(
        "INSERT INTO error_log (id, question_id, topic_id, created_at, "
        "sr_box, sr_due_at) VALUES (1, 10, 1, ?, 2, ?)",
        (today.isoformat(), today.isoformat()),
    )

    r = record_review(con, 1, True)
    assert r is not None
    assert r["new_box"] == 3
    # box 3 interval is 7 days from today
    expected = (today + timedelta(days=7)).isoformat()
    assert r["next_due"] == expected

    row = con.execute("SELECT sr_box, sr_due_at FROM error_log WHERE id=1").fetchone()
    assert row["sr_box"] == 3
    assert row["sr_due_at"] == expected


def test_record_review_drops_on_wrong():
    con = _make_test_db()
    con.execute(
        "INSERT INTO error_log (id, question_id, topic_id, sr_box, sr_due_at) "
        "VALUES (1, 10, 1, 5, ?)",
        (date.today().isoformat(),),
    )
    r = record_review(con, 1, False)
    # missing at box 5 falls to 3
    assert r["new_box"] == 3


def test_record_review_missing_row():
    con = _make_test_db()
    assert record_review(con, 999, True) is None


def test_get_queue_summary_counts_by_box():
    con = _make_test_db()
    con.execute(
        "INSERT INTO error_log (question_id, topic_id, sr_box, sr_due_at) "
        "VALUES (10, 1, 1, ?)", (date.today().isoformat(),)
    )
    con.execute(
        "INSERT INTO error_log (question_id, topic_id, sr_box, sr_due_at) "
        "VALUES (10, 1, 3, ?)", (date.today().isoformat(),)
    )
    con.execute(
        "INSERT INTO error_log (question_id, topic_id, sr_box, sr_due_at) "
        "VALUES (10, 1, 5, ?)",
        ((date.today() + timedelta(days=30)).isoformat(),),
    )
    s = get_queue_summary(con)
    assert s["total"] == 3
    assert s["due_today"] == 2  # only the two due today (box 5 is due later)
    assert s["by_box"][1] == 1
    assert s["by_box"][3] == 1
    assert s["by_box"][5] == 1


def test_get_due_reviews_filters_disabled():
    con = _make_test_db()
    con.execute("UPDATE questions SET disabled=1 WHERE id=10")
    con.execute(
        "INSERT INTO error_log (question_id, topic_id, sr_box, sr_due_at) "
        "VALUES (10, 1, 1, ?)", (date.today().isoformat(),)
    )
    rows = get_due_reviews(con)
    assert list(rows) == []


def test_full_cycle_correct_correct_wrong():
    """Realistic Leitner flow: card starts at box 1, gets promoted twice,
    then misses at box 3 (drops back to box 1)."""
    con = _make_test_db()
    con.execute(
        "INSERT INTO error_log (question_id, topic_id, sr_box, sr_due_at) "
        "VALUES (10, 1, 1, ?)", (date.today().isoformat(),)
    )
    (eid,) = con.execute("SELECT id FROM error_log LIMIT 1").fetchone()
    r = record_review(con, eid, True)
    assert r["new_box"] == 2
    r = record_review(con, eid, True)
    assert r["new_box"] == 3
    r = record_review(con, eid, False)
    assert r["new_box"] == 1  # box 3 miss goes to 1
