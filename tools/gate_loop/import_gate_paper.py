#!/usr/bin/env python3
"""Import an official GATE paper (question PDF + answer-key PDF) as a full paper.

Each question is cropped from the PDF as an image, so maths and diagrams
appear exactly as printed. The answer key supplies type (MCQ/MSQ/NAT),
section, key and marks. Questions land in `questions` with paper_code +
q_number, so `POST /tests {paper_code}` serves the whole paper in order.

Images go to frontend/public/gate/<paper_code>/qNN.webp (served by Vercel).
They never contain answers; keys stay in the DB and are only returned
after a test is finished.

Usage (DB target comes from TURSO_DB_URL / TURSO_AUTH_TOKEN, like the
migration scripts):
  import_gate_paper.py --qp GATE2024_CS_S1_QP.pdf --key GATE2024_CS_S1_Key.pdf \
      --code GATE2024_CS_S1 --exam "GATE CS" --year 2024 \
      --source "GATE 2024 CS Set 1 (official, IISc)" [--images-only] [--dry-run]
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageChops

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DPI = 160
SCALE = DPI / 72.0

# ---------------------------------------------------------------- answer key

KEY_ROW = re.compile(
    r"^\s*(\d{1,3})\s+\d+\s+(MCQ|MSQ|NAT)\s+([A-Z]{2}(?:-\d)?)\s+(.+?)\s+(\d(?:\.\d+)?)\s*$"
)


def parse_key(pdf):
    txt = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout
    rows = {}
    for line in txt.splitlines():
        m = KEY_ROW.match(line)
        if not m:
            continue
        qn, qtype, section, key, marks = int(m[1]), m[2], m[3], m[4].strip(), float(m[5])
        rows[qn] = {"q": qn, "qtype": qtype, "section": section.split("-")[0],
                    "key": normalize_key(qtype, key), "marks": marks}
    return rows


def normalize_key(qtype, key):
    k = key.strip()
    if k.upper() in ("MTA", "MARKS TO ALL"):
        return "MTA"
    if qtype == "NAT":
        m = re.match(r"^(-?[\d.]+)\s*(?:to|:)\s*(-?[\d.]+)$", k)
        if m:
            return f"{m[1]}:{m[2]}"
        float(k)  # single value; raises if garbage
        return f"{k}:{k}"
    letters = sorted(set(re.findall(r"[A-D]", k.upper())))
    if not letters:
        raise ValueError(f"unparseable key {key!r}")
    # MCQ keys like "A;B" mean either is accepted; MSQ keys are the exact set.
    return ";".join(letters)


# ---------------------------------------------------------------- layout

def parse_layout(pdf):
    out = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout
    pages = []
    for pm in re.finditer(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', out, re.S):
        w, h, body = float(pm[1]), float(pm[2]), pm[3]
        lines = []
        for lm in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', body, re.S):
            words = [html.unescape(x) for x in re.findall(r"<word [^>]*>(.*?)</word>", lm[5], re.S)]
            lines.append({"x0": float(lm[1]), "y0": float(lm[2]), "x1": float(lm[3]), "y1": float(lm[4]),
                          "text": " ".join(words), "words": words})
        lines.sort(key=lambda l: (l["y0"], l["x0"]))
        pages.append({"w": w, "h": h, "lines": lines})
    return pages


def marker_no(line):
    if len(line["words"]) == 1:
        m = re.fullmatch(r"Q\.(\d{1,3})", line["words"][0])
        if m:
            return int(m[1])
    return None


def is_boundary(line, page_h):
    t = line["text"]
    return (
        marker_no(line) is not None
        or "Carry" in t
        or re.search(r"\bPage \d+ of \d+\b", t) is not None
        or t.startswith("Organizing Institute")
        or "END OF THE QUESTION PAPER" in t.upper()
        or line["y0"] > page_h - 60
    )


def header_bottom(page):
    top = [l["y1"] for l in page["lines"] if l["y0"] < 62]
    return (max(top) if top else 50.0) + 4


def locate_questions(pages):
    """Return {q_number: [(page_index, y_top, y_bottom), ...]} in PDF points."""
    found = {}
    for pi, page in enumerate(pages):
        for li, line in enumerate(page["lines"]):
            qn = marker_no(line)
            if qn is None:
                continue
            segs = []
            y_top = line["y0"] - 4
            nxt = next((l for l in page["lines"][li + 1:] if is_boundary(l, page["h"]) and l["y0"] > line["y0"] + 2), None)
            end_is_marker_or_header = nxt is not None and (marker_no(nxt) is not None or "Carry" in nxt["text"])
            y_bot = (nxt["y0"] - 2) if nxt else page["h"] - 60
            segs.append((pi, y_top, y_bot))
            # Continuation onto following pages until a real question/header boundary.
            p2 = pi + 1
            while not end_is_marker_or_header and p2 < len(pages):
                pg = pages[p2]
                hb = header_bottom(pg)
                content = [l for l in pg["lines"] if l["y0"] >= hb - 2]
                if not content:
                    break
                # Text can sit a point above its "Q.n" marker, so judge the
                # whole first row, not just the first line.
                first_row = [l for l in content if l["y0"] < content[0]["y0"] + 6]
                if any(marker_no(l) is not None or "Carry" in l["text"] or "END OF" in l["text"].upper()
                       for l in first_row):
                    break
                nb = next((l for l in content if is_boundary(l, pg["h"])), None)
                segs.append((p2, hb, (nb["y0"] - 2) if nb else pg["h"] - 60))
                end_is_marker_or_header = nb is not None and (marker_no(nb) is not None or "Carry" in nb["text"])
                p2 += 1
            if qn in found:
                raise SystemExit(f"question marker Q.{qn} found twice — layout not understood")
            found[qn] = segs
    return found


# ---------------------------------------------------------------- images

def render_pages(pdf, tmp):
    subprocess.run(["pdftoppm", "-r", str(DPI), "-png", pdf, os.path.join(tmp, "p")], check=True)
    files = sorted(f for f in os.listdir(tmp) if f.startswith("p") and f.endswith(".png"))
    return [os.path.join(tmp, f) for f in files]


def unwatermark(img):
    """Whiten the light, neutral-grey "GATE 20xx" watermark. Text is black and
    diagrams are coloured or dark, so only near-neutral greys in 185–244 go."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mask = ((r >= 185) & (r <= 244) & (abs(r - g) < 10) & (abs(g - b) < 10) & (abs(r - b) < 10))
    a[mask] = 255
    return Image.fromarray(a.astype(np.uint8))


