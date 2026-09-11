# Installing read-later on a DAM agent

One agent, six skills, one Chrome extension, two schedules, and optionally Slack. Two ways to get there: tell the agent to install itself (section A), or run the CLI yourself (section B). Both end with the extension (section C) and, if you want links from Slack, section D. Section E is for a read-later agent that reads the reader's context from another agent.

## 0. Before either way (owner, once)

The agent must exist on the **Claude Code** template and have two things only an owner can grant. Do these first; nothing below asks for them again.

- **A model connection.** Analysis runs in ephemeral Invocations that need exactly one model connection. Find its id with `dam connection list`, then `dam connection grant <agent> --connection <model-connection>`.
- **Network access** for the first-run package downloads (PyPI) and for fetching pages the browser could not capture: `dam network apply-preset <agent> --preset all --yes`. The `trusted` preset also works, but then bookmarks that arrive without HTML fail unless their host is allowed; PDFs (arXiv papers, reports) are always fetched by the agent, so their hosts must be reachable. With `trusted`, add two hosts the image's `uv` bootstrap needs after every wake, or `uv run` hangs: `dam network create <agent> --host tuf-repo-cdn.sigstore.dev --yes` and `dam network create <agent> --host mise-versions.jdx.dev --yes`.
- **The Slack connection**, if you want to save links from Slack: `dam connection grant <agent> --connection slack`. It must be *your* Slack connection (`dam connection templates` → Slack, log in as yourself): the script reads *your* saved messages. It only reads (two tools, allowlisted in the script). Without the grant the refresh skips this step. See section D.
- A fresh agent, if you need one: `dam agent create <agent> --template claude-code`.
- **A `DAM_TOKEN` connection**, if the reader's context files live on a different agent (a read-later agent beside your personal assistant). The key, the connection that carries it and the network rule are all owner work: section [E](#e-context-from-another-agent-owner-optional).

The skill source must be registered once per DAM account: `dam skill source add https://github.com/apocohq/read-later` ("already registered" means it is done).

## A. Let the agent install itself

Paste one line into the agent's chat:

> Install read-later on yourself as described in https://raw.githubusercontent.com/apocohq/read-later/main/INSTALL.md

The agent reads this file and does the steps below with its platform tools (`install_skill`, `create_schedule`). It cannot grant connections or change network rules; that is section 0.

### Agent steps

If you are the agent reading this, do these in order and report at the end. Do not skip to running the pipeline.

