# Contract

## Inbox event — `inbox/<id>.json`

Written by producers (the Chrome extension, `read-later-slack`, the agent from chat), read only by `scripts/ingest.py`.

```json
{
  "id": "2026-09-07T06-12-31-482Z-k3f9a",
  "action": "capture",
  "source": "browser",
  "url": "https://example.com/post?utm_source=x",
  "title": "Page title",
  "selectedText": "text the user highlighted, if any",
  "html": "<html>… rendered DOM, scripts and styles stripped …",
  "note": "optional free text",
  "mustRead": false,
  "capturedAt": "2026-09-07T06:12:31.482Z"
}
```

| field | required | meaning |
|---|---|---|
| `id` | yes | unique, time-sortable, also the filename |
| `action` | no | `capture` (default); `remove` = retract earlier captures of this URL (drop if unprocessed, archive if processed); `done` = the reader finished it; `delete` = retract like `remove`, then remove the item folder for good (from `items/`, `done/` or `archive/`); a later capture starts a fresh item |
| `source` | yes | `browser`; `chat` (the agent, on the reader's word); `slack` (a link from a message the reader saved in Slack); other producers add their own value |
| `url` | yes | as seen; canonicalization happens here, not in the producer |
| `title` | no | page title |
| `selectedText`, `note` | no | the user's own signal why it matters |
| `html` | no | rendered DOM; makes paywalled and JS-rendered pages work. The extension drops what no extraction reads (scripts other than JSON-LD, styles, inline SVG, noscript, templates, style attributes) before sending. Omitted when the tab is not an HTML document (a PDF in the browser's viewer); ingest fetches the URL instead |
| `text` | no | readable text supplied by a producer that has no HTML |
| `mustRead` | no | hard override for later ranking; never filtered out |
| `recommendedBy` | no | who shared it and where, e.g. `Radek Ježek in #podcast-club`; shown on the library page |
| `sourceRef` | no | link back to where it was shared (a Slack permalink) |
| `capturedAt` | yes | ISO timestamp; orders capture vs remove |

Files that are not valid JSON or lack `url`/`capturedAt` are skipped with a message and left in place.

## Item — `items/<folder>/item.json`

The folder is `<first capture time>-<title slug>`, e.g. `2026-09-07T13-00-00Z-running-a-software-factory-efficiently-at-uber-scale`. Folders sort by capture time and read like a list of what you saved. Dedup is by the canonical `url` inside `item.json`; there is no index file.

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
| `status` | `captured` → `extracted` \| `failed` (adds `failure`, `attempts`, `failedAt`; ingest re-fetches up to 3 times, a day apart) → `analyzed` → `done` (adds `doneAt`) \| `archived` |
| | A new `capture` of a `done` item reopens it: status back to `analyzed` (or `extracted` if never analyzed), `doneAt` removed, a `reopen` line in `feedback.jsonl` |
| `mustRead` | true once any capture said so; never reset |
| `captures[]` | one per capture: `at`, `source`, and only the user's signals if present: `note`, `selectedText`, `recommendedBy`, `sourceRef` |
| `author`, `published` | when found. `published` is heuristic; treat as approximate. For a video or audio item, `author` is the channel or show |
| `words`, `images` | size of the extracted article; for a video or audio item, the size of its description. `images` is 0 for PDFs, whose figures are not extracted |
| `pages` | PDFs only: page count |
| `kind` | `video` or `audio`, only on media items (absent means article). From the page's own Open Graph type (`video.*`, `music.*`); JSON-LD (`VideoObject`, `PodcastEpisode`) counts only when the page declares no type and no article. The analyzer's `contentType` says whether an audio item is a `podcast` or a music track (`not-an-article`) |
| `durationSeconds`, `image` | play time and cover image, when the page declares them; media items only |
| `extractedBy` | `capture` (browser HTML), `fetch` (agent fetched the URL), `fetch-pdf` (agent fetched a PDF), `capture-text` (producer's text), `metadata` (video or podcast page: no article, only what the page declares) |
| `extractedAt` | when |

`read-later-analyze` adds `analysis` and sets `status: "analyzed"`:

```json
"analysis": {
  "version": "2", "at": "…", "template": "claude-code", "connection": "ibm-litellm",
  "tldr": "2-4 sentences stating the claim",
  "keyClaims": ["…", "…"],
  "contentType": "article",   // or paper, news, …, video, podcast, not-an-article
  "category": "ai-and-agents",
  "topics": ["agent-cost", "mcp", "subagents"],
  "hardWon":  { "score": 9, "reason": "one sentence" },
  "grounded": { "score": 8, "reason": "one sentence" }
}
```

A failed analysis leaves `status` unchanged and adds `analysisError: {at, message}`; the next run retries it.

## Highlights — `items/<folder>/highlights.json`

Produced by the library page (`read-later-deliver`), not by ingest. The page keeps the reader's highlights in the browser and, on **Copy for chat** or **Done reading**, puts this file's exact content on the clipboard; the reader pastes it to the agent, and the agent writes it verbatim to `items/<item>/highlights.json` (or under `done/` if prune already moved the folder). Later the artifact writes the file itself. Absent until the reader highlights something; every paste replaces the whole file, so adding or removing a highlight later is another paste.

```json
{
  "item": "2026-09-07T13-00-00Z-running-a-software-factory-efficiently-at-uber-scale",
  "url": "https://uber.com/us/en/blog/efficient-software-factory",
  "updatedAt": "2026-09-08T20:11:02.113Z",
  "highlights": [
    {
      "id": "h-k3f9a2",
      "exact": "70% of pull requests are merged within a day",
      "prefix": "we found that ",
      "suffix": ". The rest wait",
      "start": 14210,
      "end": 14254,
      "color": "yellow",
      "note": "compare with ours",
      "createdAt": "2026-09-08T20:03:11.000Z"
    }
  ]
}
```

| field | meaning |
|---|---|
| `item` | the folder the file belongs in |
| `url` | the item's canonical URL, a cross-check |
| `highlights[].id` | chosen by the page, stable for the life of the highlight |
| `exact`, `prefix`, `suffix` | the highlighted text and up to 32 characters around it: a W3C TextQuoteSelector, the anchor that survives re-rendering |
| `start`, `end` | character offsets into the rendered article text: a W3C TextPositionSelector, the fast path and the tiebreaker when `exact` occurs twice |
| `color` | optional, one of `yellow` (default), `green`, `blue`, `pink`, `orange` |
| `note` | optional, the reader's comment |
| `createdAt` | when the highlight was made |

`read-later-deliver` injects the file into the page, so highlights made on one device show on every device once the agent has the file. Marking the item read is separate: a `done` event through ingest, as from the extension or chat.

## Article — `items/<folder>/content.md`

Short frontmatter (`title`, `url`, `author`, `published`, when known), a blank line, then Markdown with headings, links, tables and images (absolute URLs). The full metadata lives in `item.json`. For a video or audio item the body is the publisher's description, which may be short or empty; there is no transcript.

For a PDF the Markdown comes from PyMuPDF's layout analysis: headings by level, paragraphs joined across lines and pages, tables as pipe tables, running heads and page numbers dropped, no images, no OCR (a scanned PDF fails with too few words). Title, author and date come from the PDF's landing page when the host has one (arXiv's abstract page, via `citation_*` meta tags), else from the first heading and the PDF's own metadata.

## Folders

`items/` is the live pool and the only folder `rank` reads. `read-later-prune` moves whole item folders to `done/` (status `done`) or `archive/` (status `archived`, `not-an-article`, or unread for 30 days and not must-read). Nothing is deleted by prune; only a `delete` event removes a folder, and it works in all three.

## Slack state — `slack/`

Written only by `read-later-slack/scripts/slack.py`.

- `state.json`: `{"me": {id, name}, "lastSweepAt": "…", "seen": {"<canonical url>": {"decision": "captured|skipped", "at": "…"}}}`. `seen` is the ledger of links already handled; entries expire after 90 days (`items/` still dedupes captured URLs).
- `skipped.json`: `[{url, title, reason, by, permalink, at}]`, links the fetch fallback cannot reach (login walls, social posts). `read-later-rank` lists them under `attention` with `kind: "slack"`.

## Reader context — `context.md`

Written at setup. Either names where the reader's context lives (files or notes the agent should read before reweighing topics), or contains the line `NO CONTEXT AVAILABLE`. When missing or marked, `rank` skips reweighing and `prune` leaves new labels unweighted.

## Vocabulary — `topics.md`

Two flat lists, seeded by `read-later-analyze` from its `references/topics.md`. `# Categories`: the shelves, one per item, hand-edited; also the analyzer's allowed values. `# Topics`: labels, `- label` or `- label: N` where N (0-10) is how much the reader cares now; unweighted counts as 5. The analyzer appends coined labels; `read-later-rank` reads the weights.

## Queue — `queue.json`

Written by `read-later-rank`; the only input `read-later-deliver` needs besides the items. Buckets `read_today`, `read_next`, `later`; each entry carries `item`, `title`, `url`, `priority`, `relevance`, `quality`, `minutes`, `tldr`, `category`, `topics`, `topTopic` (the heaviest-weighted topic, shown on the cover), `notes`. `attention` lists what the reader must look at: items whose fetch or analysis failed (`kind` `fetch` or `analysis`) and Slack links the sweep could not hand to ingest (`kind` `slack`, with `by`, `reason`, `sourceRef`). Generated files: change the weights or the script, not these. `attention` lists items the reader has to look at themselves, shown at the top of the library page: `{item, title, url, kind: "fetch" | "analysis", reason, attempts?, at}` for `failed` items and for items whose analysis keeps failing. `topics` lists the topics present in the queue as `{label, weight, count}`, ordered by the reader's weight (the page's filter chips).

## Delivery — `queue.html`, `deliver.json`

`read-later-deliver` renders `queue.html` from its template plus `queue.json` and the items, and keeps `deliver.json`: `{"renderedHash": "…", "publishedHash": "…", "artifactId": "…"}`. `renderedHash` is written by every render; `artifactId` and `publishedHash` by `render.py --published <id>` after a successful publish. A render whose hash equals `publishedHash` is not published again; a failed publish is retried next run.

## Log — `feedback.jsonl`

Append-only, one JSON object per line, e.g. `{"item": "<folder>", "action": "archive", "reason": "removed via browser", "at": "…"}`. Actions: `done`, `archive`, `reopen`, `delete` (ingest), `move:<folder>` (prune), `highlight` (the reader's paste). Nothing reads it yet; it is the audit trail and a future signal for the reweigh.
