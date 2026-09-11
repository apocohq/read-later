# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "readability-lxml>=0.8,<1",
#   "lxml_html_clean>=0.4",
#   "markdownify>=1.1,<2",
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

Video and audio pages (Open Graph type video.* or music.*; JSON-LD VideoObject/PodcastEpisode only when
the page declares no type and no article) have no article to extract. They become items with `kind`, `durationSeconds`, `image`
and the publisher's description as content.md, and skip the minimum-words check.

Dedup key is the canonical `url` inside each item.json; there is no separate index. Canonicalizing drops
tracking params and per-host position/share params (YouTube `t`/`list`, X `t`/`s`), and folds `youtu.be`
and the YouTube mobile hosts into `youtube.com/watch?v=...`.

Titles are tidied (no unread counter, no trailing ` / X`, capped); a title that only names the site is
dropped and replaced by the tab title or one derived from the text.

Events: `capture` (default) adds a page; `remove` retracts earlier captures of the same URL
(drops unprocessed ones, archives a processed item); `done` marks a processed item as read;
`delete` retracts like `remove` and then removes the item folder for good, wherever prune left it
(items/, done/ or archive/). A later capture of the same URL starts a fresh item.
A capture of an item that is `done` reopens it. A capture with HTML of an item that already has text
is extracted again, and the new text replaces the old when it is clearly larger (twice the words and
at least REDO_MIN_GROWTH more) or the analyzer had judged the old text `not-an-article`; the analysis
is then dropped so it is redone. Items with highlights are never replaced.

Content: captured HTML → readability; else fetch the URL, which may be HTML or a PDF (PyMuPDF layout
→ Markdown with headings and tables, no OCR, no images; PyMuPDF is installed on first use by
`pdf_to_md.py`, a subprocess, so agents that never meet a PDF never download it); else the event's own `text`.

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
import shutil
import subprocess
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
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|source$|si$|nd$|dlsi$)")  # si/nd/dlsi: Spotify share and app-handoff params
# Per-host parameters that name a position in the media or the share, not the page: the same page with and
# without them is one item. Host-scoped, because `t` and `s` mean real things on other sites.
SITE_PARAMS = {
    "youtube.com": {"t", "start", "feature", "pp", "app"},
    "x.com": {"t", "s"},
    "twitter.com": {"t", "s"},
}
WATCH_PARAMS = {"list", "index"}  # part of a playlist URL's identity, noise on a watch URL
SLUG_MAX = 60
RETRY_MAX = 3
RETRY_AFTER_HOURS = 20
PDF_TIMEOUT = 900  # the first PDF also installs PyMuPDF (about 250 MB)
REDO_MIN_GROWTH = 100  # words a re-capture must add (and double) to replace an item's text


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
            if ev["action"] not in ("capture", "remove", "done", "delete"):
                raise ValueError(f"unknown action {ev['action']!r}")
            ev["_path"] = path
            events.append(ev)
        except Exception as e:  # noqa: BLE001
            print(f"skip {path.name}: {e}", file=sys.stderr)
    return events


YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_id(p) -> str | None:
    """The 11-character video id from any YouTube URL shape, or None: youtu.be/ID, watch?v=ID, shorts/ID, embed/ID, live/ID."""
    host = (p.hostname or "").removeprefix("www.")
    if host == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
    elif host in YOUTUBE_HOSTS:
        m = re.match(r"^/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})", p.path)
        vid = m.group(1) if m else dict(parse_qsl(p.query)).get("v", "")
    else:
        return None
    return vid if YOUTUBE_ID.match(vid) else None


def canonicalize(url: str) -> str:
    p = urlsplit(url.strip())
    if vid := youtube_id(p):
        return f"https://youtube.com/watch?v={vid}"  # the timestamp, playlist and share parameters are the same video
    host = p.hostname or ""
    host = host[4:] if host.startswith("www.") else host
    if p.port and not ((p.scheme == "https" and p.port == 443) or (p.scheme == "http" and p.port == 80)):
        host = f"{host}:{p.port}"
    path = p.path.rstrip("/") or "/"
    pairs = parse_qsl(p.query, keep_blank_values=True)
    if host == "youtu.be":  # a share link for a video: the same item as its watch URL
        host, path, pairs = "youtube.com", "/watch", [("v", path.lstrip("/"))] + [kv for kv in pairs if kv[0] != "v"]
    elif host in ("m.youtube.com", "music.youtube.com"):  # same page, one item; the path still says which page
        host = "youtube.com"
    drop = SITE_PARAMS.get(host, set()) | (WATCH_PARAMS if host == "youtube.com" and path == "/watch" else set())
    query = sorted((k, v) for k, v in pairs if not TRACKING.match(k) and k not in drop)
    return urlunsplit((p.scheme.lower(), host, path, urlencode(query), ""))


