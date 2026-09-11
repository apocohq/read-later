#!/usr/bin/env python3
"""
Turn the reader's saved Slack messages ("Save for later") into read-later inbox events.

  slack.py STATE_DIR [--dry-run] [--json]

Searches Slack for `is:saved has:link` through the Slack MCP server and writes one
inbox event per new link found in a saved message. Saving is the reader's explicit
action, like the extension's bookmark button, so nothing is judged here. Links that
are never reading material (Slack permalinks, meetings, tickets, images) are dropped;
links the fetch fallback cannot reach (login walls, social posts) are listed in
STATE_DIR/slack/skipped.json for the library page instead of captured.

Runs on a DAM agent that holds the Slack connection: the egress gateway adds the token,
the script only speaks MCP to https://mcp.slack.com/mcp. It calls two read-only tools
and nothing else (see ALLOWED_TOOLS). Slack text never reaches the agent; the poster's
words travel as the event's `note`.

Standard library only. Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR or Slack unusable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MCP_URL = "https://mcp.slack.com/mcp"
ALLOWED_TOOLS = {"slack_search_public_and_private", "slack_read_user_profile"}
PAGE = 20  # the server's maximum
SEEN_DAYS = 90  # forget decisions older than this; items/ still dedupes captured URLs
NOTE_CHARS = 280

# Same rules as read-later-ingest so both sides agree on identity.
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|source$|si$|nd$|dlsi$)")

# Not reading material: dropped without a word.
DROP = re.compile(
    r"(^|\.)(slack\.com|slack-files\.com|zoom\.us|meet\.google\.com|calendar\.app\.google|calendar\.google\.com|calendly\.com|teams\.microsoft\.com"
    r"|atlassian\.net|linear\.app|notion\.so|figma\.com|miro\.com|trello\.com|giphy\.com|tenor\.com|gitlab\.com)$",
    re.I,
)
DROP_PATH = re.compile(r"^github\.com/[^/]+/[^/]+/(pull|issues|commit|actions|compare)(/|$)", re.I)
DROP_EXT = re.compile(r"\.(png|jpe?g|gif|webp|svg|mp4|mov|zip)$", re.I)
# Possibly worth reading, but the fetch fallback cannot get in: reported, not captured.
SKIP = [
    (re.compile(r"(^|\.)(docs|drive|sheets|slides)\.google\.com$|(^|\.)(box\.com|dropbox\.com|sharepoint\.com|onedrive\.live\.com|mural\.co|github\.ibm\.com|w3\.ibm\.com|claude\.ai)$", re.I), "needs login"),
    (re.compile(r"(^|\.)(x\.com|twitter\.com|linkedin\.com|lnkd\.in|instagram\.com|facebook\.com|threads\.net)$", re.I), "social post; needs a browser"),
]

LINK = re.compile(r"<(https?://[^|>\s]+)(?:\|([^>]*))?>")
BARE = re.compile(r"(?<![<\w])(https?://[^\s<>()\"']+)")
MENTION = re.compile(r"<@(\w+)(?:\|([^>]*))?>")
CHANNEL_REF = re.compile(r"<#\w+\|?([^>]*)>")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}


def youtube_id(p) -> str | None:
    """Same rule as read-later-ingest: one canonical URL per YouTube video, whatever the share form."""
    host = (p.hostname or "").removeprefix("www.")
    if host == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
    elif host in YOUTUBE_HOSTS:
        m = re.match(r"^/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})", p.path)
        vid = m.group(1) if m else dict(parse_qsl(p.query)).get("v", "")
    else:
        return None
    return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) else None


def canonicalize(url: str) -> str:
    p = urlsplit(url.strip())
    if vid := youtube_id(p):
        return f"https://youtube.com/watch?v={vid}"
    host = p.hostname or ""
    host = host[4:] if host.startswith("www.") else host
    if p.port and not ((p.scheme == "https" and p.port == 443) or (p.scheme == "http" and p.port == 80)):
        host = f"{host}:{p.port}"
    query = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k))
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), host, path, urlencode(query), ""))


# ---------- Slack MCP ----------

class Slack:
    def __init__(self, url: str = MCP_URL):
        self.url, self.sid = url, None
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "read-later-slack", "version": "0.2"}})

    def rpc(self, method: str, params: dict) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        for attempt in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(self.url, data=body, headers=headers), timeout=60) as r:
                    self.sid = r.headers.get("mcp-session-id", self.sid)
                    raw = r.read().decode()
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 4:  # Slack rate limit: back off (the Retry-After it sends is optimistic), then try again
                    wait = max(int(e.headers.get("Retry-After") or 0), 20 * (attempt + 1))
                    log(f"slack rate limit; waiting {wait}s")
                    time.sleep(wait)
                    continue
                hint = " Slack is rate limiting; run again later." if e.code == 429 else " Is the slack connection granted to this agent?"
                raise SystemExit(f"error: Slack MCP answered {e.code} for {method}.{hint}") from e
            except OSError as e:
                raise SystemExit(f"error: cannot reach {self.url}: {e}") from e
        if not raw.lstrip().startswith("{"):  # server-sent events framing
            raw = "".join(l[5:].strip() for l in raw.splitlines() if l.startswith("data:"))
        res = json.loads(raw)
        if "error" in res:
            raise SystemExit(f"error: Slack MCP {method}: {res['error'].get('message', res['error'])}")
        return res.get("result", {})

    def tool(self, name: str, args: dict) -> dict:
        if name not in ALLOWED_TOOLS:
            raise RuntimeError(f"tool {name} is not on the allowlist")
        res = self.rpc("tools/call", {"name": name, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise SystemExit(f"error: Slack tool {name} failed: {text[:300]}")
        try:
            return json.loads(text)
        except ValueError:
            return {"result": text}

    def me(self) -> dict:
        text = self.tool("slack_read_user_profile", {"response_format": "detailed"}).get("result", "")
        fields = dict(re.findall(r"^([A-Za-z ]+): ?(.*)$", text, re.M))
        if not fields.get("User ID"):
            raise SystemExit("error: could not read my own Slack user id")
        return {"id": fields["User ID"], "name": fields.get("Real Name") or fields.get("Display Name") or fields.get("Username", "")}

    def search(self, query: str, max_pages: int) -> list[dict]:
        """All message hits for a Slack search query, newest first, across pages."""
        hits, cursor = [], None
        for _ in range(max_pages):
            args = {"query": query, "content_types": "messages", "limit": PAGE, "sort": "timestamp", "sort_dir": "desc", "include_context": False, "include_bots": True}
            if cursor:
                args["cursor"] = cursor
            res = self.tool("slack_search_public_and_private", args)
            page = parse_results(res.get("results", ""))
            hits += page
            m = re.search(r"cursor `([^`]+)`", res.get("pagination_info", "") or "")
            cursor = m.group(1) if m else None
            if not cursor or not page:
                break
            time.sleep(1)  # search is rate limited per minute; a daily sweep is in no hurry
        return hits


HEAD = re.compile(r"^(Channel|Participants|From|Time|Message_ts|Reply count|Permalink): ?(.*)$")


def parse_results(md: str) -> list[dict]:
    """The search tool answers in Markdown. One dict per '### Result' block."""
    out = []
    for block in re.split(r"^### Result \d+ of \d+\s*$", md, flags=re.M)[1:]:
        hit: dict = {"text": ""}
        lines, i = block.strip("\n").split("\n"), 0
        while i < len(lines) and (m := HEAD.match(lines[i])):
            k, v = m.group(1), m.group(2).strip()
            if k == "Channel":
                cm = re.match(r"(.*?)\s*\(ID: (\w+)\)", v)
                hit["channel"], hit["channelId"] = (cm.group(1), cm.group(2)) if cm else (v, "")
            elif k == "Participants":
                hit["participants"] = re.findall(r"\(ID: (\w+)\)", v)
            elif k == "From":
                fm = re.match(r"(.*?)\s*\(ID: (\w+)\)\s*(\[BOT\])?", v)
                hit["from"], hit["fromId"], hit["bot"] = (fm.group(1), fm.group(2), bool(fm.group(3))) if fm else (v, "", False)
            elif k == "Message_ts":
                hit["ts"] = float(v) if re.match(r"^\d+(\.\d+)?$", v) else 0.0
            elif k == "Permalink":
                pm = re.search(r"\((https?://[^)]+)\)", v)
                hit["permalink"] = pm.group(1) if pm else v
            i += 1
        if i < len(lines) and lines[i].startswith("Text:"):
            i += 1
        body = []
        for line in lines[i:]:
            if line.strip() == "---" or line.startswith("Context before:") or line.startswith("Context after:"):
                break
            body.append(line)
        hit["text"] = "\n".join(body).strip()
        if hit.get("ts"):
            out.append(hit)
    return out


# ---------- links ----------

def unescape(s: str) -> str:
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def links(text: str) -> list[tuple[str, str | None]]:
    """(url, label) pairs from Slack mrkdwn; label only when it is not the URL itself."""
    found: list[tuple[str, str | None]] = []
    for m in LINK.finditer(text):
        url, label = unescape(m.group(1)), (m.group(2) or "").strip()
        if not label or label.startswith("http") or "…" in label or label.replace("www.", "") in url:
            label = None
        found.append((url, label))
    for m in BARE.finditer(LINK.sub(" ", text)):
        found.append((unescape(m.group(1)).rstrip(".,;:!?"), None))
    return found


def plain(text: str, limit: int) -> str:
    """The poster's words without link markup, mentions resolved, whitespace collapsed, trimmed."""
    text = LINK.sub(lambda m: m.group(2) if m.group(2) and (" " in m.group(2) or not re.search(r"[./…]", m.group(2))) else "", text)
    text = BARE.sub("", text)
    text = MENTION.sub(lambda m: "@" + (m.group(2) or m.group(1)), text)
    text = CHANNEL_REF.sub(lambda m: "#" + m.group(1), text)
    text = re.sub(r"\s+", " ", unescape(text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def classify(canonical: str) -> tuple[str, str | None]:
    """'keep' | 'drop' | 'skip' and a reason for skips."""
    p = urlsplit(canonical)
    host = p.hostname or ""
    if "." not in host or DROP.search(host) or DROP_PATH.match(host + p.path) or DROP_EXT.search(p.path):
        return "drop", None
    for rx, reason in SKIP:
        if rx.search(host):
            return "skip", reason
    return "keep", None


# ---------- state ----------

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def known_urls(root: Path) -> set[str]:
    urls = set()
    for folder in ("items", "done", "archive"):
        for p in (root / folder).glob("*/item.json"):
            if url := load_json(p, {}).get("url"):
                urls.add(url)
    for p in (root / "inbox").glob("*.json"):
        ev = load_json(p, {})
        if isinstance(ev, dict) and ev.get("url") and ev.get("action", "capture") == "capture":
            urls.add(canonicalize(ev["url"]))
    return urls


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def where(hit: dict, me: str) -> str:
    ch = hit.get("channel", "")
    if ch.startswith("#"):
        return ch
    others = [p for p in hit.get("participants", []) if p != me]
    return "a DM" if others else "your own DM"


def event(c: dict) -> dict:
    stamp = re.sub(r"[:.]", "-", c["at"].replace("Z", ""))[:23] + "Z"
    ev = {"id": f"{stamp}-{hashlib.sha1(c['url'].encode()).hexdigest()[:6]}-slack", "action": "capture", "source": "slack", "url": c["raw"],
          "capturedAt": c["at"], "mustRead": False, "sourceRef": c["permalink"]}
    for k in ("title", "note", "recommendedBy"):
        if c.get(k):
            ev[k] = c[k]
    return ev


# ---------- run ----------

def collect(hits: list[dict], me: dict, known: set[str], seen: dict) -> tuple[list[dict], list[dict]]:
    """One capture per new canonical URL across the saved messages. Returns (captures, skipped)."""
    captures: dict[str, dict] = {}
    skipped: dict[str, dict] = {}
    for hit in sorted(hits, key=lambda h: h["ts"]):
        place = where(hit, me["id"])
        poster = "you" if hit.get("fromId") == me["id"] else hit.get("from", "someone")
        by = None if poster == "you" and place == "your own DM" else f"{poster} in {place}"
        found = links(hit.get("text", ""))
        for raw, label in found:
            try:
                url = canonicalize(raw)
            except ValueError:
                continue
            p = urlsplit(url)
            if len(found) > 1 and p.path == "/" and not p.query:
                continue  # a bare domain mentioned next to the real link ("agents from x.ai") is not what was saved
            kind, reason = classify(url)
            if kind == "drop" or url in known or url in seen or url in captures or url in skipped:
                continue
            if kind == "skip":
                skipped[url] = {"url": url, "title": label, "reason": reason, "by": by or "you", "permalink": hit.get("permalink"), "at": iso(hit["ts"])}
                continue
            captures[url] = {"url": url, "raw": raw, "title": label, "at": iso(hit["ts"]), "permalink": hit.get("permalink"),
                             "note": plain(hit.get("text", ""), NOTE_CHARS), "recommendedBy": by}
    return list(captures.values()), list(skipped.values())


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="slack.py", description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR or Slack unusable.")
    ap.add_argument("state_dir", metavar="STATE_DIR", help="folder holding inbox/ and items/, e.g. ~/work/read-later")
    ap.add_argument("--pages", type=int, default=5, help="pages of 20 saved messages to read, newest first (default 5)")
    ap.add_argument("--mcp-url", default=MCP_URL, help=argparse.SUPPRESS)
    ap.add_argument("--dry-run", action="store_true", help="search and print; write nothing")
    ap.add_argument("--json", action="store_true", help="JSON lines on stdout instead of text")
    args = ap.parse_args(argv)

    root = Path(args.state_dir).expanduser().resolve()
    if not (root / "inbox").is_dir():
        log(f"error: {root} has no inbox/ folder. Is this the read-later state dir?")
        return 3
    sdir = root / "slack"
    sdir.mkdir(exist_ok=True)
    state = load_json(sdir / "state.json", {})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SEEN_DAYS)).isoformat()
    seen = {u: v for u, v in state.get("seen", {}).items() if v.get("at", "") >= cutoff}

    try:
        slack = Slack(args.mcp_url)
        me = state.get("me") or slack.me()
        hits = slack.search("is:saved has:link", args.pages)
    except SystemExit as e:
        if isinstance(e.code, str):
            log(e.code)
            return 3
        raise
    log(f"{me['name']} ({me['id']}): {len(hits)} saved message(s) with links")

    known = known_urls(root)
    captures, skipped = collect(hits, me, known, seen)
    at = now()
    for c in captures:
        ev = event(c)
        if not args.dry_run:
            (root / "inbox" / f"{ev['id']}.json").write_text(json.dumps(ev, ensure_ascii=False, indent=2) + "\n")
        seen[c["url"]] = {"decision": "captured", "at": at}
        print(json.dumps({"captured": c["url"], "by": c["recommendedBy"], "event": ev["id"]}, ensure_ascii=False) if args.json
              else f"captured   {c['url']}" + (f"  ({c['recommendedBy']})" if c["recommendedBy"] else ""))
    for s in skipped:
        seen[s["url"]] = {"decision": "skipped", "at": at, "reason": s["reason"]}
        print(json.dumps({"skipped": s["url"], "reason": s["reason"]}, ensure_ascii=False) if args.json else f"skipped    {s['url']}  ({s['reason']})")
    if not args.dry_run:
        (sdir / "state.json").write_text(json.dumps({"me": me, "lastSweepAt": at, "seen": seen}, indent=2, ensure_ascii=False) + "\n")
        old = [s for s in load_json(sdir / "skipped.json", []) if isinstance(s, dict) and s.get("url") and s["url"] not in known and s.get("at", "") >= cutoff]
        merged = {s["url"]: s for s in old + skipped}
        (sdir / "skipped.json").write_text(json.dumps(list(merged.values()), indent=2, ensure_ascii=False) + "\n")
    log(f"done: {len(captures)} captured, {len(skipped)} skipped, {len(hits)} saved messages seen{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