1. **Skills.** Call `list_skill_sources` and find the source whose git URL is `https://github.com/apocohq/read-later`. If it is missing, stop and tell the owner to run `dam skill source add https://github.com/apocohq/read-later`. Otherwise call `install_skill` for each of `read-later-slack`, `read-later-ingest`, `read-later-analyze`, `read-later-rank`, `read-later-deliver`, `read-later-prune`. Installing an already installed skill updates it to the source's HEAD; that is fine.
2. **State dir.** `mkdir -p ~/work/read-later/inbox`. Everything read-later writes lives under `~/work/read-later/`.
3. **Reader context.** Write `~/work/read-later/context.md`. If you keep files about the person you work for (a USER.md, memory notes, current projects), list them, one path per line with a few words on what each holds, under the heading `# Reader context` and the line `Read these before reweighing topics:`. If you know nothing about the reader, write the single line `NO CONTEXT AVAILABLE`; if those files live on another agent, write that same line and tell the owner, because only they can set up the key that reaches it (section E). See [Reader context](#reader-context) for all three shapes.
4. **Dependencies.** From the ingest skill's directory run `UV_CACHE_DIR=~/work/.cache/uv uv run scripts/ingest.py ~/work/read-later` once. The inbox is empty, so it only downloads the Python packages (about 30 MB; PyMuPDF for PDFs, another 250 MB, comes with the first PDF) and prints `done: 0 extracted, 0 failed`. If it prints `mise` lines and hangs, stop and tell the owner the two network rules from section 0 are missing.
5. **Schedules.** Call `create_schedule` twice with the exact names, tasks and times from [Schedules](#schedules). Use the owner's timezone if you know it, otherwise `Europe/Prague`. Fresh session each tick. If a schedule with the same name already exists, leave it.
6. **Git.** If `~/work` is a git repository, make sure `.gitignore` covers `read-later/inbox/`, `read-later/items/`, `read-later/done/` and `read-later/archive/`; keep `topics.md`, `context.md` and `feedback.jsonl` versioned.
7. **Report and stop.** List what you created, then tell the owner the two things that remain theirs: the extension key (section C) and, optionally, a first pass of topic weights after the first refresh. Do not run analyze, rank or deliver now; there is nothing to process, and the first scheduled refresh does it.

## B. From the CLI

The same steps, run from a machine where the DAM CLI is logged in.

```sh
for s in slack ingest analyze rank deliver prune; do
  dam skill install <agent> --source https://github.com/apocohq/read-later --name read-later-$s
done
dam skill list <agent>                                              # six skills, same commit
```

Re-run the install loop to update. Skills are installed at the source's current HEAD.

Write the reader context (see [Reader context](#reader-context)) and upload it:

```sh
dam file put <agent> ./context.md work/read-later/context.md
```

Create the two schedules with the tasks from [Schedules](#schedules):

```sh
dam schedule create <agent> --name read-later-refresh --daily 18:00 --timezone Europe/Prague --session-mode fresh --task '<refresh task>'
dam schedule create <agent> --name read-later-prune --daily 09:00 --weekdays SU --timezone Europe/Prague --session-mode fresh --task '<prune task>'
```

## C. Chrome extension (owner)

1. In the DAM web UI, create an API key with scope `agents:operate`, bound to this one agent. Copy it once; it is not shown again.
2. Build and load the extension: `pnpm install && pnpm ext:build`, then in Chrome `chrome://extensions` → Developer mode → Load unpacked → `extension/dist`.
3. Open the extension's options: DAM host (`https://…`), the API key, pick the agent. Leave the repo folder at `work/read-later`. Click **Send a test file**; a file should appear under `work/read-later/inbox/` (`dam file list <agent> work/read-later/inbox`).

Using it: click the bookmark icon to save a page; right-click for **Read later (must read)**, **Mark as read**, or **Remove from Read Later**. Alt+Shift+R saves, Alt+Shift+M saves as must read. A PDF open in the browser works the same way; the agent downloads and converts it during the refresh.

## D. Slack (owner, optional)

With the Slack connection granted (section 0) and `read-later-slack` installed, the daily refresh pulls your saved Slack messages before ingest. Nothing to configure.

Using it:

- **Save for later** on any Slack message with a link (the bookmark icon in the message menu, on desktop or mobile). The next refresh captures every link in that message, like a click on the extension. Nothing else in Slack is read.
- Links behind a login (Google Docs, Box, internal GitHub) and social posts cannot be fetched by the agent. The library page lists them under **Needs attention**; open them and save from the browser if you want them.
- Unsaving in Slack changes nothing. Remove items in the library or with the extension.
- Slack rate-limits search, so the step can take a minute; the script waits and retries.

By hand, in the agent's chat: *pull my saved slack messages into read later*. Then *ingest, analyze, rank and deliver read later* as usual, or the whole line from [First run by hand](#first-run-by-hand).

What the agent never does: post, react, draft or schedule anything in Slack as part of this. The script refuses every Slack tool except search and reading its own profile.

## E. Context from another agent (owner, optional)

Use this when read-later runs on its own agent but the files about the reader live on another one (below: `guido`). The read-later agent gets the DAM CLI and an API key that can only read `guido`; the nightly reweigh fetches the files with it. Nothing on `guido` changes.

**Every step here is yours, not the agent's.** An agent cannot mint an API key, create or grant a connection, or add a network rule. If you tell an agent to install itself (section A) and its reader context lives elsewhere, it writes `NO CONTEXT AVAILABLE` and stops; come back here, then replace that file.

1. **Network.** The CLI talks to the platform, whose host is not in any preset: `dam network create <agent> --host <platform-host> --yes` (the host part of the URL in `dam auth status`).
2. **CLI on the agent.** Over SSH (`dam ssh configure <agent>`, then `ssh dam-<agent> '<cmd>'`):

   ```sh
   npm install -g --prefix ~/.local @dam-agents/cli
   printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> ~/.bashrc
   printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> ~/.profile
   ~/.local/bin/dam config set server <platform-url>
   ~/.local/bin/dam --version
   ```

   Install under `~/.local`, not globally: only the home directory survives hibernation. Write the full path `~/.local/bin/dam` in `context.md` as well, because the agent's own shell does not always read `.bashrc`.
3. **API key**, bound to the context agent only. File reads need `agents:operate` (`agents:read` is refused with "Requires agents:operate"); the `--agent` binding keeps the key blind to every other agent:

   ```sh
   dam auth token create --name read-later-context --scope agents:operate --agent <guido-agent-id>
   ```

   The token is printed once on stderr. Never write it into a file under `~/work`.

   The agent reads it from `DAM_TOKEN`. An agent that already exists takes new environment variables only from a connection, so make a **Custom header credential** in the web UI (Connection catalogue → Custom Headers → Add Custom header credential):

   | field | value |
   |---|---|
   | Name | `read-later-context` |
   | Host | the platform host, e.g. `dam-dev.apps.dam-cl.fmaas.res.ibm.com` |
   | Header name | `Authorization` |
   | Value format | `Bearer {value}` |
   | Secret value | the API key |
   | Environment variable | `DAM_TOKEN` |

   Host is mandatory, although the form does not mark it. The connection does two things: it puts the key in `DAM_TOKEN`, and it rewrites the `Authorization` header on calls to that host. The rewrite is safe, because the agent's own platform traffic uses an in-cluster address, and the CLI sends the same key anyway.

   Then grant it and restart: `dam connection grant <agent> --connection read-later-context` and `dam agent restart <agent>`. `DAM_SERVER` is not needed, because step 2 wrote the server into `~/.config/dam/config.toml`.
4. **Check** from inside the agent: `ssh dam-<agent> '~/.local/bin/dam file get guido work/USER.md --stdout | head -3'`. "Not logged in" means `DAM_TOKEN` is not in the environment; a network approval in your inbox means step 1 is missing. A fresh key can be rejected with "DAM_TOKEN was rejected" for the first minute after minting; wait and retry before you suspect the key.
5. **context.md** in the third shape from [Reader context](#reader-context), listing the files to fetch.

Moving an existing library to the new agent: `ssh dam-guido 'tar czf - -C ~/work read-later' > backup.tgz`, then `ssh dam-<agent> 'tar xzf - -C ~/work' < backup.tgz`. Delete `deliver.json` on the new agent so the first deliver creates its own artifact; keep `analyze.json` (the model connection name) and `slack/state.json` (links already seen). Disable the two schedules on the old agent, then point the extension at the new one (section C).

## Reader context

`~/work/read-later/context.md` tells the nightly reweigh where the reader's interests live. Three shapes.

An agent that knows the reader (a personal assistant with memory files):

```markdown
# Reader context
Read these before reweighing topics:
- ~/work/USER.md (role, focus, preferences)
- ~/work/projects/README.md (what is live now)
```

An agent that knows nothing about the reader:

```markdown
NO CONTEXT AVAILABLE
```

An agent that reads the context from **another agent** (a dedicated read-later agent next to your personal assistant; setup in section [E](#e-context-from-another-agent-owner-optional)):

```markdown
# Reader context
Read these before reweighing topics. They live on the agent `guido`, not here.
Fetch each one with the DAM CLI (read-only; the key comes from `DAM_TOKEN` in the environment):

    ~/.local/bin/dam file get guido <path> --stdout

- work/USER.md (role, focus, preferences)
- work/MEMORY.md (durable facts, open threads)
- work/projects/README.md (what is live now)

If the CLI fails (no token, no network), say so in one line and rank with the weights as they are.
```

List files, not folders: `dam file get` fetches one file per call.

With the marker, ranking still works; it just uses the weights as they are, and the reader edits `~/work/read-later/topics.md` by hand or tells the agent "I care about X now".

## Schedules

Two schedules, fresh session each tick. The refresh at 18:00 means everything saved during the day is in that evening's queue; move the hour to your reading time.

| name | when | task |
|---|---|---|
| `read-later-refresh` | daily 18:00 | `Read-later refresh. State dir ~/work/read-later. Use the installed skills in this order, and only these: read-later-slack (run its script; skip the skill if it reports no Slack connection), read-later-ingest (with UV_CACHE_DIR=~/work/.cache/uv), read-later-analyze (pass only the model connection), read-later-rank (reweigh from context.md first), read-later-deliver. Report each script output briefly and the artifact link. Do not open articles.` |
| `read-later-prune` | Sundays 09:00 | `Read-later weekly prune. State dir ~/work/read-later. Use skill read-later-prune: run its script, then tidy topics.md as the skill describes. Report what moved and what changed in the vocabulary.` |

## First run by hand

Once a few pages are saved, in the agent's chat:

> pull saved slack messages, ingest, analyze, rank and deliver read later

Expected: the Slack step reports how many saved links it captured; ingest reports what it extracted; analyze spawns one Invocation per item and prints category and scores; rank reweighs (or says no context) and prints the queue; deliver publishes the `Read later` artifact and replies with its link. Each Invocation takes one to three minutes and they run three at a time.

Then open `~/work/read-later/topics.md`, set a first pass of weights (0-10) for the topics you care about, and ask the agent to rank and deliver again.

## What a good state looks like

```
~/work/read-later/
  inbox/            empty after each run
  slack/            state.json (last run, URLs seen), skipped.json (links behind logins, listed on the page)
  items/            one folder per live article: item.json (with analysis), content.md, highlights.json when you highlighted
  done/  archive/   moved there by prune
  topics.md         categories + weighted topics
  context.md        pointer to the reader's context, or NO CONTEXT AVAILABLE
  queue.json        the current order and buckets (from rank)
  queue.html        the library page deliver publishes
  deliver.json      artifact id + last published hash
  feedback.jsonl    every archive, done, highlight paste and move
```

Check on things with `dam file list <agent> work/read-later` and `dam file get <agent> work/read-later/queue.json --stdout`. A run's transcript is at `.claude/projects/-home-agent-work/<session>.jsonl`; `dam session list <agent>` gives the ids.

## Notes

- The artifact is private by default. Make it public from the Artifacts page if you want the link to work outside the platform.
- Everything the skills write is under `~/work/read-later/`. Removing the skills and that folder removes read-later.