UNREAD_COUNT = re.compile(r"^\(\d+\)\s*")  # X, Gmail and others put an unread counter in the tab title
X_SUFFIX = re.compile(r"\s*[/|]\s*(X|Twitter)\s*$", re.I)
TITLE_MAX = 140
# Tab titles that name the site, not the page. X gives "(1) X" for an article you are logged in to read.
PLACEHOLDER_TITLES = {"x", "twitter", "home", "post", "youtube", "spotify", "github", "linkedin", "reddit", "loading"}


def tidy_title(value: str | None) -> str | None:
    """A tab title, cleaned: no unread counter, no trailing site name, one line, not too long.
    Returns None when nothing useful is left, so a caller can fall back to a better source."""
    if not value:
        return None
    t = re.sub(r"\s+", " ", X_SUFFIX.sub("", UNREAD_COUNT.sub("", value)).strip())
    if t.lower().strip(" .!") in PLACEHOLDER_TITLES:
        return None
    if len(t) > TITLE_MAX:
        t = t[:TITLE_MAX].rsplit(" ", 1)[0].rstrip(" ,;:-–—") + "\u2026"
    return t or None


def derived_title(url: str, markdown: str | None, author: str | None) -> str | None:
    """When the page's own title says nothing (x.com articles): its first heading, else who posted and the first sentence."""
    body = (markdown or "").strip()
    if head := re.search(r"^#{1,3}\s+(.+)$", body, re.M):
        if t := tidy_title(head.group(1)):
            return t
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    if host in ("x.com", "twitter.com"):
        handle = urlsplit(url).path.lstrip("/").split("/")[0]
        who = author or (f"@{handle}" if handle else "Someone")
        lead = re.split(r"(?<=[.!?])\s", re.sub(r"\s+", " ", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)).strip())[0]
        return tidy_title(f"{who} on X: {lead}" if lead else f"{who} on X")
    return None


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
    title = tidy_title((meta.title if meta and meta.title else None) or doc.short_title())
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

    Runs `pdf_to_md.py` with `uv run` in a subprocess: PyMuPDF and its layout model are about 250 MB and
    only PDFs pay for them. Deterministic and offline: OCR off, images dropped, running heads and page numbers removed.
    """
    helper = Path(__file__).resolve().with_name("pdf_to_md.py")
    try:
        run = subprocess.run(["uv", "run", "--quiet", str(helper)], input=data, capture_output=True, timeout=PDF_TIMEOUT, check=False)
        if run.returncode != 0:
            raise RuntimeError(run.stderr.decode(errors="replace").strip().splitlines()[-1] if run.stderr.strip() else f"exit {run.returncode}")
        out = json.loads(run.stdout)
        md, meta, pages = out["markdown"], out.get("metadata") or {}, out.get("pages")
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
    first_heading = re.search(r"^# (.+)$", md, re.M)
    created = PDF_DATE.match(meta.get("creationDate") or "")
    return {
        "title": clean_title(first_heading.group(1) if first_heading else None) or clean_title(meta.get("title")),
        "author": clean_author(meta.get("author")),
        "published": "-".join(created.groups()) if created else None,
        "words": words,
        "images": 0,
        "pages": pages,
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
        return media(body, url) or extract(body, url, "fetch")
    if content := extract_pdf(body, "fetch-pdf"):
        if (landing := landing_page(url)) and (page := fetch(landing)) and page[0] == "html":
            content.update(citation_meta(page[1]))  # the abstract page knows the paper better than the PDF's own metadata
        return content
    return None


# ---------- video and podcast pages ----------

def ld_nodes(tree) -> list[dict]:
    """Every JSON-LD object on the page, flattened (lists and @graph), dicts only."""
    nodes = []
    for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict):
                nodes += [n for n in node.get("@graph", [node]) if isinstance(n, dict)]
    return nodes


def parse_duration(value) -> int | None:
    """Seconds from an ISO 8601 duration (PT1H2M3S, PT3.5S), a plain number of seconds, or nothing. Zero counts as unknown."""
    s = str(text(value) or "").strip()
    if s.isdigit():
        return int(s) or None
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", s)
    if not m or not any(m.groups()):
        return None
    d, h, mi, sec = (float(x or 0) for x in m.groups())
    return round(d * 86400 + h * 3600 + mi * 60 + sec) or None


def text(value) -> str | None:
    """A string out of a JSON-LD value: plain string, first of a list, or the @value / name of an object."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("@value") or value.get("name")
    return value.strip() if isinstance(value, str) and value.strip() else None


