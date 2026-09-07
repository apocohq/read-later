# Contract

## Inbox event — `inbox/<id>.json`

Written by producers (today: the Chrome extension), read only by `scripts/ingest.py`.

```json
{
  "id": "2026-09-07T06-12-31-482Z-k3f9a",
  "action": "capture",
  "source": "browser",
  "url": "https://example.com/post?utm_source=x",
  "title": "Page title",
  "selectedText": "text the user highlighted, if any",
  "html": "<!doctype html>… full rendered DOM …",
  "note": "optional free text",
  "mustRead": false,
  "capturedAt": "2026-09-07T06:12:31.482Z"
}
```

| field | required | meaning |
|---|---|---|
| `id` | yes | unique, time-sortable, also the filename |
| `action` | no | `capture` (default) or `remove` = retract earlier captures of this URL |
| `source` | yes | `browser`; other producers may add their own value |
| `url` | yes | as seen; canonicalization happens here, not in the producer |
| `title` | no | page title |
| `selectedText`, `note` | no | the user's own signal why it matters |
| `html` | no | full rendered DOM; makes paywalled and JS-rendered pages work |
| `text` | no | readable text supplied by a producer that has no HTML |
| `mustRead` | no | hard override for later ranking; never filtered out |
| `capturedAt` | yes | ISO timestamp; orders capture vs remove |

Files that are not valid JSON or lack `url`/`capturedAt` are skipped with a message and left in place.

## Item — `items/<id>/item.json`

`id` is the first 12 hex chars of SHA-256 of the canonical URL, so one page always maps to one folder.

```json
{
  "id": "3f9a1c7e2b04",
  "canonicalUrl": "https://example.com/post",
  "status": "extracted",
  "captures": [ { "...the inbox event without html..." } ],
  "content": { "title": "…", "author": "…", "published": "…", "wordCount": 1234, "extractedBy": "capture", "extractedAt": "…" },
  "createdAt": "…",
  "updatedAt": "…"
}
```

`status`: `captured` → `extracted` | `failed` (with `failure` reason) → `archived`.

## Article — `items/<id>/content.md`

YAML-ish frontmatter (same keys as `content` above plus `url`), a blank line, then Markdown.

## Index and log

- `index.json`: canonical URL → item id.
- `feedback.jsonl`: append-only, one JSON object per line, e.g. `{"itemId","action":"archive","reason","createdAt"}`.