def trim(img, pad=14):
    bg = Image.new(img.mode, img.size, (255, 255, 255))
    bbox = ImageChops.difference(img, bg).convert("L").point(lambda v: 255 if v > 18 else 0).getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))


def squeeze(img, keep=26):
    """Collapse long blank vertical gaps (GATE spreads options down a page).

    A row is blank when it has no ink outside the table-border columns.
    Border columns (dark in over half the rows — the vertical rules of the
    DA papers' table layout) are ignored, so rows crossed only by borders
    still collapse, while the faint top edge of a text line never counts
    as blank. Horizontal rules are full rows of ink and are kept.
    """
    a = np.asarray(img.convert("L"))
    ink = a < 200
    border_cols = ink.mean(axis=0) > 0.5
    dark = ink[:, ~border_cols].sum(axis=1)
    keep_rows, run = [], 0
    for y, d in enumerate(dark):
        run = run + 1 if d == 0 else 0
        if run <= keep:
            keep_rows.append(y)
    if len(keep_rows) == a.shape[0]:
        return img
    return Image.fromarray(np.asarray(img.convert("RGB"))[keep_rows])


def crop_question(page_imgs, pages, segs):
    parts = []
    for pi, y0, y1 in segs:
        im = Image.open(page_imgs[pi]).convert("RGB")
        w = pages[pi]["w"]
        box = (int(40 * SCALE), int(max(0, y0) * SCALE), int((w - 40) * SCALE), int(y1 * SCALE))
        if box[3] - box[1] < 8:
            continue
        part = trim(unwatermark(im.crop(box)), pad=6)
        if part.height > 10:
            parts.append(part)
    if not parts:
        raise SystemExit("empty crop")
    width = max(p.width for p in parts)
    out = Image.new("RGB", (width, sum(p.height for p in parts)), (255, 255, 255))
    y = 0
    for p in parts:
        out.paste(p, (0, y))
        y += p.height
    return squeeze(trim(out))


def region_text(pdf, segs, pages):
    chunks = []
    for pi, y0, y1 in segs:
        w = pages[pi]["w"]
        r = subprocess.run(["pdftotext", "-f", str(pi + 1), "-l", str(pi + 1), "-x", "40", "-y", str(int(y0)),
                            "-W", str(int(w - 80)), "-H", str(int(y1 - y0)), "-layout", pdf, "-"],
                           capture_output=True, text=True, check=True).stdout
        chunks.append(r)
    t = re.sub(r"[ \t]+", " ", "\n".join(chunks))
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return t


# ---------------------------------------------------------------- db

def connect_db():
    if not os.environ.get("TURSO_DB_URL") or not os.environ.get("TURSO_AUTH_TOKEN"):
        sys.exit("ERROR: set TURSO_DB_URL and TURSO_AUTH_TOKEN (or use --images-only).")
    sys.path.insert(0, REPO)
    os.environ.setdefault("DB_PATH", os.path.join(REPO, "data", "exam_prep.db"))
    import turso_patch  # noqa: F401 — routes sqlite3 to Turso over HTTP
    import sqlite3
    return sqlite3.connect(os.environ["DB_PATH"])


