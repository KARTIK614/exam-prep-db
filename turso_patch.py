#!/usr/bin/env python3
"""
Turso DB connector for Exam Prep Platform.
Monkey-patches sqlite3.connect to use Turso when env vars are set.
Leave app.py untouched — just import this before app.py.
"""
import os, sqlite3
import libsql_experimental as libsql

TURSO_URL = os.environ.get("TURSO_DB_URL", "")
TURSO_TOKEN=os.environ.get("TURSO_AUTH_TOKEN", "")

_original_connect = sqlite3.connect

def _patched_connect(database, *args, **kwargs):
    """Route to Turso if URL matches, else local SQLite"""
    if TURSO_URL and TURSO_TOKEN and ("exam_prep.db" in str(database) or database == TURSO_URL):
        return libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    return _original_connect(database, *args, **kwargs)

# Apply monkey-patch
sqlite3.connect = _patched_connect

print(f"[turso] {'ENABLED' if TURSO_URL else 'DISABLED'} → {TURSO_URL[:50] if TURSO_URL else 'local SQLite'}")
