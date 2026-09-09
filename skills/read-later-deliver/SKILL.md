---
name: read-later-deliver
description: Publishes the read-later queue as one artifact in the DAM artifact library, updating the same artifact each time the queue changes, and stores highlights the reader pastes from that page. Use after read-later-rank, when asked to publish or show the reading queue, on the daily schedule, or when the reader pastes a "Read later highlights" JSON (highlights.json) or says they are done reading.
compatibility: DAM agent with the platform artifact tools (create_artifact, update_artifact) on its MCP endpoint. Python 3.11+ for the renderer.
metadata:
  version: "0.1"
---

# Read Later · Deliver

Publishes the reader's library as one self-contained page in the artifact library: a shelf of book-like tiles (Tonight, Next, Later), each with its scores as bars; a click opens the TL;DR, claims, score reasons and the full article text, with a highlighter. One artifact, one link, a new version each time the data changes. Nothing is published when nothing changed.

The page is `assets/template.html` (design) plus data injected by `scripts/render.py` from `queue.json` and the items' `item.json`, `content.md` and `highlights.json`. To restyle for one reader, copy the template to `~/work/read-later/template.html` and edit; the copy wins.

## Highlights

In the reader pane the reader turns the highlighter on, selects text, and gets a mark; clicking a mark adds a note or removes it. Highlights live in the reader's browser (localStorage per item, or only in memory in DAM's sandboxed viewer, which the page says) until **Copy for chat** or **Done reading** puts the content of `highlights.json` on the clipboard and the reader pastes it into chat. The renderer injects that file back into the page, so after the next publish the highlights show in every browser; marks not yet sent are underlined and counted as "unsent". The page cannot write to the agent yet; when DAM's artifact bridge ships, the artifact will write the file itself.

### When the reader pastes highlights

The paste reads "Read later highlights, replace `items/<folder>/highlights.json` with this file:" followed by one JSON object with `item`, `url`, `updatedAt` and `highlights`. Do exactly that, nothing more:

1. Check that `~/work/read-later/items/<item>/` exists. If prune already moved it, use `~/work/read-later/done/<item>/`. If neither exists, say so and stop.
2. Write the JSON verbatim to `highlights.json` in that folder, replacing the previous file. Do not edit, reorder or summarize it; the page produced it and reads it back.
3. Append one line to `~/work/read-later/feedback.jsonl`: `{"item": "<folder>", "action": "highlight", "reason": "<n> highlight(s) via paste", "at": "<now, ISO>"}`.
4. Reply with one line: how many highlights the file holds, e.g. "saved 4 highlights". They show in the library page after the next deliver. Do not inspect, dedupe or comment on the highlights themselves.

If the paste starts with "Read later, done reading, mark it as read: <url>", also mark the item read the way `read-later-ingest` describes for chat: one `done` event into the inbox, then run its script. Highlights first, then done.

## Available scripts

- **`scripts/render.py`** — writes `queue.html` and prints `{"html", "changed", "artifactId", "items"}`. It records the data's hash in `deliver.json`, so `changed` is false when nothing in the queue, the items or their highlights changed since the last publish.

## Run

From this skill's directory:

```bash
python3 scripts/render.py ~/work/read-later
```

Then, based on the printed JSON:

- `changed: false` → say "queue unchanged, artifact not republished" and stop.
- `changed: true` and `artifactId: null` → first publish. Call `create_artifact` with the file's content, title `Read later`, file name `queue.html`, kind HTML, visibility private. Write the returned artifact id into `~/work/read-later/deliver.json` as `"artifactId"` (keep the existing `contentHash` key). Keep the id; the reader's link depends on it.
- `changed: true` and an `artifactId` → call `update_artifact` with that id and the new content. Same link, new version.

Do not read `queue.html` into your context; it is a few KB of generated HTML. Either pass its content to the tool directly, or use `create_artifact_upload_url` and `curl -sS -X PUT -H 'Content-Type: text/html; charset=utf-8' --data-binary @queue.html '<url>'`, then pass the `upload_ref`. Never create a second artifact for the queue: if `update_artifact` fails because the artifact is gone, say so and ask before creating a new one.

## After the run

Reply with the internal link as a markdown link (`[Read later](platform://artifacts/<id>)`) so the chat shows a preview chip, plus one line: the Read today title. Nothing else. Do not paste the queue into the chat and do not open articles.

## Rules

- `queue.html` and `deliver.json` are generated; fix the template, the renderer or the ranking, never the files.
- The artifact is a static page; it cannot call the agent. Marking something read or removing it happens through the Chrome extension ("Mark as read", "Remove from Read Later"), by telling the agent, or by pasting the page's **Done reading** message into chat. Highlights reach the agent only through that paste.
- `highlights.json` is written only from a paste, verbatim. Never compose or edit one yourself.
