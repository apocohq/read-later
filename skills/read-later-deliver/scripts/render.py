#!/usr/bin/env python3
"""
Render queue.json into a self-contained queue.html for the artifact library.

    python3 scripts/render.py [--json] STATE_DIR

Reads STATE_DIR/queue.json (from read-later-rank), writes STATE_DIR/queue.html,
and records the content hash in STATE_DIR/deliver.json. Prints one JSON object:
{"html": "<path>", "changed": true|false, "artifactId": "<id or null>"}.
`changed` is false when the rendered page is byte-identical to the last one
recorded, so the agent can skip publishing a new artifact version.

Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR or queue.json missing.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from pathlib import Path

BUCKETS = (("read_today", "Read today"), ("read_next", "Read next"), ("later", "Later"))

CSS = """
:root{--bg:#f6f5f2;--ink:#1e2126;--muted:#6b7078;--line:#dcd9d2;--card:#fff;--accent:#1d6f76}
@media (prefers-color-scheme:dark){:root{--bg:#14171b;--ink:#e6e8ea;--muted:#8d949c;--line:#2c3238;--card:#1b2026;--accent:#5cb8be}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:40px 20px 80px}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);font-size:13px;margin-bottom:32px}
h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:32px 0 12px}
.item{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px 18px;margin-bottom:12px}
.item.today{border-color:var(--accent)}.item h3{margin:0 0 6px;font-size:17px;line-height:1.3}.item h3 a{color:var(--ink);text-decoration:none}.item h3 a:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:12.5px;margin-bottom:10px}.meta b{color:var(--ink);font-weight:500}.tldr{margin:0 0 10px}
.claims{margin:0 0 10px 18px;padding:0;font-size:14px;color:var(--ink)}.claims li{margin:2px 0}
.why{font-size:12.5px;color:var(--muted)}.why span{display:inline-block;margin-right:12px}.tag{display:inline-block;font-size:11.5px;padding:1px 7px;border:1px solid var(--line);border-radius:10px;margin:0 4px 4px 0;color:var(--muted)}
.empty{color:var(--muted);font-style:italic}details{margin-top:8px}summary{cursor:pointer;color:var(--muted);font-size:13px}
"""


def esc(s: object) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def entry_html(e: dict, today: bool) -> str:
    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in e.get("topics", []))
    claims = "".join(f"<li>{esc(c)}</li>" for c in e.get("keyClaims", []))
    notes = " ".join(f"<span>{esc(n)}</span>" for n in e.get("notes", []))
    return f"""<article class="item{' today' if today else ''}">
<h3><a href="{esc(e['url'])}" target="_blank" rel="noopener">{esc(e.get('title') or e['url'])}</a></h3>
<div class="meta"><b>{esc(e.get('minutes'))} min</b> · {esc(e.get('category'))}{' · ' + esc(e['contentType']) if e.get('contentType') else ''}</div>
<p class="tldr">{esc(e.get('tldr'))}</p>
{f'<ul class="claims">{claims}</ul>' if claims else ''}
<div class="why"><span>relevance {esc(e.get('relevance'))}</span><span>hard-won {esc(e.get('hardWon'))}</span><span>grounded {esc(e.get('grounded'))}</span>{notes}</div>
<div style="margin-top:8px">{tags}</div>
</article>"""


def render(queue: dict) -> str:
    parts = [f"<title>Read later</title><style>{CSS}</style><main><h1>Read later</h1><div class=\"sub\">Generated {esc(queue.get('generatedAt', ''))}. One to read tonight, a few for the week, the rest can wait.</div>"]
    for key, title in BUCKETS:
        entries = queue.get("buckets", {}).get(key, [])
        parts.append(f"<h2>{title} · {len(entries)}</h2>")
        if not entries:
            parts.append('<p class="empty">Nothing.</p>')
            continue
        if key == "later" and len(entries) > 5:
            parts.append(f"<details><summary>{len(entries)} items</summary>" + "".join(entry_html(e, False) for e in entries) + "</details>")
        else:
            parts.extend(entry_html(e, key == "read_today") for e in entries)
    parts.append("</main>")
    return "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">" + "\n".join(parts) + "</html>\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="render.py", description="Render queue.json into a self-contained queue.html; report whether it changed since the last publish.")
    ap.add_argument("state_dir", metavar="STATE_DIR")
    args = ap.parse_args(argv)
    root = Path(args.state_dir).expanduser().resolve()
    qpath = root / "queue.json"
    if not qpath.exists():
        print(f"error: {qpath} missing. Run read-later-rank first.", file=sys.stderr)
        return 3
    queue = json.loads(qpath.read_text())
    # enrich entries with the analysis fields render needs
    for key, _ in BUCKETS:
        for e in queue.get("buckets", {}).get(key, []):
            ip = root / e["item"] / "item.json"
            if ip.exists():
                a = json.loads(ip.read_text()).get("analysis", {})
                e.setdefault("keyClaims", a.get("keyClaims", []))
                e.setdefault("contentType", a.get("contentType"))
                e.setdefault("hardWon", (a.get("hardWon") or {}).get("score"))
                e.setdefault("grounded", (a.get("grounded") or {}).get("score"))
    page = render(queue)
    # hash without the generated-at stamp, so an unchanged queue is unchanged
    digest = hashlib.sha256(page.replace(esc(queue.get("generatedAt", "")), "").encode()).hexdigest()
    (root / "queue.html").write_text(page)
    dpath = root / "deliver.json"
    state = json.loads(dpath.read_text()) if dpath.exists() else {}
    changed = state.get("contentHash") != digest
    state["contentHash"] = digest
    dpath.write_text(json.dumps(state, indent=2) + "\n")
    print(json.dumps({"html": str(root / "queue.html"), "changed": changed, "artifactId": state.get("artifactId")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
