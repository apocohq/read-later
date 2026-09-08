#!/usr/bin/env python3
"""
Render the read-later library page: assets/template.html + data from the state dir.

    python3 scripts/render.py STATE_DIR

Reads STATE_DIR/queue.json (order and buckets, from read-later-rank) and, for each
entry, items/<folder>/item.json (analysis, metadata), content.md (the article) and
highlights.json (the reader's highlights, when any), injects everything as one JSON blob
into the template, and writes STATE_DIR/queue.html.
The template is the design; this script only supplies data. To restyle, edit the
template (or drop a copy at STATE_DIR/template.html, which wins).

Records the data's hash in STATE_DIR/deliver.json and prints one JSON object:
{"html": "<path>", "changed": true|false, "artifactId": "<id or null>", "items": N}.
`changed` is false when the data and the template are identical to the last publish,
so the agent can skip publishing a new artifact version.

Exit codes: 0 ran, 2 bad arguments, 3 STATE_DIR or queue.json missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
BUCKETS = ("read_today", "read_next", "later")
MAX_ARTICLE_WORDS = 12000  # keep the page well under the artifact size cap


def strip_frontmatter(md: str) -> str:
    if md.startswith("---\n"):
        end = md.find("\n---\n", 4)
        if end != -1:
            return md[end + 5 :]
    return md


def entry(root: Path, e: dict, bucket: str) -> dict:
    folder = root / e["item"]
    item = json.loads((folder / "item.json").read_text()) if (folder / "item.json").exists() else {}
    a = item.get("analysis") or {}
    body = strip_frontmatter((folder / "content.md").read_text()) if (folder / "content.md").exists() else ""
    highlights = []
    if (folder / "highlights.json").exists():
        try:
            doc = json.loads((folder / "highlights.json").read_text())
            found = doc.get("highlights") if isinstance(doc, dict) else None
            if isinstance(found, list):
                highlights = [h for h in found if isinstance(h, dict) and isinstance(h.get("id"), str) and isinstance(h.get("exact"), str)]
            else:
                print(f"warning: {folder.name}/highlights.json has no highlights list; ignored", file=sys.stderr)
        except (OSError, ValueError) as err:
            print(f"warning: {folder.name}/highlights.json unreadable: {err}", file=sys.stderr)
    words = body.split()
    if len(words) > MAX_ARTICLE_WORDS:
        body = " ".join(words[:MAX_ARTICLE_WORDS]) + "\n\n*Truncated for the library page; open the original for the rest.*"
    return {
        "id": Path(e["item"]).name,
        "bucket": bucket,
        "title": e.get("title") or item.get("title") or e.get("url"),
        "url": e.get("url") or item.get("url"),
        "author": item.get("author"),
        "published": item.get("published"),
        "words": item.get("words"),
        "minutes": e.get("minutes"),
        "kind": item.get("kind"),
        "durationSeconds": item.get("durationSeconds"),
        "mustRead": bool(item.get("mustRead")),
        "category": a.get("category"),
        "contentType": a.get("contentType"),
        "topics": a.get("topics", []),
        "topTopic": e.get("topTopic") or (a.get("topics") or [None])[0],
        "tldr": a.get("tldr"),
        "keyClaims": a.get("keyClaims", []),
        "hardWon": a.get("hardWon"),
        "grounded": a.get("grounded"),
        "relevance": e.get("relevance"),
        "priority": e.get("priority"),
        "notes": e.get("notes", []),
        "markdown": body,
        "highlights": highlights,
        "via": via(item),
    }


def via(item: dict) -> dict | None:
    """Who shared the item and where, from the first capture that says so (Slack captures carry recommendedBy, sourceRef and the poster's words as note)."""
    for c in item.get("captures", []):
        if c.get("recommendedBy") or c.get("sourceRef"):
            return {"by": c.get("recommendedBy"), "ref": c.get("sourceRef"), "note": c.get("note")}
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="render.py", description="Render the read-later library page from the template and the state dir; report whether it changed.")
    ap.add_argument("state_dir", metavar="STATE_DIR")
    args = ap.parse_args(argv)
    root = Path(args.state_dir).expanduser().resolve()
    qpath = root / "queue.json"
    if not qpath.exists():
        print(f"error: {qpath} missing. Run read-later-rank first.", file=sys.stderr)
        return 3
    queue = json.loads(qpath.read_text())
    items = [entry(root, e, b) for b in BUCKETS for e in queue.get("buckets", {}).get(b, [])]
    attention = [a for a in queue.get("attention", []) if isinstance(a, dict) and a.get("url")]
    topics = [t for t in queue.get("topics", []) if isinstance(t, dict) and t.get("label")]
    data = {"generatedAt": queue.get("generatedAt"), "items": items, "attention": attention, "topics": topics}

    template_path = root / "template.html" if (root / "template.html").exists() else SKILL_DIR / "assets" / "template.html"
    template = template_path.read_text()
    if "/*__DATA__*/" not in template:
        print(f"error: {template_path} has no /*__DATA__*/ placeholder", file=sys.stderr)
        return 2
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = template.replace("/*__DATA__*/", payload, 1)
    (root / "queue.html").write_text(page)

    # hash the data without the timestamp, plus the template, so an unchanged queue is unchanged and a redesign republishes
    digest = hashlib.sha256((json.dumps({**data, "generatedAt": None}, sort_keys=True, ensure_ascii=False) + template).encode()).hexdigest()
    dpath = root / "deliver.json"
    state = json.loads(dpath.read_text()) if dpath.exists() else {}
    changed = state.get("contentHash") != digest
    state["contentHash"] = digest
    dpath.write_text(json.dumps(state, indent=2) + "\n")
    print(json.dumps({"html": str(root / "queue.html"), "changed": changed, "artifactId": state.get("artifactId"), "items": len(items)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
