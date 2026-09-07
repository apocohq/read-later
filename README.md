# DAM Read Later

It reads before you do. An agentic reading filter that runs as a DAM agent with this repo as its memory.

- `docs/product-brief.md` — what and why
- `docs/design.md` — decisions for this version
- `CLAUDE.md` — the agent's operating manual and repo layout
- `extension/README.md` — the Chrome/Arc capture extension

## Local development

```sh
pnpm install
pnpm typecheck
pnpm test          # node:test via tsx; no test framework dependency
echo '{"source":"api","url":"https://example.com/post","title":"Example","text":"Some article text."}' | pnpm capture
pnpm process        # drains inbox/, writes items/, regenerates queue.md / queue.json / queue.html
pnpm queue          # re-render the queue files only
pnpm ext:build      # bundle the browser extension into extension/dist/
```
