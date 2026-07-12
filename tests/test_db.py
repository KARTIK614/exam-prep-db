"""Database seeding and users-table tests."""
import sqlite3


def test_users_table_has_seeded_admin(app):
    db = sqlite3.connect(app.config["DB_PATH"])
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM users WHERE username=?", ("testadmin",)).fetchone()
    db.close()
    assert row is not None
    assert row["role"] == "admin"
    assert row["is_active"] == 1
    # bcrypt/pbkdf2 hash prefix
    assert row["password_hash"].startswith(("pbkdf2:", "scrypt:", "bcrypt:", "argon2:"))


def test_seed_data_populated_topics(app):
    db = sqlite3.connect(app.config["DB_PATH"])
    n_topics = db.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    n_questions = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    db.close()
    assert n_topics > 0
    assert n_questions > 0


def test_settings_defaults_exist(app):
    db = sqlite3.connect(app.config["DB_PATH"])
    keys = {r[0] for r in db.execute("SELECT key FROM settings").fetchall()}
    db.close()
    assert {"target_score", "accuracy_focus", "weakness_threshold"} <= keys
