# Installing read-later on a DAM agent

One agent, six skills, one Chrome extension, two schedules, and optionally Slack. The short way is section A: the agent installs all of it on itself and hands you a list of the few things an agent cannot do. Section B is the same work by hand, from the CLI. Section C is the extension, section D Slack, section E the reader's context when it lives on another agent.

**What only a human can do**, because the platform gives no agent the power: create the agent, grant it a connection, change its network rules, restart it, register the skill source, mint an API key, and load the extension in a browser. That is the whole list. Everything else — skills, folders, the context file, dependencies, schedules, the DAM CLI on the agent — the agent does for itself, and it tells you exactly which of the above it still needs.

## 0. Before either way (owner, once)

A handful of commands, and the only ones that are always yours. The agent checks each grant and names what is missing in its report, so you can also start at section A and come back here.

- **A model connection.** Analysis runs in ephemeral Invocations that need exactly one model connection. Find its id with `dam connection list`, then `dam connection grant <agent> --connection <model-connection>`.
- **Network access** for the first-run package downloads (PyPI) and for fetching pages the browser could not capture: `dam network apply-preset <agent> --preset all --yes`. The `trusted` preset also works, but then bookmarks that arrive without HTML fail unless their host is allowed; PDFs (arXiv papers, reports) are always fetched by the agent, so their hosts must be reachable. With `trusted`, add two hosts the image's `uv` bootstrap needs after every wake, or `uv run` hangs: `dam network create <agent> --host tuf-repo-cdn.sigstore.dev --yes` and `dam network create <agent> --host mise-versions.jdx.dev --yes`.
- **The Slack connection**, if you want to save links from Slack: `dam connection grant <agent> --connection slack`. It must be *your* Slack connection (`dam connection templates` → Slack, log in as yourself): the script reads *your* saved messages. It only reads (two tools, allowlisted in the script). Without the grant the refresh skips this step. See section D.
- A fresh agent, if you need one: `dam agent create <agent> --template claude-code`.
- **The skill source**, once per DAM account: `dam skill source add https://github.com/apocohq/read-later` ("already registered" means it is done).

If the reader's context files live on a **different** agent, one more thing is yours: the key that reaches it, its connection and one network rule (section [E](#e-context-from-another-agent)). The agent prepares everything else for that, including installing the DAM CLI on itself, and its report tells you the three commands to run.

## A. Let the agent install itself

Paste one line into the agent's chat:

> Install read-later on yourself as described in https://raw.githubusercontent.com/apocohq/read-later/main/INSTALL.md

If you already know that the files about you live on another agent, add its name: *…INSTALL.md — my context lives on the agent `guido`*. The agent then prepares section E as far as an agent can.

The agent reads this file and does the steps below with its platform tools (`install_skill`, `create_schedule`) and its shell. Where a step needs a human, it says so in the report instead of stopping.

### Agent steps

If you are the agent reading this, do these in order and report at the end. Do not skip to running the pipeline. **Do as much as you can yourself**: ask the owner only for the things on the list in the preamble — a connection, a network rule, a restart, the skill source, an API key, the browser. Never ask the owner to make a folder, write a file, install a package or create a schedule; do those.

