#!/usr/bin/env python3
"""Migrate local SQLite data to Turso cloud DB"""
import sqlite3, sys, os

# Add libsql path
sys.path.insert(0, os.path.expanduser("~/.local/lib/python3.12/site-packages"))

DB_URL = "libsql://exam-prep-db-pandit.aws-ap-south-1.turso.io"
AUTH = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODM4Mzc5MTUsImlkIjoiMDE5ZjU1MDYtMDQwMS03ZDU3LWI2NWYtNTRkMWY5MzkwMWJmIiwia2lkIjoiNVdJUENhcnVGMm5KeGJNUVVRbi12V0xXME9HSWg4alhvOUhQTXFUMEhSWSIsInJpZCI6ImQwZjE1Njk5LTJjYjItNDc2OS1iZDk0LTViMGI4OWE2OTRiMyJ9.s2DGLCWaNx5VE5xGAfknBcWehoTtYk31idFLLe0EsLmQa4BvwSdkrHn5YWPnLjaOKZobzuhR61CB7LeGJ81tBw"
LOCAL = "/home/pandit/code/personal/exam-prep-platform/data/exam_prep.db"

print("Importing libsql...")
try:
    import libsql_experimental as libsql
    print("libsql imported")
except:
    import libsql_client as libsql
    print("libsql_client imported")

# Connect local
src = sqlite3.connect(LOCAL)
tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

print(f"\nLocal DB: {len(tables)} tables")
for t in tables:
    c = src.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    print(f"  {t}: {c} rows")

# Connect Turso
print(f"\nConnecting to Turso...")
dst = libsql.connect(database=DB_URL, auth_token=AUTH)

# Create tables
schema = src.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name").fetchall()
created = 0
for (sql,) in schema:
    if not sql: continue
    try:
        dst.execute(sql)
        created += 1
    except Exception as e:
        if "already exists" not in str(e).lower():
            print(f"  WARN: {str(e)[:80]}")

print(f"Tables created: {created}")

# Copy data
migrated = 0
for table in tables:
    if table == 'sqlite_sequence': continue
    
    # Get existing count in destination
    existing = dst.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    if existing > 0:
        print(f"  {table}: already has {existing} rows — skipping")
        continue
    
    rows = src.execute(f"SELECT * FROM [{table}]").fetchall()
    if not rows: continue
    
    cols = [c[1] for c in src.execute(f"PRAGMA table_info([{table}])").fetchall()]
    placeholders = ','.join(['?'] * len(cols))
    cols_str = ','.join(f'[{c}]' for c in cols)
    
    try:
        dst.executemany(f"INSERT INTO [{table}] ({cols_str}) VALUES ({placeholders})", rows)
        migrated += 1
        print(f"  {table}: {len(rows)} rows migrated ✓")
    except Exception as e:
        print(f"  {table}: ERROR — {e}")

src.close()
dst.close()

print(f"\n{'='*50}")
print(f"Migration complete: {migrated} of {len([t for t in tables if t!='sqlite_sequence'])} tables")
print(f"Turso DB: {DB_URL}")
