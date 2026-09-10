# Design decisions (v0)

Status: direction for the first versions. Complements `product-brief.md`; where they differ, this file wins. Current progress and the step-by-step plan live in `walkthrough.md`.

## Three stages

| Stage | Question it answers | Where | Output |
|---|---|---|---|
| **Capture** | How does material get to the agent? | `extension/`, `read-later-slack` | `inbox/<id>.json` |
| **Curate** | What is it, is it worth reading, and how does it rank? | `read-later-ingest`, `read-later-analyze`, `read-later-rank` | `items/<time>-<slug>/` (item.json with `analysis`, content.md), `topics.md`, `queue.json` |
| **Consume** | How is the result presented and acted on? | `read-later-deliver` (artifact), extension actions `done`/`remove`, `read-later-prune` | `queue.html` as one versioned artifact; `done/`, `archive/` |

Code ships as an Agent Skill installed from this repo. State lives on the agent under `~/work/read-later/`. Each stage reads and writes only files there, so stages can be run and tested independently.

## Capture

Two paths, both landing in `inbox/`.

- **Slack (`read-later-slack`).** Slack's own **Save for later** is the capture button. Once a day, inside the refresh, a script searches `is:saved has:link` as the principal through the Slack MCP server (the egress gateway injects the connection's token, so the script calls `mcp.slack.com` directly and no message text enters the agent's context) and writes one event per new link in a saved message, with `recommendedBy` (who posted it where), `sourceRef` (the permalink) and the poster's words as `note`. Nothing else in Slack is read and nothing is judged: saving is the reader's explicit action, like a click on the extension. Noise (permalinks, meetings, tickets, images) is dropped; links behind logins or on social sites are not captured and the library page lists them under *Needs attention*. The script has a two-tool read-only allowlist and never writes to Slack. Tried and dropped (2026-09-09): sweeping every shared link with the agent judging a shortlist; it worked, but the result was too noisy for a personal queue. Not built: a Slack message action (needs an inbound endpoint DAM does not have) and enrichment of media links (the media work covers that).
- **Browser extension.** Chrome/Arc, one click. Ships URL, title, selection, and the **rendered HTML** of the page (minus scripts, styles and inline SVG, which no extraction reads), so authenticated and JavaScript-rendered pages work without the agent fetching anything. Transport: a DAM API key (`agents:operate`, bound to the agent) and the api-server's `files.upload` procedure, which drops the capture as `inbox/<id>.json` in the agent workspace. Chosen because Slack Enterprise blocks user-token apps and this needs no third-party service at all. The upload wakes a hibernated agent; a later DAM inbound-webhook feature could avoid that. See `extension/README.md`.

LinkedIn is out of scope for now.

## Curate

Steps: `ingest.py` (1 to 3), `analyze.mjs` (4), `rank.py` (5 to 7):

