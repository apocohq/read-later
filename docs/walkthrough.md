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

## Step 2 · Agent turns an inbox file into a clean article  ✅ works

The code ships as an **Agent Skill** (`skills/read-later-ingest/`), installed onto agents from this repo. No code to copy per agent and no bundled libraries: the script declares its dependencies inline (PEP 723) and `uv run` installs them on first use. uv is in the DAM agent image.

```
skills/read-later-ingest/
  SKILL.md                 when to use it, how to run it, the rules
  scripts/ingest.py       inbox → items   (uv run scripts/ingest.py ~/work/read-later)
  references/contract.md   inbox event, item.json, content.md shapes
```

What `ingest.py` does per inbox file, in order:

1. **Canonicalize + dedupe** — strip fragment, `www.`, tracking params. Same page twice = one item. `remove` events handled first.
2. **Extract** — captured HTML → readability → Markdown with images and tables; title/author/date via trafilatura. Fallback: fetch the URL. Fails visibly if neither yields ≥ 80 words.
3. **Save** — `items/<time>-<slug>/item.json` + `content.md`, drop the html, delete the inbox file.

Tested locally on a real 211 KB capture: 2682 words extracted, duplicate capture merged into one item, remove handled, non-JSON file skipped, rerun is a no-op.

**Tested on the agent:** installed via `dam skill source add <repo url>` + `dam skill install <agent> --source <repo url> --name read-later-ingest`; bookmarks in Chrome became items with images, author and date; removes and duplicates accounted for; the agent reports the script output and stops.

## Step 3 · Analyze: TL;DR, category, topics, two scores  ⏭ testing

Skill `read-later-analyze`. Decided in the grilling of 2026-09-07:

- Analysis describes the **article only**, never the reader, so it runs once and never goes stale. Seven fields: `tldr` (2-4 sentences stating the claim), `keyClaims` (1-3), `contentType`, `category` (one shelf from a hand-edited list), `topics` (2-5 labels from a shared vocabulary, new ones coined only when the main subject has no match), `hardWon` and `grounded` (0-10 with a one-sentence reason, anchors at 0/5/10).
- The reader's interests live in **`~/work/read-later/topics.md`** as weights on topics, not in a context file. Categories and topics are orthogonal: shelf vs labels.
- The judgment runs in an **ephemeral DAM Invocation** per article with the model connection only, spawned by `scripts/analyze.mjs` through the platform's `dam-invoke` SDK; the platform validates the result against a JSON Schema derived from the category list. Article text never enters the agent's session, and the evaluator has nothing to exfiltrate to.
- Rubric in `prompts/{tldr,categorize,score}.md`; a copy in `~/work/read-later/prompts/` overrides.

```
node scripts/analyze.mjs --connection ibm-litellm ~/work/read-later
```

## Step 4 · Rank: tonight's queue  ⏭ testing

Skill `read-later-rank`, `scripts/rank.py`, standard library only, no model. Per item: relevance = mean of the two highest topic weights among its topics; quality = mean of hard-won and grounded; priority = half of each, −1 for over 4000 words, +3 for must-read. Excludes archived, unanalyzed, not-an-article, and news older than 14 days. Top item = Read today, next four = Read next, rest = Later. Writes `queue.md` and `queue.json`. Changing a weight in `topics.md` and rerunning is the feedback loop.

Tested locally on the three test articles with a stub SDK: ingest → analyze (one injected failure, retried next run, coined topics appended to `topics.md`) → rank; raising `code-review` to 10 lifted the Fowler piece from third to second (its quality scores still keep it below the Uber piece).

**Test on first-reader:** skills installed, `ibm-litellm` granted, the three articles in the inbox; a temporary schedule triggers *"ingest, analyze and rank read later"*; verify via session transcript, `item.json` and `queue.md`.

## Step 5 · Deliver + daily schedule  ⏸ later

`read-later-deliver`: hand the queue to the reader (Slack message, artifact page). Then one daily schedule runs ingest → analyze → rank → deliver.

## Not in scope yet

Slack sweep, feedback from reading (mark read, useful/not), multi-user template, name change.
