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

CREATE TABLE IF NOT EXISTS question_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER REFERENCES questions(id),
    test_id INTEGER REFERENCES mock_tests(id),
    reporter TEXT,
    category TEXT,
    note TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS pdf_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    uploaded_by TEXT,
    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
    topic_id INTEGER REFERENCES topics(id),
    num_extracted INTEGER DEFAULT 0,
    num_imported INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    prompt_id INTEGER,
    model TEXT
);

CREATE TABLE IF NOT EXISTS master_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    template TEXT NOT NULL,
    model TEXT DEFAULT 'claude-sonnet-4-6',
    is_default INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _run_alter_migrations(db):
    """Idempotent ALTER TABLEs. SQLite raises "duplicate column" on re-run; we swallow it."""
    migrations = [
        "ALTER TABLE questions ADD COLUMN disabled INTEGER DEFAULT 0",
        "ALTER TABLE questions ADD COLUMN updated_at TEXT",
    ]
    for sql in migrations:
        try:
            db.execute(sql)
        except Exception:
            pass  # column likely already exists


def init_db(app):
    """Create tables if missing + run ALTER migrations. Safe to call on every startup."""
    os.makedirs(os.path.dirname(app.config["DB_PATH"]), exist_ok=True)
    db = sqlite3.connect(app.config["DB_PATH"])
    db.executescript(SCHEMA)
    _run_alter_migrations(db)
    _seed_default_prompt(db)
    db.commit()
    db.close()


DEFAULT_MASTER_PROMPT = """You are an expert exam-question extractor. You will receive one or more PDF pages containing multiple-choice questions (MCQs). Your job is to extract each MCQ into strict JSON.

For every question you find:
- Detect the question text (preserve bilingual formatting: English + Hindi/regional if present, separated by \\n).
- Detect the four options A, B, C, D. If more or fewer options exist, still emit an "options" array of exactly the answer choices you see.
- Detect the correct option letter (A/B/C/D). If not shown in the PDF, set "correct_option" to null and set "confidence" to "low".
- Write a concise 1-3 sentence "explanation" of why the correct answer is right. Draw on general knowledge.
- Assign a "difficulty": "easy" | "medium" | "hard".
- If the question contains mathematical notation, normalize it to inline LaTeX using $...$ delimiters. Do NOT skip math. Fix broken LaTeX if you can infer intent (e.g. "x2" → "$x^2$").
- If the question or an option contains an image reference you cannot read, still emit the question but set "confidence": "low" and add a "notes" field explaining what was unreadable.

Return a JSON object with a single key "questions" whose value is a list. Each item must have exactly these keys:
{
  "question_text": string,
  "option_a": string,
  "option_b": string,
  "option_c": string,
  "option_d": string,
  "correct_option": "A"|"B"|"C"|"D"|null,
  "explanation": string,
  "difficulty": "easy"|"medium"|"hard",
  "confidence": "high"|"medium"|"low",
  "notes": string (optional, only when confidence is not high)
}

Do NOT wrap the JSON in prose or code fences. Output valid JSON only.
"""


def _seed_default_prompt(db):
    """Insert the default master prompt if the table is empty."""
    try:
        count = db.execute("SELECT COUNT(*) FROM master_prompts").fetchone()
        n = count[0] if count else 0
        if n == 0:
            db.execute(
                "INSERT INTO master_prompts (name, template, model, is_default) VALUES (?, ?, ?, 1)",
                ("default", DEFAULT_MASTER_PROMPT, "claude-sonnet-4-6"),
            )
    except Exception:
        pass
