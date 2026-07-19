"""Shared parser for question metadata recovery (Plan D §5).

Self-contained module — no Flask, no app imports. Consumed by
`scripts/backfill_question_metadata.py` and by `bp_admin.upload_import`.

Exports:
    SUBTOPIC_MAP         — dict[str, str|None] mapping raw JSON `section`
                           values to normalized sub_topic strings. Values
                           collapse close variants (e.g. `DBMS` and
                           `DBMS-PYQ` both → `"DBMS fundamentals"`).
    parse_pyq_source(s)  — (exam, year) tuple from a free-text `source`.
    is_pyq_section(s)    — True if section starts with `PYQ` or ends with
                           `-PYQ`.
    extract_reviewer_note(explanation)
                         — (stripped, note) from a `[Reviewer note: ...]`
                           blob at end of explanation. Anchored regex.
                           Returns (explanation, None) when no match.

All functions are safe to run against arbitrary strings including None.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple, Iterable, Set


# ─── SUBTOPIC_MAP ─────────────────────────────────────────────────────
#
# Curated section→sub_topic mapping. Collapses `X` and `X-PYQ` and
# `PYQ - X` all into the same sub_topic. Bare `PYQ` maps to None — it
# tells us the row is a PYQ (already captured via is_pyq_section /
# parse_pyq_source) but carries no sub-topic information.
#
# 70 distinct section strings observed in data/extracted_questions/*.json;
# a handful of one-off sections (`Java`, `Multimedia`, `AI`, `C`) are
# passed through as-is by falling back to `_normalize_section`.

SUBTOPIC_MAP: dict[str, Optional[str]] = {
    # Bare PYQ tags — no sub-topic content
    "": None,
    "PYQ": None,

    # Data Structures family
    "Array":                    "Array",
    "PYQ - Array":              "Array",
    "Linked List":              "Linked List",
    "PYQ - Linked List":        "Linked List",
    "Stack":                    "Stack",
    "PYQ - Stack":              "Stack",
    "Queue":                    "Queue",
    "PYQ - Queue":              "Queue",
    "Tree":                     "Tree",
    "PYQ - Tree":               "Tree",
    "Graph":                    "Graph",
    "PYQ - Graph":              "Graph",
    "ADT":                      "ADT",
    "PYQ - ADT":                "ADT",
    "Symbol Table / Hashing":   "Symbol Table / Hashing",
    "PYQ - Symbol Table":       "Symbol Table / Hashing",
    "DSA":                      "Data Structures general",
    "DSA/Sorting":              "Sorting",

    # DBMS family
    "DBMS":                     "DBMS fundamentals",
    "DBMS-PYQ":                 "DBMS fundamentals",
    "DBMS/SQL":                 "DBMS/SQL",
    "DBMS/Logic":               "DBMS fundamentals",

    # OS family
    "OS":                       "Operating System",
    "OS-PYQ":                   "Operating System",
    "OS/Windows":               "Operating System",
    "Ch5 - Scheduling/Deadlock": "Scheduling / Deadlock",
    "Ch6 - File System/Disk":   "File System / Disk",

    # SAD family
    "SAD":                      "System Analysis & Design",
    "SAD-PYQ":                  "System Analysis & Design",
    "System Analysis":          "System Analysis & Design",
    "Software Engineering":     "Software Engineering",

    # Networks family
    "Networks":                 "Networks",
    "Ch1 - Transmission Media": "Transmission Media",
    "Ch2 - Multiplexing/Modulation/Switching": "Multiplexing / Modulation / Switching",
    "Ch3 - Topology":           "Topology",
    "Ch4 - Network Devices":    "Network Devices",
    "Ch5 - OSI Model":          "OSI Model",
    "PYQ - Ch5":                "OSI Model",
    "Networks/Web":             "Networks",
    "Networks/Security":        "Networks",

    # Security family
    "Security":                 "Network Security",
    "Security-PYQ":             "Network Security",
    "Firewall":                 "Firewall",
    "Firewall-PYQ":             "Firewall",
    "Hacking":                  "Hacking / Attacks",
    "Hacking-PYQ":              "Hacking / Attacks",
    "Backup":                   "Backup / Recovery",

    # Computer Organisation
    "CO":                       "Computer Organisation",
    "CO-PYQ":                   "Computer Organisation",
    "Digital Logic":            "Digital Logic",
    "Hardware":                 "Hardware",
    "Memory":                   "Memory",

    # Web / Multimedia / Emerging
    "Web":                      "Web Technologies",
    "Web/XML":                  "Web Technologies",
    "Multimedia":               "Multimedia",
    "AI":                       "AI & ML",

    # Fundamentals / misc
    "Fundamentals":             "Computer Fundamentals",
    "Applications":             "Applications",
    "Number Systems":           "Number Systems",
    "MS Office":                "MS Office",
    "Pedagogy":                 "Pedagogy",
    "Research Methods":         "Research Methods",

    # Languages
    "C":                        "Programming C",
    "C/C++":                    "Programming C/C++",
    "C/Algorithms":             "Algorithms",
    "Java":                     "Java",
    "Java/OOP":                 "Java & OOP",
    "Python":                   "Python",
}


def _normalize_section(section: str) -> Optional[str]:
    """Fallback for sections not in SUBTOPIC_MAP — return as-is if
    non-trivial, else None."""
    if not section:
        return None
    s = section.strip()
    if not s or s == "PYQ":
        return None
    return s


def is_pyq_section(section: Optional[str]) -> bool:
    """True if this section value marks a past-year question.

    Examples:
        >>> is_pyq_section("PYQ")
        True
        >>> is_pyq_section("DBMS-PYQ")
        True
        >>> is_pyq_section("PYQ - Tree")
        True
        >>> is_pyq_section("DBMS")
        False
        >>> is_pyq_section("")
        False
        >>> is_pyq_section(None)
        False
    """
    if not section:
        return False
    s = section.strip()
    if not s:
        return False
    # Starts with "PYQ" (as its own word) OR ends with "-PYQ"
    if s == "PYQ":
        return True
    if s.startswith("PYQ ") or s.startswith("PYQ-"):
        return True
    if s.endswith("-PYQ"):
        return True
    return False


# ─── parse_pyq_source ─────────────────────────────────────────────────
#
# Regex-driven parser. Given a free-text `source` string like:
#     "PYQ RPSC Programmer"
#     "PYQ BCI 18.06.2022"
#     "BCI 18 June 2022 Q91"
#     "Raj. Informatics Assistant Exam 21.01.2024"
#     "GATE CS 2011 / KVS PGT 2017"
# returns a normalized (exam_name, year_int_or_None) tuple.
#
# Priorities:
#     1. First 4-digit year in range 1980-2099 → pyq_year
#     2. Everything else, stripped of common noise → pyq_exam
#     3. Exam name is normalized via _EXAM_ALIASES

# Longer patterns first so partial matches don't win.
_EXAM_ALIASES = [
    # (regex pattern, canonical name)
    (r"\bRaj(?:\.|asthan)?\s+Basic\s+(?:Comp(?:uter)?\s+)?Instructor\b", "BCI"),
    (r"\bBasic\s+(?:Comp(?:uter)?\s+)?Instructor\b",                     "BCI"),
    (r"\bBCI\b",                                                          "BCI"),
    (r"\bRaj(?:\.|asthan)?\s+Sen(?:ior)?\s+(?:Comp(?:uter)?\s+)?Instructor\b", "Raj Senior Computer Instructor"),
    (r"\bSen(?:ior)?\s+(?:Comp(?:uter)?\s+)?Instructor\b",                "Raj Senior Computer Instructor"),
    (r"\bSr\.?\s+Comp(?:uter)?\s+Instructor\b",                           "Raj Senior Computer Instructor"),
    (r"\bRaj(?:\.|asthan)?\s+Inform?atics\s+Assistant(?:\s+\(IA\))?\b",   "Raj IA"),
    (r"\bInform?atics\s+Assistant(?:\s+\(IA\))?\b",                       "Raj IA"),
    (r"\bRaj(?:\.|asthan)?\s+IA\b",                                       "Raj IA"),
    (r"\bRaj\s+IA\b",                                                     "Raj IA"),
    (r"\bIA\b",                                                            "Raj IA"),  # last-resort
    (r"\bRPSC\s+Programmer\b",                                            "RPSC Programmer"),
    (r"\bRaj(?:\.|asthan)?\s+Computor\b",                                 "Raj Computor"),
    (r"\bCET\s+Gr\.?\s+Level\b",                                          "CET Gr Level"),
    (r"\bCET\s+10\+2(?:\s+Level)?\b",                                     "CET 10+2"),
    (r"\bRaj(?:\.|asthan)?\s+CET(?:\s+Grad\.?)?\b",                       "CET Gr Level"),
    (r"\bRaj(?:\.|asthan)?\s+Patwar(?:i)?(?:\s+Mains?)?(?:\s+\(S-1\))?\b", "Raj Patwar"),
    (r"\bPatwar(?:i)?\s+Direct\s+Recruitment(?:\s+Exam)?\b",              "Raj Patwar"),
    (r"\bPatwar(?:i)?\s+Mains?\b",                                        "Raj Patwar"),
    (r"\bPatwar(?:i)?\s+Pre\b",                                           "Raj Patwar"),
    (r"\bPatwar(?:i)?\b",                                                 "Raj Patwar"),
    (r"\bRaj(?:\.|asthan)?\s+Village\s+Development\s+Officer\b",          "Raj VDO"),
    (r"\bVillage\s+Development\s+Officer\b",                              "Raj VDO"),
    (r"\bVDO\b",                                                           "Raj VDO"),
    (r"\bRaj(?:\.|asthan)?\s+Jr\.?\s+Accountant\b",                       "Raj Jr Accountant"),
    (r"\bJunior\s+Accountant(?:\s+Re-?\s?Exam)?\b",                       "Raj Jr Accountant"),
    (r"\bJRA\s+Accountant(?:\s+Re\s+Exam)?\b",                            "Raj Jr Accountant"),
    (r"\bJr\.?\s+Acct\.?,?\s+TRA\b",                                      "Raj Jr Accountant"),
    (r"\bJRA\b",                                                           "Raj Jr Accountant"),
    (r"\bRaj(?:\.|asthan)?\s+Librarian(?:\s+Gr(?:ade|\.)?[-\s]*(?:2|3|II|III))?\b", "Raj Librarian"),
    (r"\bLibrarian\s+Gr(?:ade|\.)?[-\s]*(?:2|3|II|III)\b",                "Raj Librarian"),
    (r"\bLibrarian\b",                                                     "Raj Librarian"),
    (r"\bHostel\s+Superintendent(?:\s+Exam)?\b",                          "Raj Hostel Superintendent"),
    (r"\bGram\s+Sevak(?:\s+and\s+Hostel\s+Superintendent)?\b",            "Gram Sevak / Hostel Superintendent"),
    (r"\bJr\.?\s+Inst(?:ructor)?\.?\s+COPA\b",                            "Jr Instructor COPA"),
    (r"\bJunior\s+Instructor[- ]\s?COPA\b",                               "Jr Instructor COPA"),
    (r"\bJunior\s+Instructor\s*\(COPA\)",                                 "Jr Instructor COPA"),
    (r"\bJr\.?\s+Instructor\s*\(COPA\)",                                  "Jr Instructor COPA"),
    (r"\(COPA\)",                                                          "Jr Instructor COPA"),
    (r"\bJr\.?\s+Scientific\s+Assistant\b",                               "Jr Scientific Assistant"),
    (r"\bDSSSB[-\s]*PGT(?:\s*CS)?\b",                                     "DSSSB PGT"),
    (r"\bDSSB[-\s]*PGT(?:\s*CS)?\b",                                      "DSSSB PGT"),
    (r"\bDSSSB[-\s]*TGT(?:\s*CS)?\b",                                     "DSSSB TGT"),
    (r"\bDSSB[-\s]*TGT(?:\s*CS)?\b",                                      "DSSSB TGT"),
    (r"\bDSSB[-\s]*TCT\b",                                                "DSSSB TGT"),
    (r"\bDSSSB\b",                                                        "DSSSB PGT"),
    (r"\bDSSB\b",                                                         "DSSSB PGT"),
    (r"\bGATE\s+CS\b",                                                    "GATE CS"),
    (r"\bGATE\b",                                                          "GATE CS"),
    (r"\bISRO\s+Scientist(?:\s*SC)?\b",                                   "ISRO CS"),
    (r"\bISRO\s+Sci/Engineer\b",                                          "ISRO CS"),
    (r"\bISRO\s+Engineer\b",                                              "ISRO CS"),
    (r"\bISRO\s+CS\b",                                                    "ISRO CS"),
    (r"\bISRO\b",                                                          "ISRO CS"),
    (r"\bUGC\s+NET(?:\s+CS)?\b",                                          "UGC NET"),
    (r"\bNTA\s+UGCNET\b",                                                 "UGC NET"),
    (r"\bVGL\s+NET\s+CS\b",                                               "UGC NET"),
    (r"\bKVS\s+PGT(?:\s*CS)?\b",                                          "KVS PGT"),
    (r"\bKVS\b",                                                           "KVS PGT"),
    (r"\bNVS\s+PGT(?:\s*IT)?\b",                                          "NVS PGT"),
    (r"\bHTET\s+PGT(?:\s*CS)?\b",                                         "HTET PGT"),
    (r"\bNIELIT\s+Scientist(?:\s*'?B'?)?\b",                              "NIELIT Scientist B"),
    (r"\bNIELIT\s+'?[AO]'?\s+Level\b",                                    "NIELIT Level"),
    (r"\bNIELIT\b",                                                        "NIELIT"),
    (r"\bNIC\s+Scientist\s*B\b",                                          "NIC Scientist B"),
    (r"\bSSC\s+Scientific\s+Assistant\b",                                 "SSC Scientific Assistant"),
    (r"\bSSC\s+CGL(?:\s+Tier[-\s]?1)?\b",                                 "SSC CGL"),
    (r"\bSSC\s+JE(?:\s*CS)?\b",                                           "SSC JE"),
    (r"\bSSC\s+IMD\b",                                                    "SSC IMD"),
    (r"\bSSC\b",                                                           "SSC"),
    (r"\bIBPS\s+SO(?:\s*\(IT Officer\)|\s*IT\s+Officer|\s*ITO?\s+Officer|\s*IT)?\b", "IBPS SO IT"),
    (r"\bIBPS\s+RRB\s+Officer\b",                                         "IBPS RRB Officer"),
    (r"\bIBPS\s+IT\s+Officer\b",                                          "IBPS SO IT"),
    (r"\bRRB\s+Officer\s+Scale-?1\b",                                     "RRB Officer"),
    (r"\bRRB\s+NTPC\b",                                                   "RRB NTPC"),
    (r"\bRRBJE\s+IT\b",                                                   "RRB JE IT"),
    (r"\bSBI\s+PO\b",                                                     "SBI PO"),
    (r"\bSBI\s+SO\b",                                                     "SBI SO"),
    (r"\bBSNL\s+JE\b",                                                    "BSNL JE"),
    (r"\bUPP\s+Computer\s+Operator\b",                                    "UPP Computer Operator"),
    (r"\bUPPCL\s+RO/?ARO\b",                                              "UPPCL RO/ARO"),
    (r"\bUPPCL\s+ARO\b",                                                  "UPPCL RO/ARO"),
    (r"\bUPPCS\s*\(Pre\)\b",                                              "UPPCS Pre"),
    (r"\bRaj(?:\.|asthan)?\s+Police\b",                                   "Raj Police"),
    (r"\bUP\s+Police\b",                                                  "UP Police"),
    (r"\bMP\s+Patwari\b",                                                 "MP Patwari"),
    (r"\bMPPSC\b",                                                        "MPPSC"),
    (r"\bBihar\s+Comp(?:uter)?\s+Teacher\b",                              "Bihar Computer Teacher"),
    (r"\bUttarakhand\s+PCS\b",                                            "Uttarakhand PCS"),
    (r"\bCUET\s+PG\b",                                                    "CUET PG"),
    (r"\bNIM\s*CET\b",                                                    "NIMCET"),
    (r"\bNIMCET\b",                                                       "NIMCET"),
    (r"\bTax\s+Assistant\b",                                              "Tax Assistant"),
    (r"\bLDC(?:\s+Exam)?\b",                                              "Raj LDC"),
    (r"\bRSMSSB\s+LDC\b",                                                 "Raj LDC"),
    (r"\bWomen\s+Supervisor\b",                                           "Women Supervisor"),
    (r"\bLivestock\s+Assistant\b",                                        "Raj Livestock Assistant"),
    (r"\bInvestigator\s+Exam\b",                                          "Investigator Exam"),
    (r"\bCompiler\s+Exam\b",                                              "Compiler Exam"),
    (r"\bHigh\s+Court\s+Exam\b",                                          "Raj High Court"),
    (r"\bHM\s+Sanskrit\s+Ed\.?\b",                                        "Raj HM Sanskrit"),
    (r"\bH\.M\.?\s+Sanskrit\s+Ed\.?\b",                                   "Raj HM Sanskrit"),
    (r"\bHeadmaster\s+Exam\b",                                            "Raj Headmaster"),
    (r"\bHead\s+Master\s+Exam\.?\b",                                      "Raj Headmaster"),
    (r"\bH\.M\.?\s+Exam\b",                                               "Raj Headmaster"),
    (r"\bRaj\s+Computor\b",                                               "Raj Computor"),
    (r"\bSystem\s+Assistant\b",                                           "System Assistant"),
    (r"\bHealth\s+Dept\b",                                                "Health Dept"),
    (r"\bOperating\s+System\s+Concept\b",                                 "OS Concept"),
]

_COMPILED_ALIASES = [(re.compile(p, re.IGNORECASE), name) for p, name in _EXAM_ALIASES]

_YEAR_RE = re.compile(r"\b((?:19[89]\d|20\d{2}))\b")


def parse_pyq_source(src: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """Parse a `source` free-text string into (exam_name, year).

    Returns (None, None) for blank input or pdf-tags. Multi-source
    strings (e.g. `"GATE CS 2011 / KVS PGT 2017"`) resolve to the FIRST
    exam alias matched (order in _EXAM_ALIASES).

    Examples:
        >>> parse_pyq_source("PYQ RPSC Programmer")
        ('RPSC Programmer', None)
        >>> parse_pyq_source("PYQ BCI 18.06.2022")
        ('BCI', 2022)
        >>> parse_pyq_source("BCI 18 June 2022 Q91")
        ('BCI', 2022)
        >>> parse_pyq_source("Raj. Informatics Assistant Exam 21.01.2024")
        ('Raj IA', 2024)
        >>> parse_pyq_source("GATE CS 2011 / KVS PGT 2017")
        ('GATE CS', 2011)
        >>> parse_pyq_source("DSSSB-PGT-2021")
        ('DSSSB PGT', 2021)
        >>> parse_pyq_source("CET Gr. Level, 27.9.24 (2nd Shift)")
        ('CET Gr Level', 2024)
        >>> parse_pyq_source("")
        (None, None)
        >>> parse_pyq_source(None)
        (None, None)
        >>> parse_pyq_source("pdf:U4 Ch 2 Mcqs.pdf")
        (None, None)
    """
    if not src:
        return (None, None)
    s = src.strip()
    if not s or s.startswith("pdf:") or s.startswith("pdf_upload:"):
        return (None, None)

    # Strip leading "PYQ" prefix (already know it's a PYQ once we're
    # in the parser).
    working = re.sub(r"^\s*PYQ\s+", "", s, flags=re.IGNORECASE)
    # Take FIRST alternative when source lists multiple exams via `/`.
    working = working.split(" / ")[0].split("/")[0] if " / " in working else working
    # Prefer the / split only if the LHS contains an alias; else keep whole.
    # We handle multi-source by scanning aliases against the WHOLE string;
    # the first alias in _EXAM_ALIASES that matches wins.

    exam: Optional[str] = None
    for rx, name in _COMPILED_ALIASES:
        if rx.search(s):
            exam = name
            break

    year: Optional[int] = None
    # Prefer year attached to the resolved exam-alias, but for simplicity
    # take the FIRST 4-digit year in the whole source string.
    m = _YEAR_RE.search(s)
    if m:
        y = int(m.group(1))
        if 1980 <= y <= 2099:
            year = y
    else:
        # Two-digit year in DD.MM.YY / DD-MM-YY  → assume 20YY when YY<50.
        m2 = re.search(r"\b\d{1,2}[.\-/]\d{1,2}[.\-/](\d{2})\b", s)
        if m2:
            yy = int(m2.group(1))
            year = 2000 + yy if yy < 50 else 1900 + yy

    return (exam, year)


# ─── extract_reviewer_note ────────────────────────────────────────────
#
# The push script (push_extracted_to_turso.py:88-89) appends the
# reviewer note into `explanation` as:
#     f"{explanation}\n\n[Reviewer note: {q['notes']}]"
# We recover the note (and produce a clean explanation) via an anchored
# end-of-string regex. IMPORTANT: only strips if the regex matches — the
# safety property that makes it OK to run against the whole table.

_NOTE_RE = re.compile(
    r"\s*\[Reviewer note:\s*(.+?)\]\s*$",
    re.DOTALL,
)


def extract_reviewer_note(explanation: Optional[str]) -> Tuple[str, Optional[str]]:
    """Split a `[Reviewer note: ...]` blob off the end of an explanation.

    Returns (stripped_explanation, note_or_None). Never mutates unless
    the regex matches — the caller can UPDATE `review_notes` and
    `explanation` blindly without worrying about overreach.

    Examples:
        >>> extract_reviewer_note("Ans is C.\\n\\n[Reviewer note: ambiguous]")
        ('Ans is C.', 'ambiguous')
        >>> extract_reviewer_note("Plain explanation.")
        ('Plain explanation.', None)
        >>> extract_reviewer_note("")
        ('', None)
        >>> extract_reviewer_note(None)
        ('', None)
        >>> extract_reviewer_note("A. [Reviewer note: x]\\n")
        ('A.', 'x')
    """
    if not explanation:
        return ("", None)
    m = _NOTE_RE.search(explanation)
    if not m:
        return (explanation, None)
    note = m.group(1).strip()
    stripped = explanation[: m.start()].rstrip()
    return (stripped, note)


# ─── convenience helper for callers ───────────────────────────────────

def metadata_from_json_question(q: dict) -> dict:
    """One-shot: derive (confidence, section, sub_topic, pyq_exam,
    pyq_year, review_notes) fields from a raw question dict as read
    out of the extraction JSONs.

    Used by both the backfill script and the admin upload_import
    handler so behaviour cannot drift.

    Does NOT return `explanation` — that stays the caller's
    responsibility (backfill uses the DB row's already-concatenated
    explanation; upload_import concatenates fresh).
    """
    section = q.get("section") or None
    sub_topic: Optional[str]
    if section in SUBTOPIC_MAP:
        sub_topic = SUBTOPIC_MAP[section]
    else:
        sub_topic = _normalize_section(section) if section else None

    if is_pyq_section(section) or "PYQ" in (q.get("source") or ""):
        pyq_exam, pyq_year = parse_pyq_source(q.get("source"))
    else:
        # Not tagged PYQ by section, but source might still reveal an
        # exam name (e.g. "BCI 18 June 2022 Q91" without a section
        # PYQ tag — happens in last_bci_paper_2022.json).
        src = q.get("source") or ""
        pyq_exam, pyq_year = parse_pyq_source(src) if src and not src.startswith("pdf:") else (None, None)

    return {
        "confidence": q.get("confidence") or "high",
        "section":    section,
        "sub_topic":  sub_topic,
        "pyq_exam":   pyq_exam,
        "pyq_year":   pyq_year,
        "review_notes": q.get("notes") or None,
    }


# ─── Plan D §3 — trigram normalization + Jaccard helpers ─────────────
#
# Char-trigram computation reused by:
#   - scripts/build_trigram_index.py (batch precompute)
#   - bp_admin.upload_import (incremental for new rows)
#
# Normalization rules must exactly match between the batch and the
# incremental path, else Jaccard collapses. Any change here needs a
# `--rebuild` run of build_trigram_index.

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalize_for_trigrams(text: Optional[str]) -> str:
    """Lowercase, strip Hindi (after first \\n), strip punct, collapse ws.

    Examples:
        >>> _normalize_for_trigrams("Hello, World!\\nनमस्ते")
        'hello world'
        >>> _normalize_for_trigrams("  Multi   spaces.  ")
        'multi spaces'
        >>> _normalize_for_trigrams("")
        ''
        >>> _normalize_for_trigrams(None)
        ''
    """
    if not text:
        return ""
    t = text.split("\n", 1)[0]
    t = t.lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def compute_trigrams(text: Optional[str]) -> Set[str]:
    """Return the char-trigram set of the normalized text. Empty if too short.

    Examples:
        >>> sorted(compute_trigrams("abcd"))
        ['abc', 'bcd']
        >>> compute_trigrams("")
        set()
        >>> compute_trigrams(None)
        set()
    """
    norm = _normalize_for_trigrams(text)
    if len(norm) < 3:
        return set()
    return {norm[i : i + 3] for i in range(len(norm) - 2)}


def keep_better_of(row_a: dict, row_b: dict) -> Tuple[dict, dict]:
    """Return (winner, loser) between two question rows using the Plan D
    §3 heuristic:

        1. PYQ (pyq_exam non-null) beats non-PYQ
        2. confidence='high' beats 'medium'/'low'/'deferred'
        3. Longer non-null explanation wins
        4. Newer updated_at wins
        5. Fallback: lower id wins (older row is canonical)

    Rows must be dict-like with keys pyq_exam, confidence, explanation,
    updated_at, id. Missing keys default to safe values.
    """

    def score(r):
        return (
            1 if r.get("pyq_exam") else 0,
            1 if (r.get("confidence") or "").lower() == "high" else 0,
            len(r.get("explanation") or ""),
            (r.get("updated_at") or ""),
            -int(r.get("id") or 0),  # negate so smaller id = higher score
        )

    if score(row_a) >= score(row_b):
        return row_a, row_b
    return row_b, row_a


# ─── Plan D §4 — Claude synthesis prompt ─────────────────────────────
#
# Passed to ai_anthropic client from bp_admin.synthesize_generate. The
# {topic}, {sub_topics}, {existing_questions_json} placeholders are
# str-formatted at call time.

SYNTHESIS_PROMPT = """You are an expert exam-question writer for the Rajasthan Basic Computer Instructor (BCI) exam, Paper II.

