# /// script
# requires-python = ">=3.11"
# dependencies = ["trafilatura>=2.0,<3"]
# ///
"""
Drain the read-later inbox into items.

    uv run scripts/ingest.py [--dry-run] [--json] STATE_DIR

Layout under STATE_DIR:
    inbox/<id>.json        one event per file, written by the Chrome extension
    items/<id>/item.json   one folder per canonical URL
    items/<id>/content.md  extracted article, frontmatter + Markdown
    index.json             canonical URL -> item id
    feedback.jsonl         append-only log (archive lines land here)

Inbox content is untrusted input. This script parses it; it never executes it.

Exit codes: 0 ran (per-item failures are recorded on the items), 2 bad arguments,
3 STATE_DIR does not exist or has no inbox/ folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import trafilatura

MIN_WORDS = 80
FETCH_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; read-later/0.1)"
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|source$|si$)")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------- events ----------

def load_events(inbox: Path) -> list[dict]:
    events = []
    for path in sorted(inbox.glob("*.json")):
        try:
            ev = json.loads(path.read_text())
            if not isinstance(ev, dict) or not ev.get("url") or not ev.get("capturedAt"):
                raise ValueError("missing url or capturedAt")
            ev.setdefault("action", "capture")
            ev.setdefault("mustRead", False)
            ev.setdefault("id", path.stem)
            ev["_path"] = path
            events.append(ev)
        except Exception as e:  # noqa: BLE001
            print(f"skip {path.name}: {e}", file=sys.stderr)
    return events


def canonicalize(url: str) -> str:
    p = urlsplit(url.strip())
    host = p.hostname or ""
    host = host[4:] if host.startswith("www.") else host
    if p.port and not ((p.scheme == "https" and p.port == 443) or (p.scheme == "http" and p.port == 80)):
        host = f"{host}:{p.port}"
    query = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k))
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), host, path, urlencode(query), ""))


def item_id(canonical: str) -> str:
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


# ---------- extraction ----------

def extract(html: str, url: str, extracted_by: str) -> dict | None:
    md = trafilatura.extract(html, url=url, output_format="markdown", include_links=True, include_tables=True, favor_recall=True)
    if not md or len(md.split()) < MIN_WORDS:
        return None
    meta = trafilatura.extract_metadata(html, default_url=url)
    return {
        "markdown": md,
        "title": (meta.title if meta else None),
        "author": (meta.author if meta else None),
        "published": (meta.date if meta else None),
        "wordCount": len(md.split()),
        "extractedBy": extracted_by,
        "extractedAt": now(),
    }


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as res:  # honors HTTPS_PROXY
            if "html" not in res.headers.get("content-type", "html"):
                return None
            return res.read(5_000_000).decode(res.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"fetch failed {url}: {e}", file=sys.stderr)
        return None


def acquire(item: dict) -> dict | None:
    url = item["canonicalUrl"]
    for cap in reversed(item["captures"]):
        if cap.get("html"):
            if content := extract(cap["html"], url, "capture"):
                return content
    if html := fetch(url):
        if content := extract(html, url, "fetch"):
            return content
    for cap in reversed(item["captures"]):
        if (text := cap.get("text")) and len(text.split()) >= MIN_WORDS:
            return {"markdown": text, "title": cap.get("title"), "wordCount": len(text.split()), "extractedBy": "capture-text", "extractedAt": now()}
    return None


# ---------- store ----------

class Store:
    def __init__(self, root: Path):
        self.root = root
        self.inbox = root / "inbox"
        self.items = root / "items"
        self.items.mkdir(parents=True, exist_ok=True)
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.index_path = root / "index.json"
        self.index: dict[str, str] = json.loads(self.index_path.read_text()) if self.index_path.exists() else {}

    def get(self, iid: str) -> dict | None:
        p = self.items / iid / "item.json"
        return json.loads(p.read_text()) if p.exists() else None

    def save(self, item: dict, content: dict | None = None) -> None:
        d = self.items / item["id"]
        d.mkdir(parents=True, exist_ok=True)
        if content:
            fm = {k: v for k, v in content.items() if k != "markdown" and v is not None}
            fm["url"] = item["canonicalUrl"]
            front = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items())
            (d / "content.md").write_text(f"---\n{front}\n---\n\n{content['markdown']}\n")
            item["content"] = fm
        item["captures"] = [{k: v for k, v in c.items() if k not in ("html", "_path")} for c in item["captures"]]
        (d / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")
        self.index[item["canonicalUrl"]] = item["id"]
        self.index_path.write_text(json.dumps(self.index, indent=2, sort_keys=True) + "\n")

    def feedback(self, line: dict) -> None:
        with (self.root / "feedback.jsonl").open("a") as f:
            f.write(json.dumps(line) + "\n")


# ---------- run ----------

def apply_removals(store: Store, events: list[dict]) -> list[dict]:
    """Per canonical URL the last event in time decides. A remove retracts everything before it."""
    groups: dict[str, list[dict]] = {}
    for ev in events:
        groups.setdefault(canonicalize(ev["url"]), []).append(ev)
    survivors = []
    for canonical, group in groups.items():
        group.sort(key=lambda e: (e["capturedAt"], e["action"] == "capture"))  # remove sorts first on a tie
        last_remove = max((i for i, e in enumerate(group) if e["action"] == "remove"), default=-1)
        for i, ev in enumerate(group):
            if ev["action"] == "capture" and i > last_remove:
                survivors.append(ev)
            else:
                ev["_path"].unlink(missing_ok=True)
        if last_remove == len(group) - 1:
            iid = store.index.get(canonical)
            item = store.get(iid) if iid else None
            if item and item["status"] != "archived":
                item.update(status="archived", updatedAt=now())
                store.save(item)
                store.feedback({"itemId": item["id"], "action": "archive", "reason": f"removed via {group[-1].get('source', '?')}", "createdAt": now()})
    return survivors


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="ingest.py",
        description="Drain the read-later inbox: canonicalize, dedupe, extract each page to Markdown, save under items/.",
        epilog="Examples:\n  uv run scripts/ingest.py ~/work/read-later\n  uv run scripts/ingest.py --dry-run ~/work/read-later\n\n"
        "Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR missing or without inbox/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("state_dir", metavar="STATE_DIR", help="folder holding inbox/ and items/, e.g. ~/work/read-later")
    ap.add_argument("--dry-run", action="store_true", help="list what would happen; write and delete nothing")
    ap.add_argument("--json", action="store_true", help="one JSON object per item on stdout instead of text lines")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = Path(args.state_dir).expanduser().resolve()
    if not (root / "inbox").is_dir():
        print(f"error: {root} has no inbox/ folder. Is this the state dir the extension uploads to?", file=sys.stderr)
        return 3
    store = Store(root)
    events = load_events(store.inbox)
    if args.dry_run:
        for ev in events:
            print(json.dumps({"id": ev["id"], "action": ev["action"], "canonicalUrl": canonicalize(ev["url"]), "hasHtml": bool(ev.get("html"))}))
        print(f"dry run: {len(events)} event(s), nothing written", file=sys.stderr)
        return 0

    ok = failed = 0
    for ev in apply_removals(store, events):
        canonical = canonicalize(ev["url"])
        iid = store.index.get(canonical) or item_id(canonical)
        item = store.get(iid) or {"id": iid, "canonicalUrl": canonical, "status": "captured", "captures": [], "createdAt": now()}
        item["captures"].append(ev)
        content = None
        if "content" not in item:
            content = acquire(item)
            if content:
                item["status"] = "extracted"
                item.pop("failure", None)
                ok += 1
            else:
                item["status"] = "failed"
                item["failure"] = f"no source yielded at least {MIN_WORDS} words"
                failed += 1
        item["updatedAt"] = now()
        store.save(item, content)
        ev["_path"].unlink(missing_ok=True)
        title = item.get("content", {}).get("title") or canonical
        if args.json:
            print(json.dumps({"id": iid, "status": item["status"], "title": title, "path": f"items/{iid}", "failure": item.get("failure")}))
        else:
            print(f"{item['status']:9} items/{iid}  {title}")
    print(f"done: {ok} extracted, {failed} failed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
