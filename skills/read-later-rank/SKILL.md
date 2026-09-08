---
name: read-later-rank
description: Reweighs the reader's topic interests from their context, then ranks analyzed read-later items into tonight's queue (one Read today, a few Read next, the rest Later) from topic weights and article scores. Use when asked what to read, to build or refresh the read-later queue, or after read-later-analyze has run.
compatibility: Python 3.11+, standard library only.
metadata:
  version: "0.1"
---

# Read Later · Rank

Turns analyzed items into a short queue. Relevance comes from the reader's **topic weights** in `~/work/read-later/topics.md`; quality comes from the article's `hardWon` and `grounded` scores. Arithmetic only, so it is cheap to rerun nightly and every placement is explainable.

## Available scripts

- **`scripts/rank.py`** — writes `queue.json` (order, buckets, priority, relevance) into the state dir and prints a short text view. `--help` for flags, `--json` to print the JSON instead.

## Run

From this skill's directory:

```bash
python3 scripts/rank.py ~/work/read-later
```

Per item: `relevance` = mean of the two highest topic weights among its topics (unweighted topics count 5); `quality` = mean of hard-won and grounded; `priority` = half of each, minus 1 for articles over 4000 words, plus 3 for must-read. Excluded: archived, unanalyzed, `not-an-article`, and news or announcements older than 14 days. Top item is **Read today**, the next four **Read next**, the rest **Later**.

## Before ranking: reweigh the topics

The reader's interests are the weights in `~/work/read-later/topics.md` (`- agent-cost: 9`, 0-10, how much they care right now). This is the one place the reader's context enters the system, and it is your judgment, not a script's. Every run:

1. Read `~/work/read-later/context.md`. It says where the reader's context lives (which files or notes to read) or contains the line `NO CONTEXT AVAILABLE`. If the file is missing or carries that marker, skip reweighing entirely: leave the numbers as they are, say so in one line, and go straight to ranking.
2. Otherwise read the context sources it names, then adjust weights: raise topics tied to what the reader is working on or deciding now, lower topics they have parked, and give a number to labels that have none. Change only what the context supports; a weight is a claim about the reader, not a guess. Do not ask the reader to grade thirty labels.
3. Never delete a label that items still carry; that is `read-later-prune`'s job.

Then run the script.

## After the run

Report: which weights you changed and why (one line each, or "no context, weights unchanged"), then the queue as the script printed it: the Read today item with its TL;DR and why it ranked first, the Read next titles in one line each, and the count in Later. Do not open articles, do not re-summarize, do not override the order by hand.

## Rules

- `queue.json` is generated; fix the weights or the script, never the file.
- The scores in `item.json` are the analyzer's; rank does not rewrite them.
