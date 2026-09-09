# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "readability-lxml>=0.8,<1",
#   "lxml_html_clean>=0.4",
#   "markdownify>=1.1,<2",
#   "pymupdf4llm>=1.28,<2",
#   "trafilatura>=2.0,<3",
# ]
# ///
"""
Drain the read-later inbox into items.

    uv run scripts/ingest.py [--dry-run] [--json] STATE_DIR

Layout under STATE_DIR:
    inbox/<id>.json            one event per file, written by the Chrome extension
    items/<folder>/item.json   one folder per page: <capturedAt>-<title slug>
    items/<folder>/content.md  the article: short frontmatter + Markdown (with images)
    feedback.jsonl             append-only log (archive lines land here)

Dedup key is the canonical `url` inside each item.json; there is no separate index.

Events: `capture` (default) adds a page; `remove` retracts earlier captures of the same URL
(drops unprocessed ones, archives a processed item); `done` marks a processed item as read.

Content: captured HTML → readability; else fetch the URL, which may be HTML or a PDF (PyMuPDF layout
→ Markdown with headings and tables, no OCR, no images); else the event's own `text`.

Failed extractions are retried on later runs by fetching the URL again: at most RETRY_MAX
attempts, at least RETRY_AFTER_HOURS apart, recorded as `attempts` and `failedAt` on the item.
After that the item stays `failed` until the reader saves the page again or removes it.

Inbox content is untrusted input. This script parses it; it never executes it.

Exit codes: 0 ran (per-item failures are recorded on the items), 2 bad arguments,
3 STATE_DIR does not exist or has no inbox/ folder.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import trafilatura
from lxml import html as lxml_html
from markdownify import markdownify
from readability import Document

MIN_WORDS = 80
FETCH_TIMEOUT = 20
FETCH_MAX = 40_000_000  # a paper with figures runs to tens of MB
USER_AGENT = "Mozilla/5.0 (compatible; read-later/0.2)"
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|source$|si$)")
SLUG_MAX = 60
RETRY_MAX = 3
RETRY_AFTER_HOURS = 20


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
            ev.setdefault("source", "unknown")
            if ev["action"] not in ("capture", "remove", "done"):
                raise ValueError(f"unknown action {ev['action']!r}")
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


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:SLUG_MAX].rstrip("-")


def folder_name(captured_at: str, title: str | None, canonical: str) -> str:
    stamp = re.sub(r"[:.]", "-", captured_at.replace("Z", ""))[:19] + "Z"
    return f"{stamp}-{slugify(title or urlsplit(canonical).hostname or 'page') or 'page'}"


# ---------- extraction ----------

def extract(html: str, url: str, extracted_by: str) -> dict | None:
    """Body via readability + markdownify (keeps images and links); metadata via trafilatura."""
    try:
        doc = Document(html, url=url)
        body = doc.summary(html_partial=True)
    except Exception as e:  # noqa: BLE001
        print(f"readability failed: {e}", file=sys.stderr)
        return None
    md = markdownify(body, heading_style="ATX", strip=["script", "style"])
    md = re.sub(r"\]\((?!https?://|data:|#)([^)\s]+)\)", lambda m: f"]({urljoin(url, m.group(1))})", md)  # absolutize
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    words = len(re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md).split())
    if words < MIN_WORDS:
        return None
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta and meta.title else None) or doc.short_title() or None
    return {
        "title": title,
        "author": declared_author(html) or clean_author(meta.author if meta else None),
        "published": meta.date if meta else None,
        "words": words,
        "images": len(re.findall(r"!\[[^\]]*\]\(", md)),
        "extractedBy": extracted_by,
        "extractedAt": now(),
        "markdown": md,
    }


BAD_AUTHOR = re.compile(r"^(posted|by|author|written|admin|staff)\b|;|\||https?://", re.I)
USERNAME = re.compile(r"^[a-z0-9._-]+$")  # a CMS login, not a byline


def declared_author(html: str) -> str | None:
    """Author the page states explicitly: meta tags, then JSON-LD. No guessing."""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001
        return None
    for xp in ('//meta[@name="author"]/@content', '//meta[@property="article:author"]/@content', '//meta[@name="parsely-author"]/@content'):
        for v in tree.xpath(xp):
            if v := clean_author(v):
                return v
    for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        for node in nodes if isinstance(nodes, list) else []:
            author = node.get("author") if isinstance(node, dict) else None
            author = author[0] if isinstance(author, list) and author else author
            name = author.get("name") if isinstance(author, dict) else author if isinstance(author, str) else None
            if name := clean_author(name if isinstance(name, str) else None):
                return name
    return None


def clean_author(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value or len(value) > 80 or BAD_AUTHOR.search(value) or USERNAME.match(value):
        return None
    return value


# ---------- pdf ----------

PDF_DATE = re.compile(r"D:(\d{4})(\d{2})(\d{2})")
HEADING = re.compile(r"^(#{1,6} .*)$", re.M)
# HTML pages that describe a PDF, when the host has one: arXiv's abstract page carries the real title, authors and date.
LANDING_PAGES = [(re.compile(r"^https?://arxiv\.org/pdf/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?$"), "https://arxiv.org/abs/{}")]


def extract_pdf(data: bytes, extracted_by: str) -> dict | None:
    """Markdown via pymupdf4llm: headings and paragraphs from PyMuPDF's layout model, tables as pipe tables.

    Deterministic and offline: OCR off, images dropped, running heads and page numbers removed.
    """
    try:
        import pymupdf  # noqa: PLC0415  heavy import (onnxruntime); only PDFs pay for it
        import pymupdf4llm  # noqa: PLC0415

        doc = pymupdf.open(stream=data, filetype="pdf")
        md = pymupdf4llm.to_markdown(doc, use_ocr=False, header=False, footer=False, show_progress=False)
    except Exception as e:  # noqa: BLE001
        print(f"pdf extraction failed: {e}", file=sys.stderr)
        return None
    md = HEADING.sub(lambda m: re.sub(r"^(#+ )_(.+?)_$", r"\1\2", m.group(1).replace("**", "").rstrip()), md)  # headings come bold- or italic-wrapped
    md = re.sub(r"<!-- Start of picture text -->\s*(.*?)\s*<!-- End of picture text -->",
                lambda m: "```\n" + re.sub(r"<br\s*/?>", "\n", m.group(1)).strip() + "\n```", md, flags=re.S)  # ASCII diagrams as code
    md = re.sub(r"</?mark>", "", md)  # code spans come wrapped in <mark>
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    md = re.sub(r"^[ \t]*[-*][ \t]*\n", "", md, flags=re.M)  # empty bullets from list glyphs the layout model split off
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    words = len(md.split())
    if words < MIN_WORDS:
        return None
    meta = doc.metadata or {}
    first_heading = re.search(r"^# (.+)$", md, re.M)
    created = PDF_DATE.match(meta.get("creationDate") or "")
    return {
        "title": clean_title(first_heading.group(1) if first_heading else None) or clean_title(meta.get("title")),
        "author": clean_author(meta.get("author")),
        "published": "-".join(created.groups()) if created else None,
        "words": words,
        "images": 0,
        "pages": doc.page_count,
        "extractedBy": extracted_by,
        "extractedAt": now(),
        "markdown": md,
    }


def clean_title(value: str | None) -> str | None:
    """PDF title fields are often the source filename ('acmmv2', 'paper.docx'); a real title has words."""
    value = (value or "").strip()
    return value if len(value) >= 8 and " " in value and len(value) <= 300 else None


def landing_page(url: str) -> str | None:
    for pat, template in LANDING_PAGES:
        if m := pat.match(url):
            return template.format(m.group(1))
    return None


def citation_meta(html: str) -> dict:
    """Highwire Press `citation_*` meta tags, as on arXiv, ACM, IEEE, Springer: title, authors, date."""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001
        return {}

    def get(name: str) -> list[str]:
        return [v.strip() for v in tree.xpath(f'//meta[@name="{name}"]/@content') if v.strip()]

    authors = [" ".join(reversed(a.split(", ", 1))) if ", " in a else a for a in get("citation_author")]  # "Last, First"
    author = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "") if authors else None
    date = next(iter(get("citation_publication_date") + get("citation_date")), None)
    found = {"title": clean_title(next(iter(get("citation_title")), None)), "author": clean_author(author), "published": date.replace("/", "-") if date else None}
    return {k: v for k, v in found.items() if v}


# ---------- fetch ----------

def fetch(url: str) -> tuple[str, str | bytes] | None:
    """("html", text) or ("pdf", bytes); None for anything else or on error."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as res:  # honors HTTPS_PROXY
            ctype = res.headers.get("content-type", "text/html").lower()
            charset = res.headers.get_content_charset() or "utf-8"
            data = res.read(FETCH_MAX)
    except Exception as e:  # noqa: BLE001
        print(f"fetch failed {url}: {e}", file=sys.stderr)
        return None
    if "pdf" in ctype or data.startswith(b"%PDF"):
        return "pdf", data
    if "html" in ctype:
        return "html", data.decode(charset, errors="replace")
    print(f"fetch skipped {url}: {ctype}", file=sys.stderr)
    return None