def youtube_description(html: str, url: str) -> str | None:
    """YouTube truncates its meta description; the full one is in the player response the page embeds.
    The page is a single-page app, so the embedded response can describe an earlier video: use it only
    when its video id matches the URL."""
    start = html.find("ytInitialPlayerResponse = ")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[start + len("ytInitialPlayerResponse = "):])
        details = obj.get("videoDetails", {})
        wanted = dict(parse_qsl(urlsplit(url).query)).get("v") or urlsplit(url).path.rsplit("/", 1)[-1]
        if details.get("videoId") != wanted:
            return None
        desc = details.get("shortDescription")
        return desc if isinstance(desc, str) else None
    except Exception:  # noqa: BLE001
        return None


ARTICLE_TYPES = {"article", "newsarticle", "blogposting", "report", "scholarlyarticle", "techarticle"}


def media(html: str, url: str) -> dict | None:
    """A video or audio page has no article to extract, so keep what the page declares about itself:
    title, description, duration, channel or show, date, cover image. The page's own Open Graph type
    decides (video.* → video, music.* → audio; Spotify labels episodes music.song). JSON-LD decides only
    when the page declares no type and describes no article, so an article with an embedded clip stays an article."""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001
        return None
    ld = ld_nodes(tree)
    types = {t.lower() for n in ld for t in (n.get("@type") if isinstance(n.get("@type"), list) else [n.get("@type")]) if isinstance(t, str)}
    og_type = "".join(tree.xpath('//meta[@property="og:type"]/@content')[:1]).lower()
    if og_type.startswith("video"):
        kind = "video"
    elif og_type.startswith("music"):
        kind = "audio"
    elif og_type or types & ARTICLE_TYPES:
        return None
    elif "videoobject" in types:
        kind = "video"
    elif types & {"podcastepisode", "audioobject"}:
        kind = "audio"
    else:
        return None

    def meta(*names: str) -> list[str]:
        return [v.strip() for n in names for v in tree.xpath(f'//meta[@property="{n}" or @name="{n}" or @itemprop="{n}"]/@content') if v.strip()]

    def first(*values):
        return next((v for v in values if v), None)

    descriptions = meta("description", "og:description", "twitter:description") + [text(n.get("description")) for n in ld] + [youtube_description(html, url)]
    description = max((d for d in descriptions if d), key=len, default="")
    spotify = re.match(r"Listen to this episode from (.+?) on Spotify\.\s*", description)  # the show name is in that sentence
    description = description[spotify.end():].strip() if spotify else description
    description = break_lines(description)
    all_links = BARE_URL.findall(description)
    description, links = clean_description(description)
    series = [text(n["partOfSeries"].get("name")) for n in ld if isinstance(n.get("partOfSeries"), dict)]
    published = first(*meta("music:release_date", "uploadDate", "datePublished", "video:release_date", "article:published_time"),
                      *[text(n.get("datePublished") or n.get("uploadDate")) for n in ld])
    return {
        "title": tidy_title(first(*meta("og:title"), *[text(n.get("name")) for n in ld], *[t.strip() for t in tree.xpath("//title/text()")])),
        "author": first(*tree.xpath('//*[@itemprop="author"]//*[@itemprop="name"]/@content'), *series, declared_author(html), spotify and spotify.group(1)),
        "published": published[:10] if published and re.match(r"\d{4}-\d{2}-\d{2}", published) else None,
        "kind": kind,
        "durationSeconds": first(*(parse_duration(v) for v in meta("music:duration", "duration", "og:video:duration", "video:duration") + [n.get("duration") for n in ld])),
        "image": first(*meta("og:image")),
        "links": links or None,
        "transcriptUrl": transcript_url(all_links),
        "words": len(description.split()),
        "images": 0,
        "extractedBy": "metadata",
        "extractedAt": now(),
        "markdown": description,
    }


