---
name: read-later-slack
description: Turns the reader's saved Slack messages ("Save for later") into read-later inbox events. One script call, no judgment. Use before read-later-ingest in a refresh, or when the reader asks to pull what they saved in Slack into read-later.
compatibility: Python 3.11+, standard library only. Runs on a DAM agent that holds the Slack connection (the egress gateway adds the token; the script talks to mcp.slack.com directly).
metadata:
  version: "0.2"
---

# Read Later · Slack

A second producer for the read-later inbox, next to the Chrome extension. In Slack the reader presses **Save for later** on a message with a link; this script turns every such link into an inbox event. `read-later-ingest` does the rest, exactly as for a browser bookmark.

## Available scripts

- **`scripts/slack.py`** — searches the reader's saved messages and writes inbox events for the links in them. `--help` for flags, `--dry-run` to look without writing, `--json` for machine-readable output.

## Run

From this skill's directory:

```bash
python3 scripts/slack.py ~/work/read-later
```

Idempotent. Run it as often as you like; a link is captured once. Slack rate-limits search, so the script may wait and retry between pages; let it finish.

## What it does

1. Searches `is:saved has:link` through the Slack MCP server, newest first, up to five pages of twenty.
2. For every link in a saved message: drops what is never reading material (Slack permalinks, meeting and calendar links, tickets, boards, images); sets aside what the fetch fallback cannot reach (documents behind a login, social posts) into `slack/skipped.json`, which `read-later-rank` shows under *Needs attention*; skips links already in `items/`, `done/`, `archive/`, the inbox or its own ledger.
3. Writes one inbox event per remaining link with `source: "slack"`, the message permalink as `sourceRef`, the poster's words as `note`, and `recommendedBy` ("Radek Ježek in #podcast-club") unless the reader posted it in their own DM.

Unsaving in Slack changes nothing; the reader removes items in the library or with the extension.

## After the run

Report the script's output in one or two lines: how many links were captured and from whom, and which were skipped as unreachable. Then continue with `read-later-ingest`. Do not open the links.

## Rules

- **Read only.** The script calls two read-only Slack tools and refuses others. Never use your own Slack tools to send, react, schedule or draft anything as part of this skill.
- Never write inbox files by hand for Slack links; run the script, so `slack/state.json` stays honest about what was seen.
- If the script fails to start (no Slack connection, MCP error, rate limit), report that and continue the refresh with `read-later-ingest`; do not read Slack by hand with your own tools.

## Files

Under `~/work/read-later/slack/`: `state.json` (who the reader is on Slack, last run, one line per URL seen), `skipped.json` (unreachable links for the library page). The event shape is in `read-later-ingest`'s `references/contract.md`.

## Related skills

`read-later-ingest` turns the events into items. `read-later-rank` lists the skipped links under *Needs attention*, and `read-later-deliver` shows who shared each item.
