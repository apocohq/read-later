#!/usr/bin/env python3
"""
Sweep Slack for links worth reading and turn them into read-later inbox events.

Two commands:

  sweep    STATE_DIR   Search Slack (the reader's saved messages, then every link shared
                       since the last sweep) through the Slack MCP server. Messages the
                       reader saved ("Save for later") or sent to themselves become inbox
                       events at once. Every other link goes to a numbered shortlist,
                       printed on stdout and kept in STATE_DIR/slack/shortlist.json, for
                       the agent to judge. Links that cannot be fetched (login walls,
                       social posts) are listed in STATE_DIR/slack/skipped.json for the
                       library page.
  capture  STATE_DIR --picks 1,4,7 | none
                       Write inbox events for the picked shortlist entries; remember the
                       rest as rejected so they are not shown again (unless someone else
                       shares the same link later).

Runs on a DAM agent that holds the Slack connection: the egress gateway adds the token,
the script only speaks MCP to https://mcp.slack.com/mcp. It calls two read-only tools and
nothing else (see ALLOWED_TOOLS). Slack text never reaches the agent except as the trimmed
snippets in the shortlist.

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
SEEN_DAYS = 60  # forget decisions older than this; items/ still dedupes captured URLs
SNIPPET = 280
CONTEXT_LINES = 3
CONTEXT_CHARS = 160

# Same rules as read-later-ingest so both sides agree on identity.
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|source$|si$)")

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


def canonicalize(url: str) -> str:
    p = urlsplit(url.strip())
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
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "read-later-slack", "version": "0.1"}})

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

    def search(self, query: str, max_pages: int, stop_before: float | None = None) -> list[dict]:
        """All message hits for a Slack search query, newest first, across pages."""
        hits, cursor = [], None
        for _ in range(max_pages):
            args = {"query": query, "content_types": "messages", "limit": PAGE, "sort": "timestamp", "sort_dir": "desc", "include_context": True, "include_bots": False}
            if cursor:
                args["cursor"] = cursor
            res = self.tool("slack_search_public_and_private", args)
            page = parse_results(res.get("results", ""))
            hits += page
            m = re.search(r"cursor `([^`]+)`", res.get("pagination_info", "") or "")
            cursor = m.group(1) if m else None
            if not cursor or not page or (stop_before and page[-1]["ts"] < stop_before):
                break
            time.sleep(1)  # search is rate limited per minute; a daily sweep is in no hurry
        return hits


HEAD = re.compile(r"^(Channel|Participants|From|Time|Message_ts|Reply count|Permalink): ?(.*)$")


def parse_results(md: str) -> list[dict]:
    """The search tool answers in Markdown. One dict per '### Result' block."""
    out = []
    for block in re.split(r"^### Result \d+ of \d+\s*$", md, flags=re.M)[1:]:
        hit: dict = {"text": "", "context": []}
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
            elif k == "Reply count":
                hit["replies"] = int(v) if v.isdigit() else 0
            elif k == "Permalink":
                pm = re.search(r"\((https?://[^)]+)\)", v)
                hit["permalink"] = pm.group(1) if pm else v
            i += 1
        if i < len(lines) and lines[i].startswith("Text:"):
            i += 1
        body, ctx, mode = [], [], "text"
        for line in lines[i:]:
            if line.strip() == "---":
                break
            if line.startswith("Context before:") or line.startswith("Context after:"):
                mode = "ctx"
                continue
            if mode == "text":
                body.append(line)
            elif line.startswith("  ") and not line.strip().startswith("Message_ts:"):
                ctx.append(line.strip())
        hit["text"] = "\n".join(body).strip()
        hit["context"] = ctx
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
    text = LINK.sub(lambda m: m.group(2) if m.group(2) and (" " in m.group(2) or not re.search(r"[./…]", m.group(2))) else "", text)
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


def event(c: dict, source: str) -> dict:
    stamp = re.sub(r"[:.]", "-", c["at"].replace("Z", ""))[:23] + "Z"
    ev = {"id": f"{stamp}-{hashlib.sha1(c['url'].encode()).hexdigest()[:6]}-slack", "action": "capture", "source": source, "url": c["raw"],
          "capturedAt": c["at"], "mustRead": False, "sourceRef": c["permalink"]}
    if c.get("title"):
        ev["title"] = c["title"]
    if c.get("text"):
        ev["note"] = c["text"]
    if c.get("recommendedBy"):
        ev["recommendedBy"] = c["recommendedBy"]
    return ev


def write_event(root: Path, ev: dict, dry: bool) -> None:
    path = root / "inbox" / f"{ev['id']}.json"
    if not dry:
        path.write_text(json.dumps(ev, ensure_ascii=False, indent=2) + "\n")


# ---------- sweep ----------

def where(hit: dict, me: str) -> tuple[str, bool]:
    """Human-readable place and whether it is the reader's own DM."""
    ch = hit.get("channel", "")
    if ch.startswith("#"):
        return ch, False
    others = [p for p in hit.get("participants", []) if p != me]
    if not others:
        return "your own DM", True
    return "a DM", False


