# Design decisions (v0)

Status: skeleton. Complements `product-brief.md`; where they differ, this file wins. Informed by the 2026-09-04 read-later brainstorm (`strategy/meetings/2026-09-04-read-later-agent-brainstorm.md`).

## Three stages

| Stage | Question it answers | Code | Output |
|---|---|---|---|
| **Capture** | How does material get to the agent? | `src/capture/`, `extension/`, `.claude/skills/sweep-slack/` | `inbox/<id>.json` |
| **Curate** | What is it, is it worth reading, and how does it rank? | `src/curate/` | `items/<id>/` (item.json, content.md, analysis.*.json), `queue.json` |
| **Consume** | How is the result presented and acted on? | `src/consume/` | `queue.md` (Slack), `queue.html` (artifact) |

Each stage reads and writes only files in this repo, through `src/store/`. Stages can be run and tested independently.

## Capture

Two paths for the first version, both landing in `inbox/`:

- **Slack sweep.** On a schedule the agent reads recent history through the Slack MCP connection (acting as the principal) and writes one capture per link or document. Swept conversations include the principal's **own DM (messages to self)**, so sharing a link to yourself from any device is a capture. No ambient mode, no per-message turns.
- **Browser extension.** Chrome/Arc, one click. Ships URL, title, selection, and the **full rendered HTML** of the page, so authenticated and JavaScript-rendered pages work without the agent fetching anything. Transport: a DAM API key (`agents:operate`, bound to the agent) and the api-server's `files.upload` procedure, which drops the capture as `inbox/<id>.json` in the agent workspace. Chosen because Slack Enterprise blocks user-token apps and this needs no third-party service at all. The upload wakes a hibernated agent; a later DAM inbound-webhook feature could avoid that. See `extension/README.md`.

LinkedIn is out of scope for now.

## Curate

Deterministic steps in `src/curate/process.ts`:

1. apply retractions: a `remove` event is a retraction, not a delete. Per canonical URL the last event in the batch decides, ordered by `capturedAt` — a remove drops the captures before it (they are never fetched or evaluated) and archives the item if it was already processed; a capture after it survives and nothing is archived. The extension cannot delete from the workspace itself: its key is upload-only, and once processed there is no inbox file to delete, only an item to archive;
2. canonicalize URL, dedup against `index.json` (one item per canonical URL, captures appended);
3. acquire content, first source that succeeds: reader-view extraction (Defuddle) of the HTML the browser captured; server-side fetch + the same extraction; capturer-supplied plain text;
4. assemble context from providers (`profile.md` now; later the digital-traces agent's output file);
5. evaluate through a structured model call (`Evaluator`); article text is data, not prompt;
6. prune: archive filtered-out items immediately and unread items after 14 days, never must-reads;
7. rank with weighted 0-5 dimensions, penalty terms weighted so they cannot swamp the base, must-read as a hard boost; caps of one Read today and four Read next.

`items/<id>/content.md` is pure text and images with frontmatter (title, url, author, published, words). Every consumption surface, including future audio and e-ink, renders from this file.

## Consume

- **Slack DM (first surface).** The daily post is a short menu to choose from, not a verdict: Read today, Read next, with why-it-matters and confidence. Replies in the thread become feedback.
- **Artifact.** `queue.html` is rendered by code from the files, so regenerating it after every run costs no model tokens. Published to the DAM artifact library each run. DAM artifacts are static HTML/JSX rendered in a sandboxed iframe with a version history and live refresh on republish; there is no supported data channel into an already-published page, so a regenerated page is the right model.
- Later: a reader view per item, highlights, audio rendition, e-ink.

## Runtime and cost

One DAM agent on the standard Claude Code image; this repo lives at `~/work/read-later` (one `dam import` of the folder, or a clone once a remote exists); the subfolder scopes it so the same agent can host other tools. Connections: GitHub, Slack, Anthropic. One **daily** schedule runs sweep, process, and deliver in sequence; hourly is possible but costs a model turn per run plus per-item evaluation, and a read-later queue does not need it. Extraction and classification should use a cheap model; the expensive model only evaluates items that survive dedup.

No headless browser on the standard image (Chromium needs root-installed libraries). Revisit with a custom image if fetch fails on too many pages.

Open: whether unattended turns may fetch arbitrary hosts through the egress gateway. Until verified, extension text must be sufficient on its own.

## Slack sweep configuration

Conversations to sweep: _to be listed here_. Always include the principal's self-DM.

## Not yet

Web UI, cross-user items, team routing, preference learning, author following, audio, e-ink, internal reader.
