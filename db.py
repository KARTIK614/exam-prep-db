"""Database helpers — connection lifecycle + schema init."""
import os
import sqlite3
from flask import g, current_app


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DB_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE, subject TEXT, paper TEXT, weightage INTEGER DEFAULT 5
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER REFERENCES topics(id),
    question_text TEXT, option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
    correct_option TEXT, explanation TEXT, difficulty TEXT DEFAULT 'medium',
    source TEXT, language TEXT DEFAULT 'bilingual'
);
CREATE TABLE IF NOT EXISTS mock_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, completed_at TEXT, paper TEXT, total_questions INTEGER,
    score REAL, max_score INTEGER, time_taken_sec INTEGER, status TEXT DEFAULT 'in_progress'
);
CREATE TABLE IF NOT EXISTS test_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER REFERENCES mock_tests(id),
    question_id INTEGER, selected_option TEXT, is_correct INTEGER,
    time_spent_sec REAL, confidence TEXT DEFAULT 'medium',
    error_type TEXT
);
CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER REFERENCES mock_tests(id),
    question_id INTEGER, topic_id INTEGER REFERENCES topics(id),
    selected_option TEXT, correct_option TEXT, error_type TEXT,
    root_cause TEXT, resolved INTEGER DEFAULT 0, created_at TEXT,
    redo_1_score REAL, redo_2_score REAL
);
CREATE TABLE IF NOT EXISTS topic_mastery (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER REFERENCES topics(id) UNIQUE,
    diagnostic_score REAL, current_score REAL, study_hours REAL DEFAULT 0,
    status TEXT DEFAULT 'not_started', last_studied TEXT, test_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT, topic_id INTEGER REFERENCES topics(id),
    duration_min INTEGER, mcqs_solved INTEGER, score REAL, notes TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT
);
INSERT OR IGNORE INTO settings (key, value) VALUES ('target_score', '75');
INSERT OR IGNORE INTO settings (key, value) VALUES ('accuracy_focus', 'true');
INSERT OR IGNORE INTO settings (key, value) VALUES ('weakness_threshold', '60');

CREATE TABLE IF NOT EXISTS doubt_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT UNIQUE NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);
"""


def init_db(app):
    """Create tables if missing. Safe to call on every startup."""
    os.makedirs(os.path.dirname(app.config["DB_PATH"]), exist_ok=True)
    db = sqlite3.connect(app.config["DB_PATH"])
    db.executescript(SCHEMA)
    db.commit()
    db.close()
