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

## Item — `items/<folder>/item.json`

The folder is `<first capture time>-<title slug>`, e.g. `2026-09-07T13-00-00Z-running-a-software-factory-efficiently-at-uber-scale`. Folders sort by capture time and read like a list of what you saved. Dedup does not depend on the name: `index.json` maps canonical URL → folder.

```json
{
  "url": "https://uber.com/us/en/blog/efficient-software-factory",
  "title": "Running a Software Factory Efficiently at Uber Scale",
  "status": "extracted",
  "mustRead": false,
  "captures": [
    { "at": "2026-09-07T13:00:00.000Z", "source": "browser", "selectedText": "70% of pull requests" },
    { "at": "2026-09-07T13:03:00.000Z", "source": "browser", "note": "second time" }
  ],
  "author": "…",
  "published": "2026-09-02",
  "words": 3465,
  "images": 8,
  "extractedBy": "capture",
  "extractedAt": "2026-09-07T13:37:31.336Z"
}
```

| field | meaning |
|---|---|
| `url` | canonical URL, the item's identity |
| `title` | from extraction, else from the capture |
| `status` | `captured` → `extracted` \| `failed` (adds `failure`) → `archived` |
| `mustRead` | true once any capture said so; never reset |
| `captures[]` | one per capture: `at`, `source`, and only the user's signals if present: `note`, `selectedText`, `recommendedBy`, `sourceRef` |
| `author`, `published` | when found. `published` is heuristic; treat as approximate |
| `words`, `images` | size of the extracted article |
| `extractedBy` | `capture` (browser HTML), `fetch` (agent fetched the URL), `capture-text` (producer's text) |
| `extractedAt` | when |

Later skills add their own top-level keys (e.g. `analysis`).

## Article — `items/<folder>/content.md`

Short frontmatter (`title`, `url`, `author`, `published`, when known), a blank line, then Markdown with headings, links, tables and images (absolute URLs). The full metadata lives in `item.json`.

## Index and log

- `index.json`: canonical URL → item folder.
- `feedback.jsonl`: append-only, one JSON object per line, e.g. `{"item": "<folder>", "action": "archive", "reason": "removed via browser", "at": "…"}`.