# A description's trailer: sponsor pitches, link lists, social handles. Kept on the item as `links`, out of the text the
# reader and the analyzer see. The outline (chapter timestamps) stays.
HEADING_WORDS = r"(?:OUTLINE|TIMESTAMPS?|CHAPTERS?|SPONSORS?|PODCAST LINKS?|SOCIAL LINKS?|EPISODE LINKS?|CONTACT [A-Z]+|CREDITS|SUPPORT [A-Z ]+|SUBSCRIBE|MERCH(?:ANDISE)?|FOLLOW [A-Z ]+)"
TRAILER_HEADINGS = re.compile(r"(?im)^(?:sponsors?|podcast links?|social links?|contact \w+|episode links?|links?|follow (?:us|me)|credits|support (?:the|this) (?:show|podcast)|subscribe|merch(?:andise)?)\s*:")
OUTLINE_HEADING = re.compile(r"(?im)^(?:outline|timestamps?|chapters?)\s*:")
NOISE_LINE = re.compile(r"(?i)^(?:thank you for listening|thanks for listening|check out our sponsors|see below for timestamps|please (?:support|subscribe|rate)|subscribe (?:to|for)|follow (?:us|me))")
TIMESTAMP = re.compile(r"\(?\b\d{1,2}:\d{2}(?::\d{2})?\)?")
BARE_URL = re.compile(r"https?://[^\s<>()\"']+")


def split_glued_url(m: re.Match) -> str:
    """`https://x.com/pageNext sentence` → the URL, a newline, the sentence: a lowercase letter followed by Capital+lowercase
    inside a URL's last path segment is where the publisher's line break was lost."""
    url = m.group(0)
    tail = url.rfind("/") + 1
    if cut := re.search(r"[a-z0-9](?=[A-Z][a-z])", url[tail:]):
        i = tail + cut.end()
        return url[:i] + "\n" + url[i:]
    return url


def break_lines(text: str) -> str:
    """Restore line structure to a description that lost its newlines (Spotify's meta tags hold one run-on string).

    Breaks before an ALL-CAPS heading such as `SPONSORS:`, before a capital letter that follows a sentence end with no
    space, before each chapter timestamp, and where a URL runs straight into the next sentence. Text that already has
    newlines is left alone.
    """
    if "\n" in text:
        return text
    text = re.sub(r"(?<!^)(?<![A-Z] )(?=" + HEADING_WORDS + r":)", "\n", text)  # not inside a multi-word heading
    text = re.sub(r"(?<=[.!?])(?=[A-Z])", "\n", text)
    text = re.sub(r"(?<=\S)(?=\(\d{1,2}:\d{2}(?::\d{2})?\) )", "\n", text)
    text = BARE_URL.sub(split_glued_url, text)
    return text


def clean_description(text: str) -> tuple[str, list[str]]:
    """(description for the reader and the analyzer, links from the trailer blocks)."""
    lines = [l.rstrip() for l in text.split("\n")]
    keep, trailer, in_trailer = [], [], False
    for line in lines:
        if OUTLINE_HEADING.match(line) or TIMESTAMP.match(line.strip()):
            in_trailer = False
        elif TRAILER_HEADINGS.match(line):
            in_trailer = True
        if NOISE_LINE.match(line.strip()):
            trailer.append(line)
            continue
        (trailer if in_trailer else keep).append(line)
    links = list(dict.fromkeys(BARE_URL.findall("\n".join(trailer))))
    body = "\n".join(keep).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"(?<!\n)\n(?!\n)", "  \n", body)  # single newlines are meaningful here (chapters, credits): hard breaks in Markdown
    return body, links


