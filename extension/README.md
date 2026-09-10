# DAM Read Later browser extension

Chrome and Arc, Manifest V3. One click captures the current page (URL, title, selection, and the full rendered HTML; for a PDF tab just URL and title, the agent fetches the file) and uploads it as a file into your agent's workspace on DAM. The agent's next refresh picks it up from `work/read-later/inbox/`.

No Slack app, no GitHub token. The only credential is a DAM API key.

## Setup

1. **Create an API key in DAM.** Settings → API keys. Scopes: `agents:operate` (upload) and `agents:read` (lets the options page list your agents). Bind it to your Read Later agent only. Copy the `pk_…` value once; it is not shown again.
2. **Build the extension.** From the repo root:
   ```sh
   pnpm install
   pnpm ext:build        # writes extension/dist/
   ```
3. **Load it.** `chrome://extensions` → Developer mode → Load unpacked → pick `extension/dist`. Arc: same page via `arc://extensions`.
4. **Configure.** Open the extension options (right-click the icon → Options). Enter the DAM host origin and API key, click *Load agents*, pick the agent, keep the folder as `work/read-later` (paths are relative to the agent's home directory; this is the state dir the skills read). Save. The browser asks once for permission to reach the DAM host.
5. **Test upload** writes a small `.txt` file into `work/read-later/inbox/` on the agent. Ingest skips non-JSON files; delete it whenever.

## Use

- Toolbar icon or `Alt+Shift+R`: *Read later*. Click the icon again on a saved page to archive it (the agent drops it if unprocessed, archives it otherwise). On a page you already marked as read, the click puts it back in the queue.
- `Alt+Shift+M`, or *Read later (must read)* from the right-click menu on a page or on the toolbar icon: never filtered out, boosted in the queue.
- *Mark as read* in the same menus sends a `done` event; the agent moves the item to `done/` and it leaves the queue. The icon turns into a grey bookmark with a check, and stays that way when you come back to the page.
- *Archive in Read Later* and *Delete from Read Later* are also in both menus. Archive keeps the item folder on the agent; delete removes it for good.
- Select text first to attach it as a hint about why the page matters.
- The toolbar icon tells you what happened: a grey dashed outline marching around the bookmark while uploading, a green bookmark with a check when saved, a gold solid bookmark with the check cut out for must read, a grey bookmark with a check once you marked it as read, a grey exclamation mark for a failure (details in the service worker console). Idle, done and error states stay in the same grey as the other toolbar icons, so colour only ever means "this page is in your queue".
- The extension remembers what it sent (locally, per browser profile) and shows the saved or done icon again when you return to that page. Tracking parameters and fragments are ignored when matching.

The upload wakes a hibernated agent, so the first capture after a quiet period can take up to two minutes. Later ones are instant.

## Where the key is stored

In `chrome.storage.local` inside your browser profile, never in sync storage, so it stays on this machine. Web pages and other extensions cannot read it; someone with access to your profile folder can, the same as your cookies. Full-disk encryption is the real protection at rest.

That last point is the limit worth understanding: anyone who can copy your profile folder can also just run your browser, so no client-side storage scheme in an extension defends against it. What the extension does instead is keep the blast radius small.

- The key is only ever sent over TLS. `DamClient` refuses a non-https host outright (loopback excepted for local development), and the manifest only asks for `https://*/*` plus loopback, so the browser will not grant a plain-http origin either.
- Keep the key scoped to `agents:operate` (plus `agents:read` for the agent picker) and bound to the one agent. Uploads use `overwrite: false`, so even a stolen key can only add new files under fresh timestamped names — it cannot alter or destroy anything already in the workspace.
- Everything the extension writes lands in `work/read-later/inbox/`, which the skills treat as untrusted data rather than instructions. A stolen key buys an attacker inbox spam, not influence over the agent.
- Revoke the key in DAM if the machine is lost. Rotating it costs one paste into this options page.

The strongest remaining hardening is server-side rather than in the extension: a key scoped to `files.upload` under `work/read-later/inbox/` only, or short-lived tokens with a rotating refresh token, would shrink the worst case further.

## How it talks to DAM

`POST {host}/api/trpc/files.upload` with `Authorization: Bearer pk_…` and a plain-JSON body `{ agentId, path, contentBase64, contentType, overwrite: false }`. That is the same procedure `dam file put` uses. Paths are relative to the agent's home directory (not `work/`) and may not touch `.triggers` or `.initialized`. Per-file cap on the agent is 50 MB; a page snapshot is typically a few hundred KB.

## Development

`pnpm typecheck` covers `extension/src` with Chrome types. Rebuild with `pnpm ext:build` and click *Reload* on `chrome://extensions`. `dist/` is gitignored.
