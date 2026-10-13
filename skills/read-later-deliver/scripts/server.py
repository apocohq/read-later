#!/usr/bin/env python3
"""
The library page's server: the small HTTP API the interactive `Read later` artifact calls
through DAM's artifact bridge (`platform.request`). Standard library only.

    python3 scripts/server.py --ensure STATE_DIR   start it unless it already answers (what the schedule's Precheck runs)
    python3 scripts/server.py STATE_DIR            run it in the foreground (what --ensure starts)

It listens on 127.0.0.1:5555, the port DAM relays to (the Artifact API Port), and reads and writes
only inside STATE_DIR. DAM checks that the caller owns the artifact; this server checks every input.

    GET    /health                     {"app": "read-later", "version", "pid", "stateDir"}
    GET    /items                      {"items": {"<folder>": {"status", "highlights"}}} for every folder in items/
    PUT    /items/<folder>/highlights  body: the page's highlights.json; replaces the file
    PATCH  /items/<folder>             body: {"status": "done" | "archived"}
    DELETE /items/<folder>             removes the folder from items/, done/ or archive/ for good

Each change appends one line to feedback.jsonl, like ingest does for the same change.

--ensure prints one JSON object: {"running": true, "started": true|false, "pid", "log"}, or {"running": false, "error", "log", "logTail"}.
A running server of an older version (the skill was updated) is stopped and started again.
It starts the server with `platform-keep` when the agent has it, so the platform lists it and keeps it running.

Exit codes: 0 runs (or ran), 1 --ensure could not start it, 2 bad arguments, 3 STATE_DIR not usable or the port is taken.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST, PORT = "127.0.0.1", 5555
APP = "read-later"
VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]  # a new server.py restarts the old one
MAX_BODY = 1024 * 1024  # DAM's cap each way
FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
COLORS = {"yellow", "green", "blue", "pink", "orange"}
POOLS = ("items", "done", "archive")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(msg: str) -> None:
    print(f"{now()} {msg}", file=sys.stderr, flush=True)


class Fail(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ---------- state ----------

class State:
    def __init__(self, root: Path):
        self.root = root

    def folder(self, name: str, pools: tuple[str, ...] = ("items",)) -> Path:
        if not FOLDER.match(name) or ".." in name:
            raise Fail(400, "bad item name")
        for pool in pools:
            path = self.root / pool / name
            if (path / "item.json").is_file():
                return path
        raise Fail(404, f"no item {name}")

    def write_json(self, path: Path, doc: dict) -> None:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")  # a reader never sees half a file
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)

    def feedback(self, item: str, action: str, reason: str) -> None:
        with (self.root / "feedback.jsonl").open("a") as f:
            f.write(json.dumps({"item": item, "action": action, "reason": reason, "at": now()}) + "\n")

    @staticmethod
    def highlights_of(path: Path) -> list:
        try:
            doc = json.loads((path / "highlights.json").read_text())
            found = doc.get("highlights") if isinstance(doc, dict) else None
            return found if isinstance(found, list) else []
        except (OSError, ValueError):
            return []

    def items(self) -> dict:
        out = {}
        for p in sorted((self.root / "items").glob("*/item.json")):
            try:
                status = json.loads(p.read_text()).get("status")
            except (OSError, ValueError):
                continue
            out[p.parent.name] = {"status": status, "highlights": self.highlights_of(p.parent)}
        return {"items": out}

    def put_highlights(self, name: str, body: dict) -> dict:
        path = self.folder(name, POOLS)
        doc = clean_highlights(name, body)
        before = len(self.highlights_of(path))
        self.write_json(path / "highlights.json", doc)
        if len(doc["highlights"]) != before:  # the page saves on every edit; log only when the count moves
            self.feedback(name, "highlight", f"{len(doc['highlights'])} highlight(s) via page")
        return {"item": name, "highlights": len(doc["highlights"]), "updatedAt": doc["updatedAt"]}

    def patch_item(self, name: str, body: dict) -> dict:
        status = body.get("status")
        if status not in ("done", "archived"):
            raise Fail(400, 'status must be "done" or "archived"')
        path = self.folder(name)
        item = json.loads((path / "item.json").read_text())
        # the same rules as ingest's done and remove events
        if status == "done" and item.get("status") == "archived":
            raise Fail(409, "the item is archived")
        if item.get("status") != status:
            item["status"] = status
            if status == "done":
                item["doneAt"] = now()
            self.write_json(path / "item.json", item)
            self.feedback(name, "done" if status == "done" else "archive", "marked via page" if status == "done" else "removed via page")
            log(f"{status:<9} items/{name}")
        return {"item": name, "status": status}

    def delete_item(self, name: str) -> dict:
        path = self.folder(name, POOLS)
        shutil.rmtree(path)
        self.feedback(name, "delete", "deleted via page")
        log(f"deleted   {path.parent.name}/{name}")
        return {"item": name, "deleted": True}


def clean_highlights(name: str, body: dict) -> dict:
    """Keep the shape the page writes and the renderer reads; drop everything else."""
    found = body.get("highlights")
    if not isinstance(found, list) or len(found) > 5000:
        raise Fail(400, "highlights must be a list")
    if body.get("item") not in (None, name):
        raise Fail(400, "item does not match the path")
    out = []
    for h in found:
        if not (isinstance(h, dict) and isinstance(h.get("id"), str) and isinstance(h.get("exact"), str) and 0 < len(h["id"]) <= 64):
            raise Fail(400, "each highlight needs a string id and exact")
        keep = {"id": h["id"], "exact": h["exact"]}
        for k in ("prefix", "suffix", "note", "createdAt"):
            if isinstance(h.get(k), str):
                keep[k] = h[k]
        for k in ("start", "end"):
            if isinstance(h.get(k), int) and not isinstance(h.get(k), bool):
                keep[k] = h[k]
        if h.get("color") in COLORS:
            keep["color"] = h["color"]
        out.append(keep)
    url = body.get("url") if isinstance(body.get("url"), str) else None
    return {"item": name, **({"url": url} if url else {}), "updatedAt": now(), "highlights": out}


# ---------- HTTP ----------

ROUTES = [
    ("GET", re.compile(r"^/health$"), lambda s, m, b: {"app": APP, "version": VERSION, "pid": os.getpid(), "stateDir": str(s.root)}),
    ("GET", re.compile(r"^/items$"), lambda s, m, b: s.items()),
    ("PUT", re.compile(r"^/items/([^/]+)/highlights$"), lambda s, m, b: s.put_highlights(m[1], b)),
    ("PATCH", re.compile(r"^/items/([^/]+)$"), lambda s, m, b: s.patch_item(m[1], b)),
    ("DELETE", re.compile(r"^/items/([^/]+)$"), lambda s, m, b: s.delete_item(m[1])),
]


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"{APP}/{VERSION}"

        def log_message(self, fmt, *args):  # one line per request on stderr, no client address (always loopback)
            log(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}")

        def reply(self, status: int, doc: dict) -> None:
            data = json.dumps(doc, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def route(self) -> None:
            path = urllib.parse.unquote(self.path.split("?", 1)[0])
            try:
                for method, pattern, fn in ROUTES:
                    if (m := pattern.match(path)) and method == self.command:
                        self.reply(200, fn(state, m, self.body() if method in ("PUT", "PATCH") else {}))
                        return
                if any(p.match(path) for _, p, _ in ROUTES):
                    raise Fail(405, f"{self.command} not allowed on {path}")
                raise Fail(404, f"no route {path}")
            except Fail as err:
                self.reply(err.status, {"error": str(err)})
            except Exception as err:  # noqa: BLE001 - one bad request must not stop the server
                log(f"error     {self.command} {path}: {err!r}")
                self.reply(500, {"error": "internal error, see server.log"})

        def body(self) -> dict:
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_BODY:
                raise Fail(413, "body too large")
            try:
                doc = json.loads(self.rfile.read(size) or b"{}")
            except ValueError:
                raise Fail(400, "body is not JSON") from None
            if not isinstance(doc, dict):
                raise Fail(400, "body must be a JSON object")
            return doc

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = route

    return Handler


def serve(root: Path, port: int) -> int:
    try:
        httpd = HTTPServer((HOST, port), make_handler(State(root)))  # one request at a time: no two writes race
    except OSError as err:
        print(f"error: cannot listen on {HOST}:{port}: {err}", file=sys.stderr)
        return 3
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)  # --ensure stops an old version with SIGTERM
    log(f"listening {HOST}:{port} version {VERSION} state {root}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    log("stopped")
    return 0


# ---------- --ensure ----------

def health(port: int) -> dict | None:
    """The running server's /health, {} when something else answers, None when nothing listens."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/health", timeout=2) as res:
            doc = json.loads(res.read())
            return doc if isinstance(doc, dict) and doc.get("app") == APP else {}
    except urllib.error.HTTPError:
        return {}
    except (OSError, ValueError):
        return None


def tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def ensure(root: Path, port: int, dry_run: bool) -> int:
    logfile = root / "server.log"
    h = health(port)
    if h and h.get("version") == VERSION and h.get("stateDir") == str(root):
        print(json.dumps({"running": True, "started": False, "pid": h.get("pid"), "log": str(logfile)}))
        return 0
    if h == {}:
        print(json.dumps({"running": False, "error": f"another program answers on {HOST}:{port}; stop it first", "log": str(logfile)}))
        return 1
    if dry_run:
        print(json.dumps({"running": False, "wouldStart": True, "stops": h.get("pid") if h else None, "log": str(logfile)}))
        return 0
    if h:  # an older version, or another state dir: stop it and wait for the port
        log(f"ensure: stopping pid {h.get('pid')} (version {h.get('version')})")
        try:
            os.kill(int(h["pid"]), signal.SIGTERM)
        except (KeyError, ValueError, OSError):
            pass
        for _ in range(50):
            if health(port) is None:
                break
            time.sleep(0.1)
    cmd = [sys.executable, str(Path(__file__).resolve()), str(root)] + (["--port", str(port)] if port != PORT else [])
    keep = shutil.which("platform-keep")
    if keep:  # DAM: own session, output to the log, listed in the Processes panel and kept running
        subprocess.run([keep, "--log", str(logfile), "--", *cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=30)
    else:
        with logfile.open("a") as out:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
    for _ in range(100):
        time.sleep(0.1)
        if (h := health(port)) and h.get("version") == VERSION:
            print(json.dumps({"running": True, "started": True, "pid": h.get("pid"), "log": str(logfile), "keep": bool(keep)}))
            return 0
    print(json.dumps({"running": False, "error": "started, but /health did not answer within 10 s", "log": str(logfile), "logTail": tail(logfile)}))
    return 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="server.py", description="Serve the read-later library page's API on 127.0.0.1:5555, or with --ensure start it unless it already runs.")
    ap.add_argument("state_dir", metavar="STATE_DIR", help="e.g. ~/work/read-later")
    ap.add_argument("--ensure", action="store_true", help="start the server in the background unless the current version already answers; print JSON and exit")
    ap.add_argument("--dry-run", action="store_true", help="with --ensure: say what it would do, start and stop nothing")
    ap.add_argument("--port", type=int, default=PORT, help=argparse.SUPPRESS)  # tests only: DAM relays to 5555 and nothing else
    args = ap.parse_args(argv)
    root = Path(args.state_dir).expanduser().resolve()
    if not (root / "items").is_dir():
        print(f"error: {root}/items is missing; is STATE_DIR right?", file=sys.stderr)
        return 3
    if args.ensure:
        return ensure(root, args.port, args.dry_run)
    if args.dry_run:
        ap.error("--dry-run needs --ensure")
    return serve(root, args.port)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
