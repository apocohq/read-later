# Design decisions (v0)

Status: direction for the first versions. Complements `product-brief.md`; where they differ, this file wins. Current progress and the step-by-step plan live in `walkthrough.md`.

## Three stages

| Stage | Question it answers | Where | Output |
|---|---|---|---|
| **Capture** | How does material get to the agent? | `extension/` today; a Slack sweep later | `inbox/<id>.json` |
| **Curate** | What is it, is it worth reading, and how does it rank? | `read-later-ingest`, `read-later-analyze`, `read-later-rank` | `items/<time>-<slug>/` (item.json with `analysis`, content.md), `topics.md`, `queue.md`/`queue.json` |
| **Consume** | How is the result presented and acted on? | planned | `queue.md`, `queue.html` |

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
7. priority = ½ relevance + ½ quality (mean of hard-won and grounded), −1 for long reads, +3 for must-read; one Read today, four Read next, the rest Later. Deterministic and explainable.

`items/<time>-<slug>/content.md` is text, tables and images with frontmatter (title, url, author, published, words). Every consumption surface, including future audio and e-ink, renders from this file.

## Consume

- **Slack DM (first surface).** The daily post is a short menu to choose from, not a verdict: Read today, Read next, with why-it-matters and confidence. Replies in the thread become feedback.
- **Artifact.** `queue.html` is rendered by code from the files, so regenerating it after every run costs no model tokens. Published to the DAM artifact library each run. DAM artifacts are static HTML/JSX rendered in a sandboxed iframe with a version history and live refresh on republish; there is no supported data channel into an already-published page, so a regenerated page is the right model.
- Later: a reader view per item, highlights, audio rendition, e-ink.

## Runtime and cost

One DAM agent on the standard Claude Code image, with the skill installed from this repo and state under `~/work/read-later` (the subfolder scopes it so the same agent can host other tools). Connections: a model provider for evaluation; Slack once the sweep exists. One **daily** schedule runs sweep, process, and deliver in sequence; hourly is possible but costs a model turn per run plus per-item evaluation, and a read-later queue does not need it. Extraction and classification should use a cheap model; the expensive model only evaluates items that survive dedup.

No headless browser on the standard image (Chromium needs root-installed libraries). Revisit with a custom image if fetch fails on too many pages.

Unattended runs reach the network through the egress gateway; the `all` preset allows the fetch fallback and the first-run package download.

## Not yet

Web UI, cross-user items, team routing, preference learning, author following, audio, e-ink, internal reader.
