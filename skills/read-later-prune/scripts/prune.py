#!/usr/bin/env python3
"""
Prune the read-later pool: move finished and dropped items out of items/.

    python3 scripts/prune.py [--dry-run] [--max-age-days N] STATE_DIR

Folders under STATE_DIR:
    items/     the live pool; rank reads only this
    done/      items the reader finished (status "done")
    archive/   items dropped: un-bookmarked (status "archived"), not-an-article,
               or unread for more than --max-age-days (default 30) and not must-read

Moves whole item folders; never deletes anything. Appends one line per move to
feedback.jsonl. Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR not usable.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

DEFAULT_MAX_AGE_DAYS = 30


def first_capture(item: dict) -> date | None:
    ats = sorted(c.get("at", "") for c in item.get("captures", []) if c.get("at"))
    if not ats:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", ats[0])
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def verdict(item: dict, today: date, max_age: int) -> tuple[str, str] | None:
    """Return (destination folder, reason) or None to keep."""
    status = item.get("status")
    if status == "done":
        return "done", "finished reading"
    if status == "archived":
        return "archive", "removed by the reader"
    if (item.get("analysis") or {}).get("contentType") == "not-an-article":
        return "archive", "not an article"
    if status in ("extracted", "analyzed") and not item.get("mustRead"):
        first = first_capture(item)
        if first and (today - first).days > max_age:
            return "archive", f"unread for more than {max_age} days"
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="prune.py", description="Move finished items to done/ and dropped or stale items to archive/. Never deletes.",
                                 epilog="Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR not usable.")
    ap.add_argument("state_dir", metavar="STATE_DIR")
    ap.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS, help=f"archive unread items older than this (default {DEFAULT_MAX_AGE_DAYS})")
    ap.add_argument("--dry-run", action="store_true", help="print what would move; move nothing")
    args = ap.parse_args(argv)
    root = Path(args.state_dir).expanduser().resolve()
    items = root / "items"
    if not items.is_dir():
        print(f"error: {root} has no items/ folder.", file=sys.stderr)
        return 3
    today = datetime.now(timezone.utc).date()
    moved = {"done": 0, "archive": 0}
    for p in sorted(items.glob("*/item.json")):
        try:
            item = json.loads(p.read_text())
        except Exception as e:  # noqa: BLE001
            print(f"skip unreadable {p}: {e}", file=sys.stderr)
            continue
        v = verdict(item, today, args.max_age_days)
        if not v:
            continue
        dest_name, reason = v
        folder = p.parent.name
        dest = root / dest_name / folder
        print(f"{'would move' if args.dry_run else 'moved':10} items/{folder} -> {dest_name}/  ({reason})")
        if args.dry_run:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{folder}-{int(datetime.now().timestamp())}")
        shutil.move(str(p.parent), str(dest))
        moved[dest_name] += 1
        with (root / "feedback.jsonl").open("a") as f:
            f.write(json.dumps({"item": folder, "action": f"move:{dest_name}", "reason": reason, "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}) + "\n")
    remaining = len(list(items.glob("*/item.json")))
    print(f"{'dry run: ' if args.dry_run else ''}done {moved['done']}, archived {moved['archive']}, {remaining} item(s) remain in items/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
