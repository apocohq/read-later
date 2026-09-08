# Design decisions (v0)

Status: direction for the first versions. Complements `product-brief.md`; where they differ, this file wins. Current progress and the step-by-step plan live in `walkthrough.md`.

## Three stages

| Stage | Question it answers | Where | Output |
|---|---|---|---|
| **Capture** | How does material get to the agent? | `extension/` today; a Slack sweep later | `inbox/<id>.json` |
| **Curate** | What is it, is it worth reading, and how does it rank? | `read-later-ingest`, `read-later-analyze`, `read-later-rank` | `items/<time>-<slug>/` (item.json with `analysis`, content.md), `topics.md`, `queue.json` |
| **Consume** | How is the result presented and acted on? | `read-later-deliver` (artifact), extension actions `done`/`remove`, `read-later-prune` | `queue.html` as one versioned artifact; `done/`, `archive/` |

Code ships as an Agent Skill installed from this repo. State lives on the agent under `~/work/read-later/`. Each stage reads and writes only files there, so stages can be run and tested independently.

## Capture

Two paths, both landing in `inbox/`. The extension is built; the Slack sweep is planned.

- **Slack sweep (planned).** On a schedule the agent reads recent history through the Slack MCP connection (acting as the principal) and writes one capture per link or document. Swept conversations include the principal's **own DM (messages to self)**, so sharing a link to yourself from any device is a capture. No ambient mode, no per-message turns.
- **Browser extension.** Chrome/Arc, one click. Ships URL, title, selection, and the **full rendered HTML** of the page, so authenticated and JavaScript-rendered pages work without the agent fetching anything. Transport: a DAM API key (`agents:operate`, bound to the agent) and the api-server's `files.upload` procedure, which drops the capture as `inbox/<id>.json` in the agent workspace. Chosen because Slack Enterprise blocks user-token apps and this needs no third-party service at all. The upload wakes a hibernated agent; a later DAM inbound-webhook feature could avoid that. See `extension/README.md`.

LinkedIn is out of scope for now.

## Curate

Steps: `ingest.py` (1 to 3), `analyze.mjs` (4), `rank.py` (5 to 7):

1. apply retractions: a `remove` event is a retraction, not a delete. Per canonical URL the last event in the batch decides, ordered by `capturedAt` — a remove drops the captures before it (they are never fetched or evaluated) and archives the item if it was already processed; a capture after it survives and nothing is archived. The extension cannot delete from the workspace itself: its key is upload-only, and once processed there is no inbox file to delete, only an item to archive;
2. canonicalize URL, dedup by the canonical `url` in existing `item.json` files (one item per canonical URL, captures appended);
3. acquire content, first source that succeeds: reader-view extraction (readability + markdownify, metadata via trafilatura) of the HTML the browser captured; server-side fetch + the same extraction; capturer-supplied plain text;
4. analyze in an ephemeral DAM Invocation holding only the model connection: TL;DR, key claims, content type, category, topics, hard-won and grounded (0-10 with reasons). Article-only, so it never goes stale; result schema-validated by the platform; article text is data, not prompt. Rubric in the skill, overrides and the topic vocabulary in the state dir;
5. relevance from **topic weights** in `topics.md` (the reader's interests, edited by hand or by the host agent from its memory), not from a per-article model judgment: when focus shifts, a few numbers change and the whole pool re-ranks for free;
6. exclude archived, not-an-article, and news older than 14 days;
7. priority = ½ relevance + ½ quality (mean of hard-won and grounded), −1 for long reads, +3 for must-read; three Read today, four Read next, the rest Later. Deterministic and explainable.

`items/<time>-<slug>/content.md` is text, tables and images with frontmatter (title, url, author, published, words). Every consumption surface, including future audio and e-ink, renders from this file.

## Consume

- **Artifact (the surface).** `queue.html` is rendered by code from `queue.json`, so regenerating it costs no model tokens. Published once to the DAM artifact library and updated in place when the content hash changes, so it keeps one link and a version history. Artifacts are static pages in a sandboxed iframe; DAM's agent-calling bridge for interactive artifacts is planned, not built, so the page does not call back.
- **Actions** come from the extension: **Mark as read** (`done`) and **Remove** (`remove` → archived), both plain inbox events. Weekly `prune` moves `done/` and `archive/` folders out of the pool.
- **Highlights** are made in the artifact's reader pane and anchored as W3C text quotes (exact, prefix, suffix) plus character offsets, so they re-attach to the article after any republish. Live state stays in the browser (localStorage per item) while reading; the agent receives one `highlight` or `done` event carrying the item's full current set, and ingest writes it to `items/<folder>/highlights.json`, which the renderer bakes back into the page. Every upload wakes the agent, so highlights travel in batches, not one by one. Transport today: the page copies the event JSON and the reader pastes it into chat. Later: the artifact bridge posts the same event, and the page could then push on every change, which makes highlights cross-device while reading. The agent side is the same under both.
- **Reader context** enters through topic weights only: `rank` reweighs them each run from the context sources named in `context.md`, or skips when the file says `NO CONTEXT AVAILABLE`.
- Later: highlights as a ranking signal (topics of highlighted items drift up more than plain done items), a reader view per item, audio rendition, e-ink.

## Runtime and cost

One DAM agent on the standard Claude Code image, with the skill installed from this repo and state under `~/work/read-later` (the subfolder scopes it so the same agent can host other tools). Connections: a model provider for evaluation; Slack once the sweep exists. One **daily** schedule runs sweep, process, and deliver in sequence; hourly is possible but costs a model turn per run plus per-item evaluation, and a read-later queue does not need it. Extraction and classification should use a cheap model; the expensive model only evaluates items that survive dedup.

No headless browser on the standard image (Chromium needs root-installed libraries). Revisit with a custom image if fetch fails on too many pages.

Unattended runs reach the network through the egress gateway; the `all` preset allows the fetch fallback and the first-run package download.

## Not yet

Web UI, cross-user items, team routing, preference learning, author following, audio, e-ink, internal reader.
