# Walkthrough

What works today, what is next. One step at a time, each step tested before the next.

## Step 1 · Chrome extension → agent file system  ✅ works

```
 Chrome                          DAM api-server                 Agent pod
┌──────────────────────┐  HTTPS   ┌──────────────────┐  writes  ┌───────────────────────────┐
│ page + selection     │ ───────▶ │ files.upload     │ ───────▶ │ ~/work/read-later/inbox/  │
│ extension builds     │  API key │ checks key scope │  wakes   │   <id>.json               │
│ one inbox event      │          │ refuses overwrite│  pod     │ (nothing reads it yet)    │
└──────────────────────┘          └──────────────────┘          └───────────────────────────┘
```

**The call** (`extension/src/dam-client.ts`)

```
POST <host>/api/trpc/files.upload
Authorization: Bearer pk_…          # scope agents:operate, bound to the one agent
{ agentId, path: "work/read-later/inbox/<id>.json", contentBase64, contentType: "application/json", overwrite: false }
```

**The file** (`extension/src/contract.ts`, schema in `src/domain/capture.ts`)

```json
{
  "id": "2026-09-07T06-12-31-482Z-k3f9a",   // unique, time-sortable, also the filename
  "action": "capture",                      // or "remove" = retract earlier capture of this url
  "source": "browser",
  "url": "https://…",                       // raw; the agent canonicalizes
  "title": "…",
  "selectedText": "…",                      // optional, what the user highlighted
  "html": "<!doctype html>…",               // full rendered DOM, so paywalled/JS pages work
  "note": "…",                              // optional
  "mustRead": false,
  "capturedAt": "2026-09-07T06:12:31.482Z"
}
```

Nothing flows back to the browser. The extension keeps its own local list of saved URLs for the icon state.

**Tested:** a bookmark in Chrome lands as a file in `~/work/read-later/inbox/` on the agent.

## Step 2 · Agent turns an inbox file into a clean article  ⏭ next

The code ships as an **Agent Skill** (`skills/read-later/`), installed onto agents from this repo. No code to copy per agent and no bundled libraries: the script declares its dependencies inline (PEP 723) and `uv run` installs them on first use. uv is in the DAM agent image.

```
skills/read-later/
  SKILL.md                 when to use it, how to run it, the rules
  scripts/ingest.py       inbox → items   (uv run scripts/ingest.py ~/work/read-later)
  references/contract.md   inbox event, item.json, content.md shapes
```

What `ingest.py` does per inbox file, in order:

1. **Canonicalize + dedupe** — strip fragment, `www.`, tracking params. Same page twice = one item. `remove` events handled first.
2. **Extract** — captured HTML → trafilatura → Markdown with title/author/date/word count. Fallback: fetch the URL. Fails visibly if neither yields ≥ 80 words.
3. **Save** — `items/<hash>/item.json` + `content.md`, drop the html, delete the inbox file.

Tested locally on a real 211 KB capture: 2682 words extracted, duplicate capture merged into one item, remove handled, non-JSON file skipped, rerun is a no-op.

**Test on the agent:**

1. Push this repo to GitHub, then `dam skill source add <repo url>` and `dam skill install <agent> --source <repo url> --name read-later`.
2. Bookmark a page in Chrome.
3. Ask the agent: *"process the read-later inbox"*. The first run downloads packages (~30 s). Expect one `extracted` line.
4. Ask it to show `~/work/read-later/items/*/content.md`. It should read like the article.

## Step 3 · Real evaluation  ⏸ later

A second script in the skill (`evaluate.py`) makes one structured model call per new item and appends the analysis to `item.json`. Then ranking and the queue become meaningful.

## Step 4 · Daily schedule + reading the queue  ⏸ later

A daily schedule runs the skill. Decide how the queue is read: a Markdown file, an artifact page, or a Slack message.

## Not in scope yet

Slack sweep, feedback loop, multi-user template, name change.