def transcript_url(links: list[str]) -> str | None:
    """A transcript the publisher links from the description, on the publisher's own site (never the platform's)."""
    for link in links:
        host = (urlsplit(link).hostname or "").removeprefix("www.")
        if "transcript" in link.lower() and host and host not in YOUTUBE_HOSTS | {"youtu.be", "open.spotify.com"}:
            return link.rstrip(".,;:")
    return None


def attach_transcript(content: dict) -> dict:
    """For a video or audio item whose description links a transcript: fetch it and keep it as `transcript` (Markdown).

    The analyzer judges the transcript instead of the description. Silent on failure: the host may be outside the
    agent's network rules; the item is still complete without it.
    """
    if not content.get("kind") or not content.get("transcriptUrl"):
        return content
    fetched = fetch(content["transcriptUrl"])
    if fetched and fetched[0] == "html" and (page := extract(fetched[1], content["transcriptUrl"], "fetch")):
        content["transcript"] = page["markdown"]
        content["transcriptWords"] = page["words"]
        print(f"transcript {page['words']} words from {content['transcriptUrl']}", file=sys.stderr)
    else:
        print(f"transcript not fetched: {content['transcriptUrl']}", file=sys.stderr)
    return content


def acquire(url: str, events: list[dict]) -> dict | None:
    for ev in reversed(events):
        if ev.get("html") and (content := media(ev["html"], url) or extract(ev["html"], url, "capture")):
            return attach_transcript(content)
    if content := fetch_and_extract(url):
        return attach_transcript(content)
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
        if transcript := item.pop("transcript", None):
            (d / "transcript.md").write_text(f"---\nsource: {json.dumps(item.get('transcriptUrl'))}\n---\n\n{transcript}\n")
        if markdown is not None:
            fm = {k: item.get(k) for k in ("title", "url", "author", "published")}
            front = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items() if v is not None)
            (d / "content.md").write_text(f"---\n{front}\n---\n\n{markdown}\n")
        (d / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")
        self.by_url[item["url"]] = folder

    def feedback(self, line: dict) -> None:
        with (self.root / "feedback.jsonl").open("a") as f:
            f.write(json.dumps(line) + "\n")

    def find_anywhere(self, canonical: str) -> Path | None:
        """The item's folder in items/, done/ or archive/ (prune moves folders out of the pool); None if unknown."""
        if folder := self.by_url.get(canonical):
            return self.items / folder
        for pool in ("done", "archive"):
            for p in (self.root / pool).glob("*/item.json"):
                try:
                    if json.loads(p.read_text()).get("url") == canonical:
                        return p.parent
                except Exception:  # noqa: BLE001
                    continue
        return None

    def delete(self, path: Path) -> None:
        """Remove an item folder for good and forget it. Only a `delete` event gets here."""
        shutil.rmtree(path)
        self.by_url = {u: f for u, f in self.by_url.items() if f != path.name or path.parent != self.items}


def first_title(evs: list[dict]) -> str | None:
    return next((t for e in evs if (t := tidy_title(e.get("title")))), None)


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
    """Group by canonical URL. Per URL the last event in time decides; a remove or delete retracts everything before it.

    A delete also removes the existing item folder, wherever prune left it; captures after it start a fresh item.
    """
    groups: dict[str, list[dict]] = {}
    for ev in events:
        groups.setdefault(canonicalize(ev["url"]), []).append(ev)
    survivors: dict[str, list[dict]] = {}
    for canonical, group in groups.items():
        group.sort(key=lambda e: (e["capturedAt"], e["action"] == "capture"))  # remove/delete sort first on a tie
        retracts = [i for i, e in enumerate(group) if e["action"] in ("remove", "delete")]
        last_retract = retracts[-1] if retracts else -1
        keep = [e for i, e in enumerate(group) if e["action"] == "capture" and i > last_retract]
        for e in group:
            if e not in keep:
                why = f"{e['action']} event" if e["action"] != "capture" else f"retracted by a later {group[last_retract]['action']}"
                print(f"dropped   {e['_path'].name}  {why}  {canonical}", file=sys.stderr)
                e["_path"].unlink(missing_ok=True)
        if deletes := [group[i] for i in retracts if group[i]["action"] == "delete"]:
            if path := store.find_anywhere(canonical):
                store.delete(path)
                store.feedback({"item": path.name, "action": "delete", "reason": f"deleted via {deletes[-1].get('source', '?')}", "at": now()})
                print(f"deleted   {path.parent.name}/{path.name}", file=sys.stderr)
            else:
                print(f"dropped   delete for an unknown item  {canonical}", file=sys.stderr)
        if keep:
            survivors[canonical] = keep
        elif not deletes and (found := store.get(canonical)) and found[1]["status"] != "archived":
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


def has_highlights(folder: Path) -> bool:
    try:
        return bool(json.loads((folder / "highlights.json").read_text()).get("highlights"))
    except (OSError, ValueError, AttributeError):
        return False


def redo_reason(item: dict, fresh: dict) -> str | None:
    """Why a fresh extraction should replace the item's text, or None to keep what is there."""
    old, new = item.get("words") or 0, fresh.get("words") or 0
    if new >= 2 * old and new - old >= REDO_MIN_GROWTH:
        return f"{old} → {new} words"
    if (item.get("analysis") or {}).get("contentType") == "not-an-article":
        return "not-an-article"
    return None


def stored_markdown(store: "Store", found: tuple[str, dict] | None) -> str | None:
    path = store.items / found[0] / "content.md" if found else None
    return path.read_text() if path and path.exists() else None


def settle_title(item: dict, evs: list[dict], markdown: str | None) -> str | None:
    """The best title we have: the page's own, else the browser tab's, else one derived from the text.
    A stored placeholder ('(1) X') loses to any of them, so an old item improves on the next capture."""
    return tidy_title(item.get("title")) or first_title(evs) or derived_title(item["url"], markdown, item.get("author")) or item.get("title")


def process(store: Store, canonical: str, evs: list[dict], args: argparse.Namespace, ok: int, failed: int) -> tuple[int, int]:
    """One URL's captures → one item folder; deletes the inbox files it consumed. Raises on a bad page so main() can report it and move on."""
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
            item.pop("failure", None)
            ok += 1
        else:
            item.update(status="failed", failure=f"no source yielded at least {MIN_WORDS} words", attempts=item.get("attempts", 0) + 1, failedAt=now())
            failed += 1
    elif any(e.get("html") for e in evs) and not has_highlights(store.items / found[0]):
        # The item has text already and the browser sent HTML again: extract from it and keep the better of the two.
        # Better = clearly more text (a paywalled fetch replaced by the logged-in page), or the analyzer had judged the
        # old text not-an-article. Highlights anchor to the old text, so an item with highlights is never replaced.
        fresh = next((c for e in reversed(evs) if e.get("html") and (c := media(e["html"], canonical) or extract(e["html"], canonical, "capture"))), None)
        if fresh and (why := redo_reason(item, fresh)):
            markdown = fresh.pop("markdown")
            for k in ("analysis", "analysisError", "failure", "kind", "durationSeconds", "image", "links", "transcriptUrl", "transcriptWords"):
                item.pop(k, None)
            (store.items / found[0] / "transcript.md").unlink(missing_ok=True)
            item.update({k: v for k, v in fresh.items() if v is not None}, status="extracted")
            store.feedback({"item": found[0], "action": "re-extract", "reason": f"{why}; captured again with HTML via {evs[-1].get('source', '?')}", "at": now()})
            print(f"redo      items/{found[0]}  {why}", file=sys.stderr)
            ok += 1
    item["title"] = settle_title(item, evs, markdown if markdown is not None else stored_markdown(store, found))
    folder = found[0] if found else store.new_folder(evs[0]["capturedAt"], item.get("title"), canonical)
    store.save(folder, item, markdown)
    for e in evs:
        e["_path"].unlink(missing_ok=True)
    if args.json:
        print(json.dumps({"item": f"items/{folder}", "status": item["status"], "title": item.get("title"), "failure": item.get("failure")}))
    else:
        print(f"{item['status']:9} items/{folder}")
    return ok, failed


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
        try:
            ok, failed = process(store, canonical, evs, args, ok, failed)
        except Exception as e:  # noqa: BLE001
            print(f"error     {canonical}: {type(e).__name__}: {e}; its inbox file(s) stay for the next run", file=sys.stderr)
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
            item["title"] = settle_title(item, [], markdown)
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
