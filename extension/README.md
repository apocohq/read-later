# DAM Read Later browser extension

Chrome and Arc, Manifest V3. One click captures the current page (URL, title, selection, and the full rendered HTML) and uploads it as a file into your Read Later agent's workspace on DAM. The agent's next run picks it up from `inbox/`.

No Slack app, no GitHub token. The only credential is a DAM API key.

## Setup

1. **Create an API key in DAM.** Settings → API keys. Scopes: `agents:operate` (upload) and `agents:read` (lets the options page list your agents). Bind it to your Read Later agent only. Copy the `pk_…` value once; it is not shown again.
2. **Build the extension.** From the repo root:
   ```sh
   pnpm install
   pnpm ext:build        # writes extension/dist/
   ```
3. **Load it.** `chrome://extensions` → Developer mode → Load unpacked → pick `extension/dist`. Arc: same page via `arc://extensions`.
4. **Configure.** Open the extension options (right-click the icon → Options). Enter the DAM host origin and API key, click *Load agents*, pick the agent, keep the repo folder as `work` (paths are relative to the agent's home directory, and the repo is the agent's work dir). Save. The browser asks once for permission to reach the DAM host.
5. **Test upload** writes a small `.txt` file into `inbox/` on the agent. The pipeline ignores non-JSON files; delete it whenever.

## Use

- Toolbar icon or `Alt+Shift+R`: *Read later*. Click the icon again on a saved page to remove it (the agent drops it if unprocessed, archives it otherwise).
- `Alt+Shift+M`, or *Read later (must read)* from the right-click menu on a page or on the toolbar icon: bypasses filtering.
- *Remove from Read Later* is also in both right-click menus.
- Select text first to attach it as a hint about why the page matters.
- The toolbar icon tells you what happened: a grey dashed outline marching around the bookmark while uploading, a green bookmark with a check when saved, a gold solid bookmark with the check cut out for must read, a grey exclamation mark for a failure (details in the service worker console). Idle and error states stay in the same grey as the other toolbar icons, so colour only ever means "this page is in your queue".
- The extension remembers what it sent (locally, per browser profile) and shows the saved icon again when you return to that page. Tracking parameters and fragments are ignored when matching.

The upload wakes a hibernated agent, so the first capture after a quiet period can take up to two minutes. Later ones are instant.

## Where the key is stored

In `chrome.storage.local` inside your browser profile, never in sync storage, so it stays on this machine. Web pages and other extensions cannot read it; someone with access to your profile folder can, the same as your cookies. Full-disk encryption is the real protection at rest.

That last point is the limit worth understanding: anyone who can copy your profile folder can also just run your browser, so no client-side storage scheme in an extension defends against it. What the extension does instead is keep the blast radius small.

- The key is only ever sent over TLS. `DamClient` refuses a non-https host outright (loopback excepted for local development), and the manifest only asks for `https://*/*` plus loopback, so the browser will not grant a plain-http origin either.
- Keep the key scoped to `agents:operate` (plus `agents:read` for the agent picker) and bound to the one agent. Uploads use `overwrite: false`, so even a stolen key can only add new files under fresh timestamped names — it cannot alter or destroy anything already in the workspace.
- Everything the extension writes lands in `inbox/`, which the pipeline treats as untrusted data rather than instructions. A stolen key buys an attacker inbox spam, not influence over the agent.
- Revoke the key in DAM if the machine is lost. Rotating it costs one paste into this options page.

The strongest remaining hardening is server-side rather than in the extension: a key scoped to `files.upload` under `work/read-later/inbox/` only, or short-lived tokens with a rotating refresh token, would shrink the worst case further.

## How it talks to DAM

`POST {host}/api/trpc/files.upload` with `Authorization: Bearer pk_…` and a plain-JSON body `{ agentId, path, contentBase64, contentType, overwrite: false }`. That is the same procedure `dam file put` uses. Paths are relative to the agent's home directory (not `work/`) and may not touch `.triggers` or `.initialized`. Per-file cap on the agent is 50 MB; a page snapshot is typically a few hundred KB.

## Development

`pnpm typecheck` covers `extension/src` with Chrome types. Rebuild with `pnpm ext:build` and click *Reload* on `chrome://extensions`. `dist/` is gitignored.
