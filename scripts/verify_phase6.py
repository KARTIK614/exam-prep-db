#!/usr/bin/env python3
"""Verify Phase 6 imports and route count. Intended to be run manually
from the repo root:

    python3 scripts/verify_phase6.py

Prints:
    - import status for app + content_metadata helpers
    - total Flask route count
    - listing of the new /admin/* routes registered in this phase
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def main():
    # Force local sqlite; do NOT hit Turso for a smoke import.
    os.environ.pop("TURSO_DB_URL", None)
    os.environ.pop("TURSO_AUTH_TOKEN", None)
    os.environ.setdefault("FLASK_SECRET_KEY", "verify-phase6-only")
    os.environ.setdefault("JWT_SECRET", "verify-phase6-only")

    # Import checks
    print("importing app…")
    import app as app_module
    print("  OK — app module loaded")

    print("importing content_metadata helpers…")
    from content_metadata import (
        compute_trigrams,
        keep_better_of,
        extract_reviewer_note,
        SYNTHESIS_PROMPT,
    )
    print(f"  OK — compute_trigrams('abcdef') -> {len(compute_trigrams('abcdef'))} grams")
    print(f"  OK — SYNTHESIS_PROMPT length = {len(SYNTHESIS_PROMPT)}")

    # Route count + list of new admin routes.
    app_obj = app_module.app
    all_rules = list(app_obj.url_map.iter_rules())
    print(f"\ntotal Flask routes: {len(all_rules)}")

    phase6_endpoints = {
        "admin.review_queue", "admin.review_action",
        "admin.duplicates_view", "admin.duplicate_disable",
        "admin.synthesize_view", "admin.synthesize_preview",
        "admin.synthesize_preview_view", "admin.synthesize_commit",
    }
    print("\nphase-6 admin routes:")
    for r in all_rules:
        if r.endpoint in phase6_endpoints:
            print(f"  {r.rule:<50}  → {r.endpoint}  ({','.join(sorted(r.methods - {'HEAD','OPTIONS'}))})")

    missing = phase6_endpoints - {r.endpoint for r in all_rules}
    if missing:
        print(f"\nMISSING endpoints: {missing}")
        return 1
    print("\nAll phase-6 endpoints registered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
