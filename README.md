# read-later

Bookmark a page in Chrome, and a DAM agent turns it into a clean article, then into a small ranked reading queue.

```
Chrome extension  ──files.upload──▶  ~/work/read-later/inbox/<id>.json  ──skill──▶  ~/work/read-later/items/
```

- `extension/` — the Chrome extension. Setup in `extension/README.md`.
- `skills/` — the agent skills, one per capability: `read-later-ingest` (inbox → articles), `read-later-analyze` (articles → TL;DR, category, topics, scores), `read-later-rank` (weights + scores → tonight's queue), `read-later-deliver` (queue → one artifact), `read-later-prune` (weekly housekeeping).
- `INSTALL.md` — setting up an agent, end to end.
- `docs/walkthrough.md` — where we are and what is next.

## Install

See `INSTALL.md`. In short: one DAM agent with a model connection, five skills installed from this repo, the extension pointed at the agent, two schedules.

## Develop

```sh
pnpm install && pnpm typecheck && pnpm ext:build        # extension → extension/dist
uv run skills/read-later-ingest/scripts/ingest.py --help      # ingest script
node skills/read-later-analyze/scripts/analyze.mjs --help     # analyze script (needs a DAM agent to actually spawn)
python3 skills/read-later-rank/scripts/rank.py --help          # rank script
python3 skills/read-later-deliver/scripts/render.py --help     # queue.html renderer
python3 skills/read-later-prune/scripts/prune.py --help        # prune script
```
