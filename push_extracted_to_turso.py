#!/usr/bin/env python3
"""
One-shot: push all data/extracted_questions/*.json into Turso Cloud
via turso_patch (Hrana v2 HTTP pipeline).

Requires env vars TURSO_DB_URL and TURSO_AUTH_TOKEN.
Run:  python3 push_extracted_to_turso.py [--dry-run]
"""
import os
import sys
import json
import glob
from datetime import datetime

if not os.environ.get("TURSO_DB_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
    sys.exit("ERROR: set TURSO_DB_URL and TURSO_AUTH_TOKEN before running.")

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# Force turso_patch to monkey-patch sqlite3 when we open our db path
os.environ.setdefault("DB_PATH", os.path.join(BASE, "data", "exam_prep.db"))
import turso_patch  # noqa: F401  — monkey-patches sqlite3

import sqlite3

# File → topic_id mapping (from seed.py topic ids 25-42)
# 31=Data Structures, 32=Algorithms, 33=DBMS, 34=OS, 35=Networks,
# 36=Network Security, 38=SAD, 41=Computer Organization, 25=Fundamentals
FILE_TOPIC = {
    "U4_Ch2.json":            31,  # Arrays + Linked Lists
    "U4_Ch3_4_5.json":        31,  # Stack + Queue + Tree + Graph
    "U4_Ch6.json":            31,  # ADT + Hashing + Symbol Table
    "U5_Ch1.json":            25,  # Computer Generations / Fundamentals
    "U5_Ch2_Ch3.json":        41,  # Computer Org + OS  (bulk → CO; OS Qs stay here)
    "U5_Ch4.json":            41,  # Memory & Storage
    "U5_Ch5_Ch6.json":        34,  # OS Scheduling + File System
    "U6_Ch1_to_5.json":       35,  # Networks + Digital Logic + OSI
    "U6_Ch6.json":            35,  # Mobile Communication
    "U7_Complete.json":       36,  # Network Security
    "U8_Complete.json":       33,  # DBMS
    "U9_Complete.json":       38,  # System Analysis & Design
    "last_bci_paper_2022.json": 25, # PYQ — mixed CS → Fundamentals
}

# For files whose 'section' field disambiguates (e.g. U5_Ch2_Ch3 has 'CO' and 'OS')
# override on a per-question basis.
SECTION_OVERRIDE = {
    "U5_Ch2_Ch3.json": {
        "OS":     34, "OS-PYQ": 34,
        "CO":     41, "CO-PYQ": 41,
    },
}


def main(dry_run=False):
    db_path = os.environ["DB_PATH"]
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    existing = cur.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    print(f"Existing questions in Turso: {existing}")

    files = sorted(glob.glob(os.path.join(BASE, "data", "extracted_questions", "*.json")))
    print(f"Found {len(files)} JSON files to import")

    total_inserted = 0
    for path in files:
        fname = os.path.basename(path)
        default_tid = FILE_TOPIC.get(fname)
        overrides = SECTION_OVERRIDE.get(fname, {})
        if default_tid is None:
            print(f"  SKIP {fname} — no topic mapping")
            continue

        with open(path) as fh:
            data = json.load(fh)
        qs = data.get("questions", [])
        src_pdf = data.get("source_pdf", fname)

        f_inserted = 0
        for q in qs:
            section = q.get("section") or ""
            topic_id = overrides.get(section, default_tid)
            src = q.get("source") or f"pdf:{src_pdf}"
            explanation = q.get("explanation", "") or ""
            if q.get("notes"):
                explanation = f"{explanation}\n\n[Reviewer note: {q['notes']}]"

            if dry_run:
                f_inserted += 1
                continue

            res = cur.execute(
                "INSERT INTO questions (topic_id, question_text, option_a, option_b, "
                "option_c, option_d, correct_option, explanation, difficulty, source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    topic_id,
                    q.get("question_text", ""),
                    q.get("option_a", ""),
                    q.get("option_b", ""),
                    q.get("option_c", ""),
                    q.get("option_d", ""),
                    (q.get("correct_option") or "A").upper()[:1],
                    explanation,
                    q.get("difficulty", "medium"),
                    src,
                ),
            )
            if res.lastrowid is None:
                print(f"    !! insert failed silently for Q section={section}")
                continue
            f_inserted += 1

        if not dry_run:
            con.commit()
        print(f"  {fname:32s} → topic_id={default_tid}  inserted {f_inserted}")
        total_inserted += f_inserted

    final = cur.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    con.close()

    verb = "would insert" if dry_run else "inserted"
    print(f"\n{verb} {total_inserted} questions.")
    print(f"Final total in Turso: {final}  (delta: {final - existing})")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
