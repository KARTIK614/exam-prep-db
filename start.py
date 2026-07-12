#!/usr/bin/env python3
"""Exam Prep Platform — Startup Script for Render + Turso"""
import os, sys

# If DB exists locally but TURSO_DB_URL is set, migrate data to Turso
local_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'exam_prep.db')
turso_url = os.environ.get('TURSO_DB_URL', '')
turso_token = os.environ.get('TURSO_AUTH_TOKEN', '')

if os.path.exists(local_db) and turso_url and turso_token:
    print("[migrate] Local DB found + TURSO configured. Migrating...")
    try:
        import sqlite3, libsql_experimental
        # Read local schema + data
        src = sqlite3.connect(local_db)
        
        # Connect to Turso
        dst = libsql_experimental.connect(
            database=turso_url,
            auth_token=turso_token
        )
        
        # Copy schema
        schema = src.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL").fetchall()
        for (sql,) in schema:
            try:
                dst.execute(sql)
            except:
                pass  # Table already exists
        
        # Copy data
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for table in tables:
            if table == 'sqlite_sequence': continue
            rows = src.execute(f"SELECT * FROM [{table}]").fetchall()
            if not rows: continue
            cols = [c[1] for c in src.execute(f"PRAGMA table_info([{table}])").fetchall()]
            placeholders = ','.join(['?'] * len(cols))
            cols_str = ','.join(f'[{c}]' for c in cols)
            dst.executemany(f"INSERT OR IGNORE INTO [{table}] ({cols_str}) VALUES ({placeholders})", rows)
        
        src.close()
        dst.close()
        print(f"[migrate] Done. {len(tables)-1} tables migrated.")
    except Exception as e:
        print(f"[migrate] Error: {e}")

# Launch Flask
from app import app
if __name__ == '__main__':
    app.run()