def candidates(hits: list[dict], me: dict, known: set[str], seen: dict) -> tuple[list[dict], list[dict]]:
    """Merge hits into one candidate per canonical URL. Returns (kept, skipped)."""
    by_url: dict[str, dict] = {}
    skipped: list[dict] = []
    for hit in sorted(hits, key=lambda h: h["ts"]):
        if hit.get("bot"):
            continue
        place, self_dm = where(hit, me["id"])
        for raw, label in links(hit.get("text", "")):
            try:
                url = canonicalize(raw)
            except ValueError:
                continue
            kind, reason = classify(url)
            if kind == "drop" or url in known:
                continue
            poster = "you" if hit.get("fromId") == me["id"] else hit.get("from", "someone")
            explicit = bool(hit.get("saved")) or self_dm  # the reader asked for it: let ingest try even behind a login
            if kind == "skip" and not explicit:
                if url not in seen and url not in {s["url"] for s in skipped}:
                    skipped.append({"url": url, "title": label, "reason": reason, "by": f"{poster} in {place}", "permalink": hit.get("permalink"), "at": iso(hit["ts"])})
                continue
            c = by_url.get(url)
            if not c:
                c = by_url[url] = {"url": url, "raw": raw, "title": label, "at": iso(hit["ts"]), "permalink": hit.get("permalink"), "text": plain(hit.get("text", ""), SNIPPET),
                                   "context": [plain(x, CONTEXT_CHARS) for x in hit.get("context", [])[:CONTEXT_LINES]], "replies": hit.get("replies", 0),
                                   "sharers": [], "sharerIds": [], "place": place, "selfDm": self_dm, "saved": bool(hit.get("saved"))}
            if hit.get("fromId") and hit["fromId"] not in c["sharerIds"]:
                c["sharerIds"].append(hit["fromId"])
                c["sharers"].append(poster)
            c["saved"] = c["saved"] or bool(hit.get("saved"))
            c["selfDm"] = c["selfDm"] or self_dm
            c["title"] = c["title"] or label
    skipped = [s for s in skipped if s["url"] not in by_url]  # the same message can come back from both searches
    kept = []
    for c in by_url.values():
        prior = seen.get(c["url"])
        if prior and not (prior.get("decision") == "rejected" and set(c["sharerIds"]) - set(prior.get("sharers", []))):
            continue
        c["recommendedBy"] = None if c["selfDm"] and c["sharers"] == ["you"] else f"{', '.join(c['sharers'])} in {c['place']}"
        # A saved or self-sent message is a request; but a bare domain in it is rarely the thing to read, so that still goes to the shortlist.
        p = urlsplit(c["url"])
        c["auto"] = (c["saved"] or c["selfDm"]) and not (p.path in ("", "/") and not p.query)
        kept.append(c)
    return kept, skipped