def fetch_and_extract(url: str) -> dict | None:
    """Fetch the URL and extract whatever came back, HTML or PDF."""
    if not (fetched := fetch(url)):
        return None
    kind, body = fetched
    if kind == "html":
        return extract(body, url, "fetch")
    if content := extract_pdf(body, "fetch-pdf"):
        if (landing := landing_page(url)) and (page := fetch(landing)) and page[0] == "html":
            content.update(citation_meta(page[1]))  # the abstract page knows the paper better than the PDF's own metadata
        return content
    return None


def acquire(url: str, events: list[dict]) -> dict | None:
    for ev in reversed(events):
        if ev.get("html") and (content := extract(ev["html"], url, "capture")):
            return content
    if content := fetch_and_extract(url):
        return content
    for ev in reversed(events):
        if (text := ev.get("text")) and len(text.split()) >= MIN_WORDS:
            return {"title": ev.get("title"), "words": len(text.split()), "images": 0, "extractedBy": "capture-text", "extractedAt": now(), "markdown": text}
    return None


# ---------- store ----------

CAPTURE_KEEP = ("source", "note", "selectedText", "recommendedBy", "sourceRef")


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.inbox = root / "inbox"
        self.items = root / "items"
        self.items.mkdir(parents=True, exist_ok=True)
        self.by_url: dict[str, str] = {}
        for p in self.items.glob("*/item.json"):
            try:
                url = json.loads(p.read_text()).get("url")
                if url:
                    self.by_url[url] = p.parent.name
            except Exception as e:  # noqa: BLE001
                print(f"skip unreadable {p}: {e}", file=sys.stderr)

    def get(self, canonical: str) -> tuple[str, dict] | None:
        folder = self.by_url.get(canonical)
        if not folder:
            return None
        return folder, json.loads((self.items / folder / "item.json").read_text())

    def new_folder(self, captured_at: str, title: str | None, canonical: str) -> str:
        base = folder_name(captured_at, title, canonical)
        folder, n = base, 2
        while (self.items / folder).exists():
            folder, n = f"{base}-{n}", n + 1
        return folder

    def save(self, folder: str, item: dict, markdown: str | None = None) -> None:
        d = self.items / folder
        d.mkdir(parents=True, exist_ok=True)
        if markdown is not None:
            fm = {k: item.get(k) for k in ("title", "url", "author", "published")}
            front = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items() if v is not None)
            (d / "content.md").write_text(f"---\n{front}\n---\n\n{markdown}\n")
        (d / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")
        self.by_url[item["url"]] = folder

    def feedback(self, line: dict) -> None:
        with (self.root / "feedback.jsonl").open("a") as f:
            f.write(json.dumps(line) + "\n")


def first_title(evs: list[dict]) -> str | None:
    return next((e["title"] for e in evs if e.get("title")), None)


def capture_record(ev: dict) -> dict:
    rec = {"at": ev["capturedAt"]}
    rec.update({k: ev[k] for k in CAPTURE_KEEP if ev.get(k)})
    return rec


# ---------- run ----------

def apply_done(store: Store, events: list[dict]) -> list[dict]:
    """`done` events mark an existing item as read. Returns the other events. A done for an unknown URL is dropped with a note."""
    rest = []
    for ev in events:
        if ev["action"] != "done":
            rest.append(ev)
            continue
        canonical = canonicalize(ev["url"])
        found = store.get(canonical)
        if found and found[1]["status"] not in ("archived",):
            folder, item = found
            if item["status"] != "done":
                item["status"] = "done"
                item["doneAt"] = ev["capturedAt"]
                store.save(folder, item)
                store.feedback({"item": folder, "action": "done", "reason": f"marked via {ev.get('source', '?')}", "at": now()})
            print(f"done      items/{folder}", file=sys.stderr)
        else:
            print(f"dropped   {ev['_path'].name}  done for an unknown or archived item  {canonical}", file=sys.stderr)
        ev["_path"].unlink(missing_ok=True)
    return rest


def apply_removals(store: Store, events: list[dict]) -> dict[str, list[dict]]:
    """Group by canonical URL. Per URL the last event in time decides; a remove retracts everything before it."""
    groups: dict[str, list[dict]] = {}
    for ev in events:
        groups.setdefault(canonicalize(ev["url"]), []).append(ev)
    survivors: dict[str, list[dict]] = {}
    for canonical, group in groups.items():
        group.sort(key=lambda e: (e["capturedAt"], e["action"] == "capture"))  # remove sorts first on a tie
        last_remove = max((i for i, e in enumerate(group) if e["action"] == "remove"), default=-1)
        keep = [e for i, e in enumerate(group) if e["action"] == "capture" and i > last_remove]
        for e in group:
            if e not in keep:
                why = "remove event" if e["action"] == "remove" else "retracted by a later remove"
                print(f"dropped   {e['_path'].name}  {why}  {canonical}", file=sys.stderr)
                e["_path"].unlink(missing_ok=True)
        if keep:
            survivors[canonical] = keep
        elif (found := store.get(canonical)) and found[1]["status"] != "archived":
            folder, item = found
            item["status"] = "archived"
            store.save(folder, item)
            store.feedback({"item": folder, "action": "archive", "reason": f"removed via {group[-1].get('source', '?')}", "at": now()})
            print(f"archived  items/{folder}", file=sys.stderr)
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
            print(json.dumps({"id": ev.get("id", ev["_path"].stem), "action": ev["action"], "url": canonicalize(ev["url"]), "hasHtml": bool(ev.get("html"))}))
        print(f"dry run: {len(events)} event(s), nothing written", file=sys.stderr)
        return 0

    ok = failed = 0
    for canonical, evs in apply_removals(store, apply_done(store, events)).items():
        found = store.get(canonical)
        item = found[1] if found else {"url": canonical, "title": first_title(evs), "status": "captured", "mustRead": False, "captures": []}
        if found or len(evs) > 1:
            print(f"merged    {len(evs)} capture(s) into {'existing' if found else 'new'} item  {canonical}", file=sys.stderr)
        item["captures"] += [capture_record(e) for e in evs]
        item["mustRead"] = item["mustRead"] or any(e.get("mustRead") for e in evs)
        if item["status"] == "done":  # a fresh capture of a finished item puts it back in the queue
            item["status"] = "analyzed" if item.get("analysis") else "extracted"
            item.pop("doneAt", None)
            store.feedback({"item": found[0], "action": "reopen", "reason": f"captured again via {evs[-1].get('source', '?')}", "at": now()})
            print(f"reopened  items/{found[0]}", file=sys.stderr)
        markdown = None
        if not found or not (store.items / found[0] / "content.md").exists():
            if content := acquire(canonical, evs):
                markdown = content.pop("markdown")
                item.update({k: v for k, v in content.items() if v is not None}, status="extracted")
                item["title"] = item.get("title") or first_title(evs)
                item.pop("failure", None)
                ok += 1
            else:
                item.update(status="failed", failure=f"no source yielded at least {MIN_WORDS} words", attempts=item.get("attempts", 0) + 1, failedAt=now())
                failed += 1
        folder = found[0] if found else store.new_folder(evs[0]["capturedAt"], item.get("title"), canonical)
        store.save(folder, item, markdown)
        for e in evs:
            e["_path"].unlink(missing_ok=True)
        if args.json:
            print(json.dumps({"item": f"items/{folder}", "status": item["status"], "title": item.get("title"), "failure": item.get("failure")}))
        else:
            print(f"{item['status']:9} items/{folder}")
    retried = retry_failed(store, args.json)
    print(f"done: {ok} extracted, {failed} failed" + (f", {retried} recovered on retry" if retried else ""), file=sys.stderr)
    return 0


def retry_failed(store: Store, as_json: bool) -> int:
    """Fetch failed items again, bounded. Returns how many recovered."""
    recovered = 0
    cutoff = datetime.now(timezone.utc).timestamp() - RETRY_AFTER_HOURS * 3600
    for p in sorted(store.items.glob("*/item.json")):
        item = json.loads(p.read_text())
        if item.get("status") != "failed" or item.get("attempts", 1) >= RETRY_MAX:
            continue
        last = item.get("failedAt")
        try:
            if last and datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp() > cutoff:
                continue
        except ValueError:
            pass
        folder = p.parent.name
        if content := fetch_and_extract(item["url"]):
            markdown = content.pop("markdown")
            item.update({k: v for k, v in content.items() if v is not None}, status="extracted")
            item["title"] = item.get("title") or content.get("title")
            for k in ("failure", "attempts", "failedAt"):
                item.pop(k, None)
            store.save(folder, item, markdown)
            recovered += 1
            print(f"retried   items/{folder}  extracted on attempt {item.get('attempts', 0) + 1}", file=sys.stderr)
        else:
            item["attempts"] = item.get("attempts", 1) + 1
            item["failedAt"] = now()
            store.save(folder, item)
            print(f"retried   items/{folder}  still failing ({item['attempts']}/{RETRY_MAX})", file=sys.stderr)
        if as_json:
            print(json.dumps({"item": f"items/{folder}", "status": item["status"], "title": item.get("title"), "failure": item.get("failure"), "attempts": item.get("attempts")}))
    return recovered


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
