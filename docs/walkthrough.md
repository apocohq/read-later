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

## Step 3 · Analyze: TL;DR, category, scores, recommendation  ⏭ next

Skill `read-later-analyze`. The judgment is subjective to the reader, so it is split in three layers:

| layer | what | where |
|---|---|---|
| rubric | what a TL;DR is, the category list, the 0-5 scales, the output schema | `skills/read-later-analyze/prompts/{tldr,categorize,evaluate}.md`; a copy in `~/work/read-later/prompts/` overrides |
| context | who the reader is, what they work on, what they know | `~/work/read-later/context.md`, written by the host agent (Guido) from its own memory; template in `references/context-template.md` |
| judgment | one model run per article | an ephemeral **DAM Invocation** with the model connection only, spawned by `scripts/analyze.mjs` via the platform's `dam-invoke` SDK |

Why an Invocation: the article never enters the agent's own session, and the evaluator has no Slack, GitHub or mail to act on injected instructions. The platform validates the result against a JSON Schema before it comes back. One pod per article; three run in parallel.

```
node scripts/analyze.mjs --connection ibm-litellm ~/work/read-later
```

Output lands in `item.json` as `analysis` (tldr, keyClaims, contentType, category, topics, scores, recommendation, whyItMatters, weaknesses, readingMinutes, confidence) and `status` becomes `analyzed`.

Tested locally against a stub SDK: prompt assembly, schema derived from the category list, merge into `item.json`, a failed Invocation recorded and retried on the next run, idempotent rerun.

**Test on the agent (Guido):**

1. `dam skill install guido --source <repo url> --name read-later-ingest` and the same with `--name read-later-analyze`.
2. Put the three test articles in Guido's inbox (extension pointed at Guido, or `dam file put`).
3. Ask Guido: *"ingest and analyze read later"*. First time it writes `context.md` from what it knows about you, then runs both scripts. Expect three `analyzed` lines with a recommendation each.
4. Check `items/*/item.json` → `analysis.tldr` and `whyItMatters` should name your context, not generic praise.

## Step 4 · Rank and deliver  ⏸ later

`read-later-rank`: order analyzed items, cap the buckets (one Read today, four Read next), prune. `read-later-deliver`: render the queue and hand it to the reader. Then a daily schedule runs ingest → analyze → rank → deliver.

## Not in scope yet

Slack sweep, feedback loop, multi-user template, name change.
