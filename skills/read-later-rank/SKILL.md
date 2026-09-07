---
name: read-later-rank
description: Ranks analyzed read-later items into tonight's reading queue (one Read today, a few Read next, the rest Later) from topic weights and article scores. Deterministic, no model call. Use when asked what to read, to build or refresh the read-later queue, or after read-later-analyze has run.
compatibility: Python 3.11+, standard library only.
metadata:
  version: "0.1"
---

# Read Later · Rank

Turns analyzed items into a short queue. Relevance comes from the reader's **topic weights** in `~/work/read-later/topics.md`; quality comes from the article's `hardWon` and `grounded` scores. Arithmetic only, so it is cheap to rerun nightly and every placement is explainable.

## Available scripts

- **`scripts/rank.py`** — writes `queue.md` and `queue.json` into the state dir and prints the queue. `--help` for flags, `--json` for the machine-readable form.

## Run

From this skill's directory:

```bash
python3 scripts/rank.py ~/work/read-later
```

Per item: `relevance` = mean of the two highest topic weights among its topics (unweighted topics count 5); `quality` = mean of hard-won and grounded; `priority` = half of each, minus 1 for articles over 4000 words, plus 3 for must-read. Excluded: archived, unanalyzed, `not-an-article`, and news or announcements older than 14 days. Top item is **Read today**, the next four **Read next**, the rest **Later**.

## The reader's interests live in `topics.md`

This is the one place where the reader's context enters the system. Each topic line may carry a weight, `- agent-cost: 9`, meaning how much the reader cares right now. You know the reader; keep these numbers current:

- When the reader's focus shifts (a new project, a topic parked), adjust the weights. Do it from what you know; do not ask them to grade thirty labels.
- New labels coined by the analyzer arrive without a weight. Give them one when you next touch the file.
- Never delete a label that items still carry without updating those items.

Changing a weight and rerunning rank is the whole feedback loop for now.

## After the run

Report the queue as the script printed it: the Read today item with its TL;DR and why it ranked first, the Read next titles in one line each, and the count in Later. Do not open articles, do not re-summarize, do not override the order by hand; if the order looks wrong, say which weight you would change and why, and change it only if the reader agrees.

## Rules

- `queue.md` and `queue.json` are generated; fix the weights or the script, never the files.
- The scores in `item.json` are the analyzer's; rank does not rewrite them.
