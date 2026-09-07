# read-later

Bookmark a page in Chrome, and a DAM agent turns it into a clean article, then into a small ranked reading queue.

```
Chrome extension  ──files.upload──▶  ~/work/read-later/inbox/<id>.json  ──skill──▶  ~/work/read-later/items/
```

- `extension/` — the Chrome extension. Setup in `extension/README.md`.
- `skills/` — the agent skills, one per capability: `read-later-ingest` (inbox → articles) and `read-later-analyze` (articles → TL;DR, category, scores, recommendation). Install them onto any DAM agent from this repo.
- `docs/walkthrough.md` — where we are and what is next.

## Install the skill on an agent

```sh
dam skill source add https://github.com/<org>/read-later      # once
dam skill install <agent> --source https://github.com/<org>/read-later --name read-later-ingest
dam skill install <agent> --source https://github.com/<org>/read-later --name read-later-analyze
```

Re-run install to update. Then ask the agent: *"ingest and analyze read later"*.

## Develop

```sh
pnpm install && pnpm typecheck && pnpm ext:build        # extension → extension/dist
uv run skills/read-later-ingest/scripts/ingest.py --help      # ingest script
node skills/read-later-analyze/scripts/analyze.mjs --help     # analyze script (needs a DAM agent to actually spawn)
```
