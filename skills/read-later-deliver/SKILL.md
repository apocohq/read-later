---
name: read-later-deliver
description: Publishes the read-later queue as one artifact in the DAM artifact library, updating the same artifact each time the queue changes. Use after read-later-rank, when asked to publish or show the reading queue, or on the daily schedule.
compatibility: DAM agent with the platform artifact tools (create_artifact, update_artifact) on its MCP endpoint. Python 3.11+ for the renderer.
metadata:
  version: "0.1"
---

# Read Later · Deliver

Turns `queue.json` into a single self-contained page and publishes it to the artifact library. One artifact, one link, a new version each time the queue changes. Nothing is published when nothing changed.

## Available scripts

- **`scripts/render.py`** — writes `queue.html` and prints `{"html", "changed", "artifactId"}`. It records the page's content hash in `deliver.json`, so `changed` is false when the queue is the same as the last publish.

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

- `queue.html` and `deliver.json` are generated; fix the renderer or the ranking, never the files.
- The artifact is a static page. Marking something read or removing it happens through the Chrome extension ("Mark as read", "Remove from Read Later") or by telling the agent; the page cannot call back.
