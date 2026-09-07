# read-later

Bookmark a page in Chrome, and a DAM agent turns it into a clean article, then into a small ranked reading queue.

```
Chrome extension  ──files.upload──▶  ~/work/read-later/inbox/<id>.json  ──skill──▶  ~/work/read-later/items/
```

- `extension/` — the Chrome extension. Setup in `extension/README.md`.
- `skills/read-later/` — the agent skill. Install it onto any DAM agent from this repo.
- `docs/walkthrough.md` — where we are and what is next.

## Install the skill on an agent

```sh
dam skill source add https://github.com/<org>/read-later      # once
dam skill install <agent> --source https://github.com/<org>/read-later --name read-later
```

Re-run install to update. Then ask the agent: *"process the read-later inbox"*.

## Develop

```sh
pnpm install && pnpm typecheck && pnpm ext:build        # extension → extension/dist
uv run skills/read-later/scripts/ingest.py --help      # skill script
```