SECTION_TOPIC = {
    "GA": ("GATE · General Aptitude", "General Aptitude"),
    "CS": ("GATE CS · Unsorted", "Computer Science"),
    "DA": ("GATE DA · Unsorted", "Data Science & AI"),
}


def topic_id(con, section):
    name, subject = SECTION_TOPIC.get(section, (f"GATE {section} · Unsorted", section))
    row = con.execute("SELECT id FROM topics WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    con.execute("INSERT INTO topics (name, subject, paper, weightage) VALUES (?, ?, 'GATE', 5)", (name, subject))
    con.commit()
    return con.execute("SELECT id FROM topics WHERE name = ?", (name,)).fetchone()[0]


def upsert(con, q):
    row = con.execute("SELECT id FROM questions WHERE paper_code = ? AND q_number = ?", (q["paper_code"], q["q_number"])).fetchone()
    cols = ["topic_id", "question_text", "correct_option", "difficulty", "source", "language", "qtype", "marks",
            "neg_marks", "image_url", "paper_code", "q_number", "paper_section", "pyq_exam", "pyq_year"]
    vals = [q[c] for c in cols]
    if row:
        con.execute(f"UPDATE questions SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?", vals + [row[0]])
        return "updated"
    con.execute(f"INSERT INTO questions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", vals)
    return "inserted"


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--qp", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--code", required=True, help="paper code, e.g. GATE2024_CS_S1")
    ap.add_argument("--exam", required=True, help='pyq_exam label, e.g. "GATE CS"')
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--images-dir", default=os.path.join(REPO, "frontend", "public", "gate"))
    ap.add_argument("--manifest", help="write the parsed paper (incl. keys) to this JSON path")
    ap.add_argument("--images-only", action="store_true", help="crop images, skip the DB")
    ap.add_argument("--dry-run", action="store_true", help="parse + crop, print a summary, write nothing to the DB")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", a.code) or "_" not in a.code:
        sys.exit("paper code must look like GATE2024_CS_S1")

    key = parse_key(a.key)
    pages = parse_layout(a.qp)
    located = locate_questions(pages)
    missing = sorted(set(key) - set(located))
    extra = sorted(set(located) - set(key))
    if missing or extra:
        sys.exit(f"key/paper mismatch — in key but not found: {missing}; found but not in key: {extra}")
    print(f"{a.code}: {len(key)} questions, {sum(r['marks'] for r in key.values()):g} marks, "
          f"types {dict((t, sum(1 for r in key.values() if r['qtype'] == t)) for t in ('MCQ', 'MSQ', 'NAT'))}")

    out_dir = os.path.join(a.images_dir, a.code)
    os.makedirs(out_dir, exist_ok=True)
    questions = []
    with tempfile.TemporaryDirectory() as tmp:
        page_imgs = render_pages(a.qp, tmp)
        for qn in sorted(key):
            k, segs = key[qn], located[qn]
            img = crop_question(page_imgs, pages, segs)
            fname = f"q{qn:02d}.webp"
            img.save(os.path.join(out_dir, fname), "WEBP", quality=82, method=6)
            questions.append({
                "q_number": qn, "paper_code": a.code, "paper_section": k["section"], "qtype": k["qtype"],
                "correct_option": k["key"], "marks": k["marks"],
                "neg_marks": round(k["marks"] / 3, 4) if k["qtype"] == "MCQ" else 0.0,
                "image_url": f"/gate/{a.code}/{fname}",
                "question_text": f"[{a.source} · Q.{qn}]\n" + region_text(a.qp, segs, pages),
                "source": a.source, "language": "en", "difficulty": "medium",
                "pyq_exam": a.exam, "pyq_year": a.year, "pages": [s[0] + 1 for s in segs],
                "size": list(img.size),
            })
    multi = [q["q_number"] for q in questions if len(q["pages"]) > 1]
    print(f"cropped {len(questions)} images → {out_dir}" + (f" (multi-page: {multi})" if multi else ""))
    if a.manifest:
        with open(a.manifest, "w") as f:
            json.dump(questions, f, indent=1, ensure_ascii=False)
    if a.images_only or a.dry_run:
        return

    con = connect_db()
    tids = {}
    counts = {"inserted": 0, "updated": 0}
    for q in questions:
        sec = q["paper_section"]
        if sec not in tids:
            tids[sec] = topic_id(con, sec)
        q["topic_id"] = tids[sec]
        counts[upsert(con, q)] += 1
    con.commit()
    print(f"db: {counts['inserted']} inserted, {counts['updated']} updated")


if __name__ == "__main__":
    main()
