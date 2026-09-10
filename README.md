# read-later

Bookmark a page in Chrome, and a DAM agent turns it into a clean article, scores it, and shelves it in a small ranked library you read from one page. Videos and podcast episodes are shelved too, from what their page declares (title, show, duration, description); transcripts are not fetched.

```
Chrome extension ─▶ inbox/<id>.json ─▶ ingest ─▶ items/ ─▶ analyze ─▶ rank ─▶ queue ─▶ deliver ─▶ one artifact
                   (files.upload)              (Invocation per article)    (topic weights)      (updated in place)
```

- `extension/` — the Chrome extension. Setup in `extension/README.md`.
- `skills/` — the agent skills, one per capability: `read-later-ingest` (inbox → articles), `read-later-analyze` (articles → TL;DR, category, topics, scores), `read-later-rank` (weights + scores → tonight's queue), `read-later-deliver` (queue → one artifact), `read-later-prune` (weekly housekeeping).
- `INSTALL.md` — setting up an agent, end to end, by telling the agent or from the CLI.
- `docs/walkthrough.md` — how it was built, what was tested, what is next.
- `docs/design.md` — the decisions behind it.

## What you get

- **The library**: one artifact in the DAM artifact library, updated in place. Book-shaped tiles on three shelves (Tonight: three picks, Next: four, Later: the rest), each with segmented 0-10 bars for relevance, hard-won and grounded. Click a tile for the TL;DR, key claims, the scores with their reasons, and the full article text.
- **Analysis you can argue with**: every score carries a one-sentence reason from the text. The rubric is three prompt files; the category list and topic vocabulary are one editable file; your interests are weights on topics.
- **Actions from where you read**: in Chrome, right-click for *Mark as read*, *Archive in Read Later* or *Delete from Read Later*. In chat, tell the agent. The page itself is static.
- **One unattended refresh a day** (`read-later-refresh`, 18:00 Prague) and one weekly tidy (`read-later-prune`). A refresh costs the agent one short turn plus one isolated model run per new article; the page is republished only when something changed.

## Install

One DAM agent with a model connection and network access (the owner grants both, once). Then either:

- **Tell the agent.** Paste into its chat:

  > Install read-later on yourself as described in https://raw.githubusercontent.com/apocohq/read-later/main/INSTALL.md

  The agent installs the five skills onto itself, writes its reader context, creates the two schedules, and reports back. Works on any DAM agent that is already running.

- **From the CLI.** `dam skill install` for the five skills, `dam file put` for the context file, `dam schedule create` twice.

Both paths and the extension setup are in `INSTALL.md`.

## Versioning

DAM pins each installed skill to the commit it was installed from and shows drift when the repo moves on; re-running `dam skill install` adopts HEAD. There are no release tags. Inside the skills, `ANALYSIS_VERSION` in `analyze.mjs` is the version that matters: bump it when a prompt or the result schema changes, and every item analyzed under the old version is redone on the next run. The `metadata.version` in each `SKILL.md` is a human label only.

## Develop

```sh
pnpm install && pnpm typecheck && pnpm ext:build        # extension → extension/dist
uv run skills/read-later-ingest/scripts/ingest.py --help      # ingest script
node skills/read-later-analyze/scripts/analyze.mjs --help     # analyze script (needs a DAM agent to actually spawn)
python3 skills/read-later-rank/scripts/rank.py --help          # rank script
python3 skills/read-later-deliver/scripts/render.py --help     # queue.html renderer
python3 skills/read-later-prune/scripts/prune.py --help        # prune script
```
