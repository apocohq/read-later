#!/usr/bin/env python3
"""
Rank analyzed read-later items into tonight's queue. Deterministic; no model.

    python3 scripts/rank.py [--json] [--today N] [--next N] STATE_DIR

Inputs (all under STATE_DIR):
    items/*/item.json   items with `analysis` (from read-later-analyze)
    topics.md           topic weights: "- label: N" = how much the reader cares, 0-10; no number = 5

Scoring, per item, all on a 0-10 scale:
    relevance = mean of the two highest topic weights among the item's topics
    quality   = (hardWon + grounded) / 2
    priority  = 0.5 * relevance + 0.5 * quality
                - 1 if the article is over 4000 words (long reads need to earn it)
                + 3 if mustRead
    excluded: archived or done items, items without analysis, `not-an-article`,
              news/announcements published more than 14 days ago.

Buckets: the top 3 are "Read today", the next 4 "Read next", the rest "Later".
Writes STATE_DIR/queue.json (the order and buckets read-later-deliver renders) and prints a short text view.
Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR not usable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

DEFAULT_WEIGHT = 5
LONG_READ_WORDS = 4000
NEWS_MAX_AGE_DAYS = 14
WEIGHTS = {"relevance": 0.5, "quality": 0.5}


def load_weights(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    text = path.read_text()
    m = re.search(r"^# Topics\s*$([\s\S]*?)(?=^# |\Z)", text, re.M)
    if not m:
        return {}
    weights = {}
    for label, num in re.findall(r"^- ([a-z0-9]+(?:-[a-z0-9]+)*)(?::\s*(\d+))?\s*$", m.group(1), re.M):
        weights[label] = min(10, int(num)) if num else DEFAULT_WEIGHT
    return weights


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def score(item: dict, weights: dict[str, int], today: date) -> tuple[float, dict] | None:
    a = item.get("analysis")
    if not a or item.get("status") in ("archived", "done") or a.get("contentType") == "not-an-article":
        return None
    if not isinstance(a.get("hardWon"), dict) or not isinstance(a.get("grounded"), dict):
        return None  # analysis from an older version; read-later-analyze will redo it
    if a.get("contentType") in ("news", "announcement"):
        pub = parse_date(item.get("published"))
        if pub and (today - pub).days > NEWS_MAX_AGE_DAYS:
            return None
    tw = sorted((weights.get(t, DEFAULT_WEIGHT) for t in a.get("topics", [])), reverse=True) or [DEFAULT_WEIGHT]
    relevance = sum(tw[:2]) / len(tw[:2])
    quality = (a["hardWon"]["score"] + a["grounded"]["score"]) / 2
    priority = WEIGHTS["relevance"] * relevance + WEIGHTS["quality"] * quality
    notes = []
    if (item.get("words") or 0) > LONG_READ_WORDS:
        priority -= 1
        notes.append("long read")
    if item.get("mustRead"):
        priority += 3
        notes.append("must read")
    return priority, {"relevance": round(relevance, 1), "quality": round(quality, 1), "notes": notes}


def minutes(item: dict) -> int:
    return max(1, round((item.get("words") or 0) / 230))


def render_md(buckets: dict[str, list[dict]], today: date) -> str:
    out = [f"# Read later · {today.isoformat()}", ""]
    for name, title in (("read_today", "Read today"), ("read_next", "Read next"), ("later", "Later")):
        entries = buckets[name]
        out += [f"## {title}", ""]
        if not entries:
            out += ["_Nothing._", ""]
            continue
        for e in entries:
            a = e["analysis"]
            out.append(f"**[{e['title']}]({e['url']})** · {e['minutes']} min · {a['category']} · {', '.join(a['topics'])}")
            out.append(f"{a['tldr']}")
            why = f"relevance {e['relevance']} · hard-won {a['hardWon']['score']} · grounded {a['grounded']['score']}"
            if e["notes"]:
                why += " · " + ", ".join(e["notes"])
            out.append(f"_{why}_")
            out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="rank.py", description="Rank analyzed read-later items into tonight's queue (deterministic, no model).",
                                 epilog="Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR not usable.")
    ap.add_argument("state_dir", metavar="STATE_DIR")
    ap.add_argument("--today", type=int, default=3, help="items in Read today (default 3)")
    ap.add_argument("--next", dest="next_", type=int, default=4, help="items in Read next (default 4)")
    ap.add_argument("--json", action="store_true", help="print queue.json to stdout instead of the text view")
    args = ap.parse_args(argv)
    root = Path(args.state_dir).expanduser().resolve()
    if not (root / "items").is_dir():
        print(f"error: {root} has no items/ folder. Run read-later-ingest and read-later-analyze first.", file=sys.stderr)
        return 3

    weights = load_weights(root / "topics.md")
    today = datetime.now(timezone.utc).date()
    ranked, skipped = [], 0
    for p in sorted((root / "items").glob("*/item.json")):
        item = json.loads(p.read_text())
        s = score(item, weights, today)
        if s is None:
            skipped += 1
            continue
        priority, detail = s
        ranked.append({"item": f"items/{p.parent.name}", "title": item.get("title"), "url": item["url"], "priority": round(priority, 2),
                       "minutes": minutes(item), "analysis": item["analysis"], **detail})
    ranked.sort(key=lambda e: (-e["priority"], e["item"]))
    buckets = {"read_today": ranked[: args.today], "read_next": ranked[args.today : args.today + args.next_], "later": ranked[args.today + args.next_ :]}

    queue = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), "weights": WEIGHTS,
             "buckets": {k: [{kk: vv for kk, vv in e.items() if kk != "analysis"} | {"tldr": e["analysis"]["tldr"], "category": e["analysis"]["category"], "topics": e["analysis"]["topics"]} for e in v] for k, v in buckets.items()}}
    (root / "queue.json").write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(queue, indent=2, ensure_ascii=False) if args.json else render_md(buckets, today))
    print(f"ranked {len(ranked)} item(s), skipped {skipped} (unanalyzed or outdated analysis, done, archived, not-an-article or stale news)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
