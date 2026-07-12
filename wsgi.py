#!/usr/bin/env python3
"""Render entrypoint — loads Turso patch before Flask app"""
import turso_patch   # Monkey-patches sqlite3 → Turso
from app import app   # Flask app with DB routing
