#!/usr/bin/env python3
"""Push GATE flashcards into Anki through AnkiConnect, then sync to AnkiWeb.

Cards live in the "GATE" deck with the "GATE Card" note type. Each card has a
stable UID, so pushing the same UID again updates the existing card instead of
adding a duplicate. That's how a repeated mistake rewrites its card.

Input: a JSON file holding a list of cards:
  {
    "uid": "cs24s1-q23-a",              # stable, unique
    "kind": "trap",                      # method | fact | contrast | trap | speed
    "prompt": "...", "answer": "...",   # required; HTML + MathJax \\( \\) allowed
    "why": "...", "trap": "...",        # optional
    "source": "GATE 2024 CS S1 Q23 · 2026-10-10",
    "signature": "prob/bayes/base-rate", # mistake signature, becomes a tag
    "due_now": false                     # true = the mistake recurred; show it today
  }

Usage:
  anki_push.py cards.json [--dry-run] [--no-sync]
  anki_push.py --report          # flagged cards, leeches, daily time vs budget
Anki must be running on this machine (AnkiConnect listens on 127.0.0.1:8765).
"""
import argparse, json, sys, time, urllib.request

DECK, MODEL, URL = "GATE", "GATE Card", "http://127.0.0.1:8765"
KINDS = {"method", "fact", "contrast", "trap", "speed"}
BUDGET_MIN = (15, 20)  # Kartik's daily Anki window, minutes


def ac(action, **params):
    req = urllib.request.Request(URL, json.dumps({"action": action, "version": 6, "params": params}).encode())
    try:
        r = json.load(urllib.request.urlopen(req, timeout=30))
    except OSError as e:
        sys.exit(f"Anki is not reachable on {URL} ({e}). Open Anki on the laptop and retry.")
    if r.get("error"):
        raise RuntimeError(f"{action}: {r['error']}")
    return r["result"]


def tags_for(c):
    t = ["gate", f"kind::{c['kind']}"]
    if c.get("signature"):
        t.append("sig::" + c["signature"].strip("/").replace("/", "::"))
    return t + list(c.get("tags", []))


def validate(cards):
    seen, problems = set(), []
    for i, c in enumerate(cards):
        for k in ("uid", "kind", "prompt", "answer"):
            if not str(c.get(k, "")).strip():
                problems.append(f"card {i}: missing {k}")
        if c.get("kind") not in KINDS:
            problems.append(f"card {i}: kind must be one of {sorted(KINDS)}")
        if c.get("uid") in seen:
            problems.append(f"card {i}: duplicate uid {c.get('uid')}")
        seen.add(c.get("uid"))
    if problems:
        sys.exit("\n".join(problems))


def push(cards, dry_run, sync):
    validate(cards)
    added = updated = 0
    for c in cards:
        fields = {"Prompt": c["prompt"], "Answer": c["answer"], "Why": c.get("why", ""), "Trap": c.get("trap", ""),
                  "Kind": c["kind"], "Source": c.get("source", ""), "Signature": c.get("signature", ""), "UID": c["uid"]}
        existing = ac("findNotes", query=f'deck:{DECK} note:"{MODEL}" "UID:{c["uid"]}"')
        if dry_run:
            print(("update " if existing else "add    ") + c["uid"])
            continue
        if existing:
            nid = existing[0]
            ac("updateNoteFields", note={"id": nid, "fields": fields})
            old = ac("notesInfo", notes=[nid])[0]["tags"]
            ac("removeTags", notes=[nid], tags=" ".join(t for t in old if t.startswith(("kind::", "sig::"))))
            ac("addTags", notes=[nid], tags=" ".join(tags_for(c)))
            updated += 1
        else:
            nid = ac("addNote", note={"deckName": DECK, "modelName": MODEL, "fields": fields, "tags": tags_for(c),
                                      "options": {"allowDuplicate": True}})
            added += 1
        if c.get("due_now"):
            cids = ac("findCards", query=f"nid:{nid}")
            ac("setDueDate", cards=cids, days="0")
    print(f"added {added}, updated {updated}" + (" (dry run)" if dry_run else ""))
    if sync and not dry_run:
        ac("sync")
        print("synced to AnkiWeb")


def report():
    red = ac("findCards", query=f"deck:{DECK} flag:1")
    orange = ac("findCards", query=f"deck:{DECK} flag:2")
    leeches = ac("findNotes", query=f"deck:{DECK} tag:leech")
    print(f"red-flagged (fix): {len(red)} · orange-flagged (drop?): {len(orange)} · leeches (rewrite): {len(leeches)}")
    for cid, info in zip(red + orange, ac("cardsInfo", cards=red + orange) if red + orange else []):
        print(f"  flag {info.get('flags')} · {info['fields']['UID']['value']} · {info['fields']['Prompt']['value'][:70]}")
    # Daily time spent, last 7 days
    since = int((time.time() - 7 * 86400) * 1000)
    revs = ac("cardReviews", deck=DECK, startID=since)  # rows: [reviewTime, cardID, usn, buttonPressed, newInt, prevInt, newFactor, reviewDuration_ms, reviewType]
    per_day = {}
    for r in revs:
        day = time.strftime("%Y-%m-%d", time.localtime(r[0] / 1000))
        per_day.setdefault(day, [0, 0]); per_day[day][0] += 1; per_day[day][1] += r[7] / 1000
    for day in sorted(per_day):
        n, secs = per_day[day]
        print(f"  {day}: {n} reviews, {secs/60:.1f} min ({secs/max(n,1):.1f} s/card)")
    conf = ac("getDeckConfig", deck=DECK)
    print(f"new cards/day {conf['new']['perDay']} · reviews/day {conf['rev']['perDay']} · budget {BUDGET_MIN[0]}–{BUDGET_MIN[1]} min")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cards", nargs="?")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-sync", action="store_true")
    p.add_argument("--report", action="store_true")
    a = p.parse_args()
    if a.report:
        report()
    elif a.cards:
        push(json.load(open(a.cards)), a.dry_run, not a.no_sync)
    else:
        p.print_help()
