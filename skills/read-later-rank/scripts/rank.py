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
                - 1 if it takes over 18 minutes (4140 words at 230 wpm, or a long video or episode); the exact value, not the rounded minutes
                + 3 if mustRead
    excluded: archived or done items, items without analysis, `not-an-article`,
              news/announcements published more than 14 days ago.

Buckets: the top 3 are "Read today", the next 4 "Read next", the rest "Later".
Also lists what needs the reader's attention: items whose article could not be fetched
(`status: failed`), items whose analysis keeps failing (`analysisError`, no analysis yet) and the links
the Slack sweep set aside. A link the reader has since saved from the browser drops off the list, and a
fetch that used up its retries is marked `final`, so the page can say "save it again" instead of "retrying".
Writes STATE_DIR/queue.json (the order, buckets and attention list read-later-deliver renders) and prints a short text view.
Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR not usable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_WEIGHT = 5
LONG_READ_MINUTES = 18  # 4140 words at 230 wpm; compared exactly, not rounded
WORDS_PER_MINUTE = 230
NEWS_MAX_AGE_DAYS = 14
WEIGHTS = {"relevance": 0.5, "quality": 0.5}
RETRY_MAX = 3  # ingest.py stops fetching after this many attempts
NOISE_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|source$|si$|nd$|dlsi$)")
SITE_PARAMS = {"youtube.com": {"t", "start", "feature", "pp", "app"}, "x.com": {"t", "s"}, "twitter.com": {"t", "s"}}  # as in ingest.py


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
    topics = a.get("topics", [])
    tw = sorted((weights.get(t, DEFAULT_WEIGHT) for t in topics), reverse=True) or [DEFAULT_WEIGHT]
    relevance = sum(tw[:2]) / len(tw[:2])
    # the label the reader cares most about; on a tie the analyzer's first-listed wins
    top_topic = max(topics, key=lambda t: (weights.get(t, DEFAULT_WEIGHT), -topics.index(t))) if topics else None
    quality = (a["hardWon"]["score"] + a["grounded"]["score"]) / 2
    priority = WEIGHTS["relevance"] * relevance + WEIGHTS["quality"] * quality
    notes = []
    if exact_minutes(item) > LONG_READ_MINUTES:
        priority -= 1
        notes.append("long read" if not item.get("kind") else f"long {item['kind']}")
    if item.get("mustRead"):
        priority += 3
        notes.append("must read")
    return priority, {"relevance": round(relevance, 1), "quality": round(quality, 1), "topTopic": top_topic, "notes": notes}


def same_page(url: str) -> str:
    """A loose key for "the reader already has this one". ingest.py owns the real canonical form;
    this only has to match a Slack link against an item the reader saved from the browser."""
    p = urlsplit((url or "").strip())
    host = (p.hostname or "").removeprefix("www.")
    path = p.path.rstrip("/") or "/"
    pairs = parse_qsl(p.query, keep_blank_values=True)
    if host == "youtu.be":
        host, path, pairs = "youtube.com", "/watch", [("v", path.lstrip("/"))] + [kv for kv in pairs if kv[0] != "v"]
    elif host in ("m.youtube.com", "music.youtube.com"):
        host = "youtube.com"
    drop = SITE_PARAMS.get(host, set()) | ({"list", "index"} if host == "youtube.com" and path == "/watch" else set())
    query = sorted((k, v) for k, v in pairs if not NOISE_PARAMS.match(k) and k not in drop)
    return urlunsplit(("", host, path, urlencode(query), "")).lstrip("/")


def attention(folder: str, item: dict) -> dict | None:
    """Why the reader should look at this item themselves, or None. Rendered at the top of the library page."""
    if item.get("status") in ("archived", "done"):
        return None
    base = {"item": f"items/{folder}", "title": item.get("title") or item.get("url"), "url": item.get("url")}
    if item.get("status") == "failed":
        attempts = item.get("attempts", 1)
        return {**base, "kind": "fetch", "reason": item.get("failure") or "could not extract the article", "attempts": attempts,
                "final": attempts >= RETRY_MAX, "at": item.get("failedAt") or item.get("extractedAt")}
    if not item.get("analysis") and isinstance(item.get("analysisError"), dict):
        return {**base, "kind": "analysis", "reason": item["analysisError"].get("message") or "analysis failed", "at": item["analysisError"].get("at")}
    return None