def cmd_sweep(args: argparse.Namespace) -> int:
    root = Path(args.state_dir).expanduser().resolve()
    if not (root / "inbox").is_dir():
        log(f"error: {root} has no inbox/ folder. Is this the read-later state dir?")
        return 3
    sdir = root / "slack"
    sdir.mkdir(exist_ok=True)
    state = load_json(sdir / "state.json", {})
    seen: dict = state.get("seen", {})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SEEN_DAYS)).isoformat()
    seen = {u: v for u, v in seen.items() if v.get("at", "") >= cutoff}

    slack = Slack(args.mcp_url)
    me = state.get("me") or slack.me()
    since = datetime.fromisoformat(state["lastSweepAt"].replace("Z", "+00:00")) - timedelta(days=1) if state.get("lastSweepAt") else datetime.now(timezone.utc) - timedelta(days=args.days)
    log(f"sweeping as {me['name']} ({me['id']}): saved messages, then links after {since.date()}")

    saved = slack.search("is:saved has:link", args.saved_pages)
    for h in saved:
        h["saved"] = True
    recent = slack.search(f"has:link after:{since.date().isoformat()}", args.max_pages, stop_before=since.timestamp())
    log(f"slack returned {len(saved)} saved and {len(recent)} recent messages with links")

    known = known_urls(root)
    kept, skipped = candidates(saved + recent, me, known, seen)
    auto = [c for c in kept if c["auto"]]
    shortlist = [c for c in kept if not c["auto"]]
    at = now()
    for c in auto:
        ev = event(c, "slack-saved" if c["saved"] else "slack-self")
        write_event(root, ev, args.dry_run)
        seen[c["url"]] = {"decision": "captured", "at": at, "sharers": c["sharerIds"], "how": ev["source"]}
        print(json.dumps({"captured": c["url"], "how": ev["source"], "by": c["recommendedBy"]}) if args.json else f"captured   {c['url']}  ({'saved by you' if c['saved'] else 'your own DM'})")
    for s in skipped:
        seen[s["url"]] = {"decision": "skipped", "at": at, "sharers": [], "reason": s["reason"]}
        print(json.dumps({"skipped": s["url"], "reason": s["reason"]}) if args.json else f"skipped    {s['url']}  ({s['reason']})")
    for n, c in enumerate(shortlist, 1):
        c["n"] = n
    if not args.dry_run:
        state = {"me": me, "lastSweepAt": at, "seen": seen}
        (sdir / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        old = [s for s in load_json(sdir / "skipped.json", []) if isinstance(s, dict) and s.get("url") not in known and s.get("at", "") >= cutoff]
        merged = {s["url"]: s for s in old + skipped}
        (sdir / "skipped.json").write_text(json.dumps(list(merged.values()), indent=2, ensure_ascii=False) + "\n")
        (sdir / "shortlist.json").write_text(json.dumps({"sweepAt": at, "candidates": shortlist}, indent=2, ensure_ascii=False) + "\n")
    if args.json:
        print(json.dumps({"shortlist": shortlist}, ensure_ascii=False))
    else:
        print(f"\nshortlist  {len(shortlist)} candidate(s) for you to judge" + (" (dry run, nothing written)" if args.dry_run else ", in slack/shortlist.json"))
        for c in shortlist:
            head = f"[{c['n']}] {c['url']}"
            if c.get("title"):
                head += f"  · {c['title']}"
            print(head)
            meta = f"    {c['recommendedBy']} · {c['at'][:10]}" + (f" · {c['replies']} replies" if c.get("replies") else "")
            print(meta)
            if c.get("text"):
                print(f"    “{c['text']}”")
            for x in c.get("context", []):
                if x:
                    print(f"      ↳ {x}")
    log(f"done: {len(auto)} captured, {len(skipped)} skipped, {len(shortlist)} shortlisted, {len(known)} urls already known")
    return 0


# ---------- capture ----------

def cmd_capture(args: argparse.Namespace) -> int:
    root = Path(args.state_dir).expanduser().resolve()
    sdir = root / "slack"
    short = load_json(sdir / "shortlist.json", None)
    if not short or "candidates" not in short:
        log(f"error: {sdir / 'shortlist.json'} missing or empty. Run `sweep` first.")
        return 3
    cands = {str(c["n"]): c for c in short["candidates"]}
    picks = set() if args.picks.strip().lower() in ("none", "") else {p.strip() for p in args.picks.split(",") if p.strip()}
    if unknown := picks - set(cands):
        log(f"error: no such candidate(s): {', '.join(sorted(unknown))}. Valid: 1-{len(cands)}")
        return 2
    state = load_json(sdir / "state.json", {})
    seen = state.setdefault("seen", {})
    at = now()
    for n, c in cands.items():
        if n in picks:
            ev = event(c, "slack")
            write_event(root, ev, args.dry_run)
            seen[c["url"]] = {"decision": "captured", "at": at, "sharers": c["sharerIds"], "how": "slack"}
            print(json.dumps({"captured": c["url"], "by": c["recommendedBy"]}) if args.json else f"captured   {c['url']}  ({c['recommendedBy']})")
        else:
            seen[c["url"]] = {"decision": "rejected", "at": at, "sharers": c["sharerIds"]}
    if not args.dry_run:
        (sdir / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        (sdir / "shortlist.json").unlink(missing_ok=True)
    log(f"done: {len(picks)} captured, {len(cands) - len(picks)} rejected{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0


# ---------- cli ----------

def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="slack.py", description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR or Slack unusable.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sw = sub.add_parser("sweep", help="search Slack; capture saved and self-DM links; print a shortlist for the agent")
    sw.add_argument("state_dir", metavar="STATE_DIR", help="folder holding inbox/ and items/, e.g. ~/work/read-later")
    sw.add_argument("--days", type=int, default=7, help="first-run lookback in days (default 7); later runs continue from the last sweep")
    sw.add_argument("--max-pages", type=int, default=15, help="pages of 20 messages for the has:link search (default 15)")
    sw.add_argument("--saved-pages", type=int, default=5, help="pages of 20 messages for the saved-messages search (default 5)")
    sw.add_argument("--mcp-url", default=MCP_URL, help=argparse.SUPPRESS)
    sw.add_argument("--dry-run", action="store_true", help="search and print; write nothing")
    sw.add_argument("--json", action="store_true", help="JSON lines on stdout instead of text")
    cp = sub.add_parser("capture", help="write inbox events for picked shortlist entries; remember the rest as rejected")
    cp.add_argument("state_dir", metavar="STATE_DIR")
    cp.add_argument("--picks", required=True, metavar="N,N,…|none", help="shortlist numbers to capture, or `none`")
    cp.add_argument("--dry-run", action="store_true", help="print what would be written; write nothing")
    cp.add_argument("--json", action="store_true", help="JSON lines on stdout instead of text")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        return cmd_sweep(args) if args.cmd == "sweep" else cmd_capture(args)
    except SystemExit as e:
        if isinstance(e.code, str):
            log(e.code)
            return 3
        raise


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