1. **Read this file, not a summary.** Fetch the raw Markdown of the address you were given and read it from disk (`curl -sS <that URL> -o /tmp/INSTALL.md`, then open the file). A web-fetch tool answers with a summary and loses the steps.
2. **Check what the owner must have granted**, so the report can be exact. A model connection: `node -e 'import("/usr/local/lib/driver-sdk.mjs").then(async m => console.log(await m.listConnections()))'` — one model connection is enough, and its name goes into `~/work/read-later/analyze.json` as `{"connection": "<name>"}`, which you write yourself. Network: `curl -sS -o /dev/null -w '%{http_code}\n' https://pypi.org/simple/` answers 200 when the preset is applied. Slack is optional; `read-later-slack` reports its own 401 if it was not granted. Note what is missing and carry on with the rest.
3. **Skills.** Call `list_skill_sources` and find the source whose git URL is `https://github.com/apocohq/read-later`. If it is missing, put `dam skill source add https://github.com/apocohq/read-later` at the top of the owner list in your report and stop after the report; without the source you can install nothing. Otherwise call `install_skill` for each of `read-later-slack`, `read-later-ingest`, `read-later-analyze`, `read-later-rank`, `read-later-deliver`, `read-later-prune`. Installing an already installed skill updates it to the source's HEAD; that is fine. A call the permission classifier refuses is not a real failure: repeat it once.
4. **State dir.** `mkdir -p ~/work/read-later/inbox`. Everything read-later writes lives under `~/work/read-later/`.
5. **Reader context.** Write `~/work/read-later/context.md` yourself, in one of the three shapes in [Reader context](#reader-context):
   - You hold files about the person you work for (a USER.md, memory notes, current projects): list them, one path per line with a few words on what each holds.
   - Those files live on **another agent**, named by the owner or known to you: write the third shape, naming that agent and its files, and do the agent half of section [E](#e-context-from-another-agent) now — install the DAM CLI under `~/.local` and point it at the platform. Then put the owner's three commands (network rule, key, connection, restart) in your report. The file is correct in advance; it starts working the moment the owner runs them.
   - You know nothing about the reader and the owner named no agent: write the single line `NO CONTEXT AVAILABLE`, and say in the report that one sentence about the reader, or the name of an agent that holds their files, is all you need to do better.
6. **Dependencies.** From the ingest skill's directory (`~/.claude/skills/read-later-ingest`) run `UV_CACHE_DIR=~/work/.cache/uv uv run scripts/ingest.py ~/work/read-later` once. The inbox is empty, so it only downloads the Python packages (about 30 MB; PyMuPDF for PDFs, another 250 MB, comes with the first PDF) and prints `done: 0 extracted, 0 failed`. If it prints `mise` lines and hangs, stop and tell the owner the two network rules from section 0 are missing.
7. **Schedules.** Call `create_schedule` twice with the exact names, tasks and times from [Schedules](#schedules). Use the owner's timezone if you know it, otherwise `Europe/Prague`. Fresh session each tick. If a schedule with the same name already exists, leave it.
8. **Git.** If `~/work` is a git repository, make sure `.gitignore` covers `read-later/inbox/`, `read-later/items/`, `read-later/done/` and `read-later/archive/`; keep `topics.md`, `context.md` and `feedback.jsonl` versioned.
9. **Report and stop.** Two short lists. First, what you did, in one line each. Second, **what is left for the owner**, as commands they can paste, and nothing else — typically only:

   ```sh
   dam auth token create --name read-later-ext --scope agents:operate agents:read --agent <this agent's id>
   ```

   Your own agent id is in `$PLATFORM_MCP_URL` (`…/api/agents/<id>/mcp`), so fill it in; the owner should have to type nothing they can avoid. Then: building the extension in their browser (section C), any missing grant you found in step 2, and the three section E commands if you prepared that. Do not ask them for a folder, a file, a package or a schedule: those are yours, and you did them. Do not run analyze, rank or deliver now; there is nothing to process, and the first refresh does it. Topic weights need no owner either: the reweigh sets them from the reader's context on every run, and the owner can overrule any weight in `topics.md` whenever they like.

## B. From the CLI

The same steps, run from a machine where the DAM CLI is logged in.

```sh
for s in slack ingest analyze rank deliver prune; do
  dam skill install <agent> --source https://github.com/apocohq/read-later --name read-later-$s
done
dam skill list <agent>                                              # six skills, same commit
```

Re-run the install loop to update. Skills are installed at the source's current HEAD. The six must appear under **Installed skills**; if they show as *standalone*, the account lost the source registration and you need `dam skill source add` again before reinstalling.

Write the reader context (see [Reader context](#reader-context)) and upload it:

```sh
dam file put <agent> ./context.md work/read-later/context.md      # add --overwrite to replace it later
```

Then make the inbox and warm the Python packages, over SSH:

```sh
dam ssh configure <agent>
ssh dam-<agent> 'mkdir -p ~/work/read-later/inbox'
ssh dam-<agent> 'cd ~/.claude/skills/read-later-ingest && UV_CACHE_DIR=~/work/.cache/uv uv run scripts/ingest.py ~/work/read-later'
```

The first bookmark from the extension would make `inbox/` anyway, and the first ingest would download the packages (about a minute of that refresh) — but `read-later-slack` refuses to run without `inbox/` (`error: … has no inbox/ folder`), so a Slack-only setup needs the `mkdir`. Everything else the skills make themselves.

Create the two schedules with the tasks from [Schedules](#schedules):

```sh
dam schedule create <agent> --name read-later-refresh --daily 18:00 --timezone Europe/Prague --session-mode fresh --task '<refresh task>'
dam schedule create <agent> --name read-later-prune --daily 09:00 --weekdays SU --timezone Europe/Prague --session-mode fresh --task '<prune task>'
```

## C. Chrome extension (owner)

1. Create an API key bound to this one agent, in the DAM web UI (Settings → API keys) or from the CLI:

   ```sh
   dam auth token create --name read-later-ext --scope agents:operate agents:read --agent <agent-id>
   ```

   `agents:operate` uploads; `agents:read` only lets the options page list your agents, and you can leave it out and paste the agent id by hand. The `pk_…` value is printed once, on stderr. The binding holds: the same key aimed at another agent is refused with `API key is not bound to agent …`.
2. Get the extension and build it. It is not in the Chrome Web Store, so you need the repo, Node 20+ and pnpm:

   ```sh
   git clone https://github.com/apocohq/read-later && cd read-later
   pnpm install && pnpm ext:build        # writes extension/dist
   ```

   Then in Chrome `chrome://extensions` → Developer mode → Load unpacked → `extension/dist` (Arc: `arc://extensions`). `extension/README.md` has the rest.
3. Open the extension's options: DAM host (`https://…`), the API key, pick the agent. Leave the repo folder at `work/read-later`. Click **Send a test file**; a file should appear under `work/read-later/inbox/` (`dam file list <agent> work/read-later/inbox`).

Using it: click the bookmark icon to save a page; right-click for **Read later (must read)**, **Mark as read**, or **Remove from Read Later**. Alt+Shift+R saves, Alt+Shift+M saves as must read. A PDF open in the browser works the same way; the agent downloads and converts it during the refresh.

## D. Slack (owner, optional)

With the Slack connection granted (section 0) and `read-later-slack` installed, the daily refresh pulls your saved Slack messages before ingest. Nothing to configure.

Using it:

- **Save for later** on any Slack message with a link (the bookmark icon in the message menu, on desktop or mobile). The next refresh captures every link in that message, like a click on the extension. Nothing else in Slack is read.
- Links behind a login (Google Docs, Box, internal GitHub) and social posts cannot be fetched by the agent. The library page lists them under **Needs attention**; open them and save from the browser if you want them.
- Unsaving in Slack changes nothing. Remove items in the library or with the extension.
- Slack rate-limits search, so the step can take a minute; the script waits and retries.
- Without the grant the script prints `error: Slack MCP answered 401 for initialize` and the refresh carries on with the browser inbox. That line in a run report means the connection is missing, nothing worse.

By hand, in the agent's chat: *pull my saved slack messages into read later*. Then *ingest, analyze, rank and deliver read later* as usual, or the whole line from [First run by hand](#first-run-by-hand).

What the agent never does: post, react, draft or schedule anything in Slack as part of this. The script refuses every Slack tool except search and reading its own profile.

## E. Context from another agent

Use this when read-later runs on its own agent but the files about the reader live on another one (below: `guido`). The read-later agent gets the DAM CLI and an API key that can only read `guido`; the nightly reweigh fetches the files with it. Nothing on `guido` changes.

The work splits in two, and the agent does its half without being asked when it knows the other agent's name (section A, step 5).

**The agent's half** — it runs these on itself, over its own shell:

```sh
npm install -g --prefix ~/.local @dam-agents/cli
~/.local/bin/dam config set server <platform-url>
~/.local/bin/dam --version
printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> ~/.bashrc     # convenience only
```

Install under `~/.local`, not globally: only the home directory survives hibernation. The `PATH` line is a convenience and a permission classifier may refuse it as an unasked change to a shell profile; that is harmless, because everything here uses the full path `~/.local/bin/dam`. `<platform-url>` is the external address the owner's own CLI uses. It is not in the pod — `API_SERVER_URL` and `PLATFORM_MCP_URL` are in-cluster names — and the key works only against the external host. Try to find it before you ask: a candidate built from the cluster namespace in those names is worth one probe, and `curl -sS -o /dev/null -w '%{http_code}' <candidate>/api/health` answering 200 confirms it. Only if no candidate answers, do the rest and put `~/.local/bin/dam config set server <your platform URL>` in the owner's command list. Then write `context.md` in the third shape from [Reader context](#reader-context), with the full path `~/.local/bin/dam` in the fetch command, because the agent's own shell does not always read `.bashrc`. Both are done before the key exists; the file simply starts working when it does.

**Your half** — three commands an agent cannot run. The agent's report should already carry them, filled in.

1. **Network.** The CLI talks to the platform, whose host is not in any preset: `dam network create <agent> --host <platform-host> --yes` (the host part of the URL in `dam auth status`).
2. **API key**, bound to the context agent only. File reads need `agents:operate` (`agents:read` is refused with "Requires agents:operate"); the `--agent` binding keeps the key blind to every other agent:

   ```sh
   dam auth token create --name read-later-context --scope agents:operate --agent <guido-agent-id>
   ```

   `--agent` takes the id, not the name (a name is refused with "does not exist or is not owned by you"); `dam agent list` prints both. The agent cannot see another agent's id, so this is the one blank in its report you fill in.

   The token is printed once on stderr. Never write it into a file under `~/work`.

   The agent reads it from `DAM_TOKEN`. An agent that already exists takes new environment variables only from a connection, so make a **Custom header credential**. From the CLI, in one line:

   ```sh
   dam connection connect custom-header --name read-later-context \
     --host <platform-host> --header-name Authorization \
     --value-format 'Bearer {value}' --value <the pk_… key> --env-name DAM_TOKEN
   ```

   Or in the web UI (Connection catalogue → Custom Headers → Add Custom header credential):

   | field | value |
   |---|---|
   | Name | `read-later-context` |
   | Host | the platform host, e.g. `dam-dev.apps.dam-cl.fmaas.res.ibm.com` |
   | Header name | `Authorization` |
   | Value format | `Bearer {value}` |
   | Secret value | the API key |
   | Environment variable | `DAM_TOKEN` |

   Host is mandatory, although the form does not mark it. The connection does two things: it puts the key in `DAM_TOKEN`, and it rewrites the `Authorization` header on calls to that host. The rewrite is safe, because the agent's own platform traffic uses an in-cluster address, and the CLI sends the same key anyway.

   Then grant it and restart: `dam connection grant <agent> --connection read-later-context` and `dam agent restart <agent>`. `DAM_SERVER` is not needed, because the agent's half wrote the server into `~/.config/dam/config.toml`.
3. **Check** from inside the agent: `ssh dam-<agent> '~/.local/bin/dam file get guido work/USER.md --stdout | head -3'`. "Not logged in" means `DAM_TOKEN` is not in the environment; a network approval in your inbox means step 1 is missing. A fresh key can be rejected with "DAM_TOKEN was rejected" for the first minute after minting; wait and retry before you suspect the key. `DAM_TOKEN` inside the pod holds a placeholder, not the key (`echo $DAM_TOKEN` prints `dummy-…`): the gateway swaps the real key into the `Authorization` header on the way out. That is normal, and it is why the key works only against that host.
Or leave the check to the agent: *check that you can read my files on `guido`* after the restart, and it reports the first lines or the error. If the agent never did its half (it was installed before you knew about the other agent), tell it *my context lives on the agent `guido`; set up your side of section E of the install guide* and it does the rest.

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

An agent that reads the context from **another agent** (a dedicated read-later agent next to your personal assistant; setup in section [E](#e-context-from-another-agent)):

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

## Check the install

Ask the agent: *check your read-later install and tell me anything that is missing*. It can see all of it — its skills, its schedules, its state dir, its connections — and it fixes what it can before answering.

The same from the CLI, if you want to see for yourself:

```sh
dam skill list <agent>                     # six read-later-* skills, under Installed skills
dam schedule list <agent>                  # read-later-refresh and read-later-prune, enabled
dam file list <agent> work/read-later      # inbox/ and context.md at least
```

Then save one page with the extension and confirm the event arrived: `dam file list <agent> work/read-later/inbox`. The upload wakes a hibernated agent, so the first one can take up to two minutes.

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
