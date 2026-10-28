---
name: read-later-deliver
description: Publishes the read-later queue as one interactive artifact in the DAM artifact library, updating the same artifact each time the queue changes, and runs the small server the page saves highlights, Done, Archive and Delete to. Use after read-later-rank, when asked to publish or show the reading queue, on the daily schedule, when asked to start the read-later server, or when the reader pastes a "Read later highlights" JSON (highlights.json) or says they are done reading.
compatibility: DAM agent with the platform artifact tools (create_artifact, update_artifact) on its MCP endpoint and interactive artifacts (the reader turns on Interactive artifacts in DAM's settings). Python 3.11+, standard library only.
metadata:
  version: "0.2"
---

# Read Later · Deliver

Publishes the reader's library as one self-contained page in the artifact library: a shelf of book-like tiles (Tonight, Next, Later), each with its scores as bars. A tile carries category, topic and publisher in that order at the top, so the same fact sits at the same height on every tile, and a monochrome mark of the publisher (GitHub, YouTube, X, Spotify, Substack, Medium, LinkedIn, Hacker News, papers) or of the medium in the top right corner. Above the shelves, **Needs attention** lists what the reader must handle themselves, with one **Open all** button that opens every link in a tab: the fix is always to open the page and save it again with the extension; a click opens the TL;DR, claims, scores (reasons on click) and the full article text, with a highlighter. One artifact, one link, a new version each time the data changes. Nothing is published when nothing changed.

The page is `assets/template.html` (design) plus data injected by `scripts/render.py` from `queue.json` and the items' `item.json`, `content.md` and `highlights.json`. To restyle for one reader, copy the template to `~/work/read-later/template.html` and edit; the copy wins.

## Highlights

In the reader pane the reader turns the highlighter on (pen icon in the sticky header, with five colors), selects text, and gets a mark; clicking a mark adds a note, changes its color or removes it. The list of highlights sits below the article. The header also has **Done reading**, **Archive** (it leaves the queue, the folder stays) and **Delete** (the folder goes, for good; it asks for a second click).

The page has two modes:

- **Live**, in the preview beside the chat with this agent, when the [server](#server) answers. Every highlight edit saves to `items/<folder>/highlights.json` half a second later; Done, Archive and Delete change the item at once and the tile leaves the shelf. On load the page asks the server for the current state, so items finished or removed since the last publish are hidden and highlights from other browsers show. **Refresh** in the header sends the nightly refresh task to this chat; run it as the schedule would. When the template on the agent is newer than the one the page was rendered from (the skill was updated), the page says it is out of date and offers **Ask the agent to republish it**.
- **Chat paste**, anywhere else (the artifact library), or when the server does not answer. The page says so and offers **Retry** and **Ask the agent to start it**, which sends a prompt to this chat. Highlights live in the browser until **Copy for chat** or **Done reading** puts `highlights.json` on the clipboard, and Archive and Delete copy a one-line request. The reader pastes it into chat; see below.

### When the reader asks you to start the server

Run `python3 scripts/server.py --ensure ~/work/read-later` from this skill's directory and reply with one line: running, or the error and what it needs. See [Server](#server).

### When the reader says the page is out of date

Run this skill as usual (render, then update the artifact). The template changed, so the render reports `changed: true`. Reply with the link.

### When the reader pastes highlights

The paste reads "Read later highlights, replace `items/<folder>/highlights.json` with this file:" followed by one JSON object with `item`, `url`, `updatedAt` and `highlights`. Do exactly that, nothing more:

1. Check that `~/work/read-later/items/<item>/` exists. If prune already moved it, use `~/work/read-later/done/<item>/`. If neither exists, say so and stop.
2. Write the JSON verbatim to `highlights.json` in that folder, replacing the previous file. Do not edit, reorder or summarize it; the page produced it and reads it back.
3. Append one line to `~/work/read-later/feedback.jsonl`: `{"item": "<folder>", "action": "highlight", "reason": "<n> highlight(s) via paste", "at": "<now, ISO>"}`.
4. Reply with one line: how many highlights the file holds, e.g. "saved 4 highlights". They show in the library page after the next deliver. Do not inspect, dedupe or comment on the highlights themselves.

If the paste is "Read later, archive this article: <url>" (the page's **Archive** button; older pages say "remove this article from my list"), file a `remove` event the way `read-later-ingest` describes for chat and run its script; the item is archived and leaves the queue at the next deliver. If the paste is "Read later, delete this article for good: <url>" (the **Delete** button), file a `delete` event the same way; the script removes the item folder, including highlights. Do not delete anything by hand.

If the paste starts with "Read later, done reading, mark it as read: <url>", also mark the item read the way `read-later-ingest` describes for chat: one `done` event into the inbox, then run its script. Highlights first, then done.

## Available scripts

- **`scripts/render.py`** — writes `queue.html` and prints `{"html", "changed", "artifactId", "replaces", "items"}`. It records the data's hash in `deliver.json`, so `changed` is false when nothing in the queue, the items or their highlights changed since the last publish. It leaves out items that are done or archived, or whose folder is gone, since rank wrote the queue.
- **`scripts/server.py`** — the page's server; see [Server](#server).

## Run

From this skill's directory:

```bash
python3 scripts/render.py ~/work/read-later
```

Then, based on the printed JSON:

- `changed: false` → say "queue unchanged, artifact not republished" and stop.
- `changed: true` and `artifactId: null` → first publish. Call `create_artifact` with the file's content, title `Read later`, file name `queue.html`, kind HTML, visibility private, **`interactive: true`**. Keep the id; the reader's link depends on it. Only create can make an artifact interactive, so when `replaces` names an older artifact id, this is a new artifact with a new link: tell the reader once that they can delete the old `Read later` artifact (`replaces`).
- `changed: true` and an `artifactId` → call `update_artifact` with that id and the new content. Same link, new version.
- After a successful create or update, run `python3 scripts/render.py --published <artifact id> ~/work/read-later`. That records the id and marks this render as published; without it the next run publishes again. If the publish failed, do not run it: the next run retries.
- Then, whatever `changed` said, run `python3 scripts/server.py --ensure ~/work/read-later`. It does nothing when the server already runs.

Do not read `queue.html` into your context; it is a few KB of generated HTML. Either pass its content to the tool directly, or use `create_artifact_upload_url` and `curl -sS -X PUT -H 'Content-Type: text/html; charset=utf-8' --data-binary @queue.html '<url>'`, then pass the `upload_ref`. Never create a second artifact for the queue: if `update_artifact` fails because the artifact is gone, say so and ask before creating a new one.

## Server

`scripts/server.py` is a small HTTP server (standard library) on `127.0.0.1:5555`, the one port DAM relays the page's `platform.request` calls to. DAM lets only this agent's own interactive artifact reach it, and the server checks every input. It reads and writes only inside the state dir:

| call | does |
|---|---|
| `GET /health` | version and pid |
| `GET /items` | status and highlights of every folder in `items/`, and the hash of the current template |
| `PUT /items/<folder>/highlights` | replaces `highlights.json` with the page's file (only the known fields are kept) |
| `PATCH /items/<folder>` `{"status": "done" \| "archived"}` | the same change as ingest's `done` and `remove` events |
| `DELETE /items/<folder>` | removes the folder from `items/`, `done/` or `archive/`, like a `delete` event |

Each change appends a line to `feedback.jsonl` (`via page`); highlights only when their count changes.

`python3 scripts/server.py --ensure ~/work/read-later` starts it in the background unless the current version already answers, and prints `{"running": true, ...}`. After a skill update it stops the old version and starts the new one. It starts the server with `platform-keep`, so DAM lists it in the Processes panel and keeps it running; the log is `~/work/read-later/server.log`. A `SessionStart` hook in `~/work/.claude/settings.json` runs `--ensure` whenever a session starts, so a chat or a schedule tick brings the server back after a restart (INSTALL.md, Start-up hook).

When the server will not start: read the end of `server.log`. "cannot listen on 127.0.0.1:5555" means another program has the port: find it (`ss -ltnp | grep 5555` or `lsof -i :5555`), and stop it only if it is an older read-later server; otherwise report it. Any other error: report it with the last log lines. Never bind another address or port; DAM relays only to this one.

## After the run

Reply with the internal link as a markdown link (`[Read later](platform://artifacts/<id>)`) so the chat shows a preview chip, plus one line: the Read today title. Nothing else. Do not paste the queue into the chat and do not open articles.

## Rules

- `queue.html` and `deliver.json` are generated; fix the template, the renderer or the ranking, never the files.
- Marking something read, archiving or deleting it happens in the live page, through the Chrome extension ("Mark as read", "Archive in Read Later", "Delete from Read Later"), by telling the agent, or by pasting the page's **Done reading**, **Archive** or **Delete** message into chat.
- `highlights.json` is written only by the server (from the page) or from a paste, verbatim. Never compose or edit one yourself.
- Do not edit `server.py`'s routes to do more for the page; it is the whole surface the page can reach.