1. apply retractions: a `remove` event is a retraction, not a delete; a `delete` event is both, and removes the item folder wherever prune left it. Per canonical URL the last event in the batch decides, ordered by `capturedAt` — a remove drops the captures before it (they are never fetched or evaluated) and archives the item if it was already processed; a capture after it survives and nothing is archived. The extension cannot delete from the workspace itself: its key is upload-only, and once processed there is no inbox file to delete, only an item to archive;
2. canonicalize URL, dedup by the canonical `url` in existing `item.json` files (one item per canonical URL, captures appended);
3. acquire content, first source that succeeds: reader-view extraction (readability + markdownify, metadata via trafilatura) of the HTML the browser captured; server-side fetch + the same extraction, or PyMuPDF layout → Markdown when the fetch returns a PDF (deterministic, no OCR; arXiv metadata from the abstract page); capturer-supplied plain text;
4. analyze in an ephemeral DAM Invocation holding only the model connection: TL;DR, key claims, content type, category, topics, hard-won and grounded (0-10 with reasons). Article-only, so it never goes stale; result schema-validated by the platform; article text is data, not prompt. Rubric in the skill, overrides and the topic vocabulary in the state dir;
5. relevance from **topic weights** in `topics.md` (the reader's interests, edited by hand or by the host agent from its memory), not from a per-article model judgment: when focus shifts, a few numbers change and the whole pool re-ranks for free;
6. exclude archived, not-an-article, and news older than 14 days;
7. priority = ½ relevance + ½ quality (mean of hard-won and grounded), −1 for long reads, +3 for must-read; three Read today, four Read next, the rest Later. Deterministic and explainable.

`items/<time>-<slug>/content.md` is text, tables and images with frontmatter (title, url, author, published, words). Every consumption surface, including future audio and e-ink, renders from this file.

## Consume

- **Artifact (the surface).** `queue.html` is rendered by code from `queue.json`, so regenerating it costs no model tokens. Published once to the DAM artifact library and updated in place when the content hash changes, so it keeps one link and a version history. Artifacts are static pages in a sandboxed iframe; DAM's agent-calling bridge for interactive artifacts is planned, not built, so the page does not call back.
- **Actions** come from the extension: **Mark as read** (`done`), **Archive** (`remove` → archived) and **Delete** (`delete` → folder removed), all plain inbox events. Weekly `prune` moves `done/` and `archive/` folders out of the pool.
- **Highlights** are made in the artifact's reader pane and anchored as W3C text quotes (exact, prefix, suffix) plus character offsets, so they re-attach to the article after any republish. Live state stays in the browser while reading (localStorage per item where available; DAM's artifact viewer renders the page as an `about:srcdoc` frame with an opaque origin, where Storage and History throw, so there the highlights live in memory only as long as the page is open and the page says so); the page produces the whole `items/<folder>/highlights.json` (the item's full current set) and the agent copies it into the folder verbatim, no ingest involved; the renderer bakes it back into the page. Transport today: the page copies the file to the clipboard and the reader pastes it into chat. Later: the artifact writes the file itself, on every change, which makes highlights cross-device while reading. Read state stays separate: **Done reading** adds one line and the agent files the usual `done` event.
- **Reader context** enters through topic weights only: `rank` reweighs them each run from the context sources named in `context.md`, or skips when the file says `NO CONTEXT AVAILABLE`.
- Later: a reader view per item, audio rendition, e-ink.

## Runtime and cost

One DAM agent on the standard Claude Code image, with the skill installed from this repo and state under `~/work/read-later` (the subfolder scopes it so the same agent can host other tools). Connections: a model provider for evaluation; Slack for the sweep. One **daily** schedule runs sweep, process, and deliver in sequence; hourly is possible but costs a model turn per run plus per-item evaluation, and a read-later queue does not need it. Extraction and classification should use a cheap model; the expensive model only evaluates items that survive dedup.

No headless browser on the standard image (Chromium needs root-installed libraries). Revisit with a custom image if fetch fails on too many pages.

Unattended runs reach the network through the egress gateway; the `all` preset allows the fetch fallback and the first-run package download.

## Not yet

Web UI, cross-user items, team routing, preference learning, author following, audio, e-ink, internal reader.

## PDF extraction: library choice

Measured 2026-09-09 on two arXiv papers: the single-column ACMM report (28 pages, 3 tables) and the two-column BERT paper (16 pages, tables). "Install" is the uv environment on macOS; ML tools also download models on first run. All runs offline after install, no OCR.

| library | install | ACMM / BERT time | headings | tables | two columns | licence | verdict |
|---|---|---|---|---|---|---|---|
| **pymupdf4llm** 1.28 (PyMuPDF + layout model) | 230 MB | 2.7 s / 3.0 s | full hierarchy (h1–h3) | all found, `<br>` in wrapped cells | correct order | AGPL | **chosen** |
| docling 2 (IBM) | 1.2 GB + models | 125 s first run, 8 s after | all flattened to `##` | best: every cell right | correct order | MIT | fallback if AGPL is a problem |
| marker 1 | 1.1 GB + models | 68 s first run, 3.6 s after | levels wobble, HTML anchors leak in | good, some cells split | correct order | GPL-3 + non-commercial model weights | no |
| unstructured (fast) | ~1 GB | slow install | 392 "titles" | none, columns transposed | broken | Apache-2 | no (hi_res needs models) |
| markitdown (pdfminer) | 150 MB | 1 s | none | none (dashes miscounted) | interleaved, spaces lost | MIT | no |
| pdfplumber | 44 MB | 1.2 s | none | found, rows as text | interleaved | MIT | no |
| kreuzberg | 80 MB | 0.4 s | none | none | ok | MIT | no |
| pdftotext -layout (poppler) | system | 0.1 s | none | whitespace-aligned only | ok | GPL | no |

pymupdf4llm is the only small, fast option that keeps the heading hierarchy and reading order and emits real pipe tables; its layout step is a bundled ONNX classifier, deterministic and offline. Docling produces the cleanest tables but costs a gigabyte-class install, a two-minute first run and flat headings. Revisit if the agent image ever ships torch anyway, or if AGPL matters.
