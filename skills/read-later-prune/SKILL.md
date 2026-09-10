---
name: read-later-prune
description: Weekly housekeeping for read-later. Moves finished items to done/ and dropped or stale items to archive/, then tidies the topic vocabulary in topics.md (weights for new labels, merges of near-duplicates). Use when asked to prune, clean up or tidy read-later, or on the weekly schedule.
compatibility: Python 3.11+, standard library only.
metadata:
  version: "0.1"
---

# Read Later · Prune

Keeps the live pool small and the vocabulary clean. Two parts: a script that moves folders by rule, and a short judgment pass over `topics.md` that only you can do.

## Available scripts

- **`scripts/prune.py`** — moves item folders out of `items/`. `--dry-run` to preview, `--max-age-days` to change the staleness rule (default 30).

## Run

From this skill's directory:

```bash
python3 scripts/prune.py ~/work/read-later
```

Rules, in order: status `done` → `done/`; status `archived` (the reader un-bookmarked it) → `archive/`; `contentType` `not-an-article` → `archive/`; unread for more than 30 days and not must-read → `archive/`. Prune deletes nothing; each move is logged to `feedback.jsonl`. Only a `delete` event through `read-later-ingest` removes a folder. `rank` reads only `items/`, so anything moved leaves the queue.

## Then tidy the vocabulary

Open `~/work/read-later/topics.md` and:

1. **Weigh new labels.** Labels the analyzer coined arrive without a number. Give each one a weight from what you know of the reader; if `~/work/read-later/context.md` is missing or says `NO CONTEXT AVAILABLE`, leave them unweighted (they count as 5) and list them in your report instead.
2. **Merge near-duplicates.** `coding-agents` next to `ai-agents`, `ci-cd` next to `testing`: keep the one with more items, delete the other, and replace it in every `items/*/item.json` that carries it. Do this with a small `sed` or `python3` one-liner, not by hand-editing thirty files.
3. **Delete noise.** A label used once for something the reader will never search for can go, from the file and the item.

Do not touch the `# Categories` list without the reader; changing a shelf changes what the analyzer may return.

## After the run

Report: what moved and why, one line each; which labels you weighed, merged or deleted. Stop there. Do not open articles, do not re-rank.

## Rules

- Never delete an item folder. `archive/` is the end of the line, and it stays unless the reader sends a `delete` event through `read-later-ingest`.
- `done/` is the reader's own record of what they valued; leave it alone.
