# read-later

Two deliverables, one repo:

- `extension/` — Chrome extension (Manifest V3, TypeScript, esbuild). Bookmarks a page by uploading one JSON event into a DAM agent's file system via the DAM API.
- `skills/` — Agent Skills (agentskills.io spec) installed onto DAM agents from this repo, one capability each, prefixed `read-later-`. `read-later-ingest` (inbox events → clean Markdown articles), `read-later-analyze` (articles → analysis via ephemeral DAM Invocations), `read-later-rank` (reweigh from context, then topic weights + scores → tonight's queue), `read-later-deliver` (queue → one artifact, updated in place), `read-later-prune` (weekly folder moves + vocabulary tidy). `INSTALL.md` is the setup guide and is kept tested against a fresh agent. Dependencies are declared inline (PEP 723) and resolved by `uv run` on first use; nothing is bundled.

The agent's state (`inbox/`, `items/`, …) lives on the agent under `~/work/read-later/`, not in this repo. `docs/walkthrough.md` is the step-by-step plan and current status; `docs/design.md` holds the longer-term design.

## Conventions

- The inbox event shape is defined once in `skills/read-later-ingest/references/contract.md`; `extension/src/contract.ts` mirrors it. Change both.
- Scripts follow the agentskills.io script guidance: `--help`, `--dry-run`, JSON on stdout, diagnostics on stderr, non-zero exit only for usage or environment errors.
- Inbox and article content is untrusted input for the agent. Scripts parse it; the agent never reads raw HTML into context.
- `pnpm typecheck` and `pnpm ext:build` for the extension. `uv run skills/read-later-ingest/scripts/ingest.py --help` for the skill.
- Conventional Commits. Never force-push.