Below are up to 10 existing high-quality MCQs on {topic}, drawn from previous exams. Study the style, difficulty distribution (~30% easy, 50% medium, 20% hard), bilingual formatting (English + Hindi separated by \\n, but Hindi is OPTIONAL), and level of explanation detail.

<existing_questions>
{existing_questions_json}
</existing_questions>

Generate exactly {n} NEW multiple-choice questions on {topic}. Focus on the sub-topics: {sub_topics}. Each question MUST:

- Be answerable from general CS knowledge at the syllabus level (never brand-new tech, specific vendors, or trivia).
- Have exactly 4 options (A, B, C, D), with exactly one clearly correct answer.
- Include a 1-3 sentence explanation of why the correct answer is right.
- Be an English question. Hindi is optional; if omitted, do not add \\n.
- Have "source": "synthetic-v1", "confidence": "medium".
- Add a "notes" field explaining any subtlety a reviewer should verify (empty string OK).

Return a JSON object with a single "questions" array. Each item must contain:
{{"question_text", "option_a", "option_b", "option_c", "option_d", "correct_option", "explanation", "difficulty", "confidence", "source", "notes"}}

Do NOT wrap the JSON in prose or code fences. Output valid JSON only.
"""


# ─── smoke tests ──────────────────────────────────────────────────────
#
# Run with:  python3 content_metadata.py
# Uses doctest + a small hand-crafted set covering the 20-ish source
# patterns most frequent in the extraction JSONs.

if __name__ == "__main__":
    import doctest

    # Doctests inside the function docstrings.
    fails, total = doctest.testmod(verbose=False).failed, doctest.testmod(verbose=False).attempted
    if fails:
        raise SystemExit(f"doctest failed: {fails}/{total}")

    # Extra spot-checks — patterns pulled from
    # data/extracted_questions/*.json sources.
    cases = [
        # (source, expected_exam, expected_year)
        ("PYQ RPSC Programmer",                          "RPSC Programmer", None),
        ("PYQ BCI 18.06.2022",                           "BCI",             2022),
        ("PYQ Raj IA 2013",                              "Raj IA",          2013),
        ("PYQ Patwar 24.10.2021",                        "Raj Patwar",      2021),
        ("PYQ Raj IA 2018",                              "Raj IA",          2018),
        ("PYQ RPSC Programmer 27.10.2024",               "RPSC Programmer", 2024),
        ("Raj. Basic Computer Instructor 18.06.2022",    "BCI",             2022),
        ("DSSSB-PGT-2021",                               "DSSSB PGT",       2021),
        ("Patwar Mains 2015 Dt. 6.1.2017",               "Raj Patwar",      2015),
        ("PYQ Sr Comp Instructor 19.06.2022",            "Raj Senior Computer Instructor", 2022),
        ("PYQ Raj IA 21.01.2024",                        "Raj IA",          2024),
        ("Informatics Assistant - 2018",                 "Raj IA",          2018),
        ("BCI 18 June 2022 Q91",                         "BCI",             2022),
        ("Basic Computer Instructor - 18.06.2022",       "BCI",             2022),
        ("CET Gr. Level, 27.9.24 (2nd Shift)",           "CET Gr Level",    2024),
        ("PYQ Raj CET 10+2 11.02.2023",                  "CET 10+2",        2023),
        ("GATE CS 2005",                                 "GATE CS",         2005),
        ("UGC NET June 2012",                            "UGC NET",         2012),
        ("ISRO CS 2013",                                 "ISRO CS",         2013),
        ("PYQ KVS PGT CS 2017",                          "KVS PGT",         2017),
        ("PYQ DSSB TGT",                                 "DSSSB TGT",       None),
        ("Raj. Village Development Officer - 28.12.2021", "Raj VDO",         2021),
        ("Rajasthan Librarian Grade III 2016",           "Raj Librarian",   2016),
        ("PYQ Hostel Superintendent Exam",               "Raj Hostel Superintendent", None),
        ("",                                              None,              None),
        (None,                                            None,              None),
        ("pdf:U4 Ch 2 Mcqs.pdf",                          None,              None),
    ]

    fails = 0
    for src, exp_exam, exp_year in cases:
        got_exam, got_year = parse_pyq_source(src)
        if got_exam != exp_exam or got_year != exp_year:
            fails += 1
            print(f"FAIL parse_pyq_source({src!r})")
            print(f"     got={got_exam!r},{got_year!r}  exp={exp_exam!r},{exp_year!r}")

    # is_pyq_section spot-checks
    section_cases = [
        ("PYQ", True), ("DBMS-PYQ", True), ("PYQ - Tree", True),
        ("DBMS", False), ("", False), (None, False),
        ("OS-PYQ", True), ("PYQ - Array", True), ("Array", False),
    ]
    for s, exp in section_cases:
        got = is_pyq_section(s)
        if got != exp:
            fails += 1
            print(f"FAIL is_pyq_section({s!r})  got={got}  exp={exp}")

    # extract_reviewer_note spot-checks
    note_cases = [
        (
            "Ans is C.\n\n[Reviewer note: options B and C are both defensible]",
            "Ans is C.",
            "options B and C are both defensible",
        ),
        ("No note here.", "No note here.", None),
        ("", "", None),
        (None, "", None),
        (
            "Multi-line\nans.\n\n[Reviewer note: line 1\nline 2]",
            "Multi-line\nans.",
            "line 1\nline 2",
        ),
    ]
    for exp_in, exp_out, exp_note in note_cases:
        got_out, got_note = extract_reviewer_note(exp_in)
        if got_out != exp_out or got_note != exp_note:
            fails += 1
            print(f"FAIL extract_reviewer_note({exp_in!r})")
            print(f"     got=({got_out!r}, {got_note!r})")
            print(f"     exp=({exp_out!r}, {exp_note!r})")

    if fails:
        raise SystemExit(f"{fails} spot-check failures")
    print("OK — all doctests + spot-checks passed.")