def slack_skipped(root: Path) -> list[dict]:
    """Links the Slack sweep set aside (login walls, social posts): the reader can save them from the browser."""
    try:
        rows = json.loads((root / "slack" / "skipped.json").read_text())
    except (OSError, ValueError):
        return []
    return [{"item": None, "title": s.get("title") or s["url"], "url": s["url"], "kind": "slack", "reason": s.get("reason") or "cannot fetch",
             "by": s.get("by"), "sourceRef": s.get("permalink"), "at": s.get("at")} for s in rows if isinstance(s, dict) and s.get("url")]


def exact_minutes(item: dict) -> float:
    """Play time for a video or audio item, reading time for an article."""
    if item.get("durationSeconds"):
        return item["durationSeconds"] / 60
    return (item.get("words") or 0) / WORDS_PER_MINUTE


def minutes(item: dict) -> int:
    return max(1, round(exact_minutes(item)))


def render_md(buckets: dict[str, list[dict]], today: date, needs: list[dict] | None = None) -> str:
    out = [f"# Read later · {today.isoformat()}", ""]
    if needs:
        out += ["## Needs attention", ""] + [f"- [{n['title']}]({n['url']}) · {n['kind']}: {n['reason']}" for n in needs] + [""]
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
    ranked, skipped, needs, have = [], 0, [], set()
    for p in sorted((root / "items").glob("*/item.json")):
        item = json.loads(p.read_text())
        if item.get("status") != "failed":
            have.add(same_page(item.get("url")))  # the reader has the page itself; nothing to look at
        if att := attention(p.parent.name, item):
            needs.append(att)
        s = score(item, weights, today)
        if s is None:
            skipped += 1
            continue
        priority, detail = s
        ranked.append({"item": f"items/{p.parent.name}", "title": item.get("title"), "url": item["url"], "priority": round(priority, 2),
                       "minutes": minutes(item), "analysis": item["analysis"], **detail})
    needs += slack_skipped(root)
    # Only a Slack row can be resolved this way: the reader saved the page from the browser, so it is an item now.
    # A row about an item of our own (failed fetch, failed analysis) names that item and must stay.
    dropped = len(needs)
    needs = [n for n in needs if n.get("kind") != "slack" or same_page(n["url"]) not in have]
    dropped -= len(needs)
    ranked.sort(key=lambda e: (-e["priority"], e["item"]))
    buckets = {"read_today": ranked[: args.today], "read_next": ranked[args.today : args.today + args.next_], "later": ranked[args.today + args.next_ :]}

    # topics present in the queue, most relevant to the reader first: the page's filter chips
    counts: dict[str, int] = {}
    for e in ranked:
        for t in e["analysis"].get("topics", []):
            counts[t] = counts.get(t, 0) + 1
    topic_index = sorted(({"label": t, "weight": weights.get(t, DEFAULT_WEIGHT), "count": n} for t, n in counts.items()),
                         key=lambda x: (-x["weight"], -x["count"], x["label"]))
    queue = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), "weights": WEIGHTS, "topics": topic_index,
             "buckets": {k: [{kk: vv for kk, vv in e.items() if kk != "analysis"} | {"tldr": e["analysis"]["tldr"], "category": e["analysis"]["category"], "topics": e["analysis"]["topics"]} for e in v] for k, v in buckets.items()},
             "attention": needs}
    (root / "queue.json").write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(queue, indent=2, ensure_ascii=False) if args.json else render_md(buckets, today, needs))
    print(f"ranked {len(ranked)} item(s), skipped {skipped} (unanalyzed or outdated analysis, done, archived, not-an-article or stale news), "
          f"{len(needs)} need attention" + (f" ({dropped} already saved)" if dropped else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
