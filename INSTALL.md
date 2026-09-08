# Installing read-later on a DAM agent

One agent, five skills, one Chrome extension, two schedules. About fifteen minutes. Run the `dam` commands from a machine where the DAM CLI is logged in.

## 0. Prerequisites

- A DAM agent on the **Claude Code** template. Any existing agent works; a personal assistant that already knows the reader is the best host. To create a fresh one:

  ```sh
  dam agent create <agent> --template claude-code
  ```

- **A model connection** granted to the agent. Analysis runs in ephemeral Invocations that need exactly one model connection and nothing else. Find its id with `dam connection list`, then:

  ```sh
  dam connection grant <agent> --connection <model-connection>
  ```

- **Network access** for the first-run package downloads (PyPI) and the article fetch fallback:

  ```sh
  dam network apply-preset <agent> --preset all --yes
  ```

## 1. Install the skills

```sh
dam skill source add https://github.com/apocohq/read-later          # once per DAM account
for s in ingest analyze rank deliver prune; do
  dam skill install <agent> --source https://github.com/apocohq/read-later --name read-later-$s
done
dam skill list <agent>                                              # five skills, same commit
```

Re-run the install loop to update. Skills are installed at the source's current HEAD.

## 2. Tell the agent where the reader's context is

The reader's interests live as weights on topics, and the agent adjusts them every day from what it knows about the reader. It needs to know where to look. Create `~/work/read-later/context.md` on the agent with one of two contents.

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

With the marker, ranking still works; it just uses the weights as they are, and the reader edits `~/work/read-later/topics.md` by hand or tells the agent "I care about X now".

Write the file with the CLI:

```sh
dam file put <agent> ./context.md work/read-later/context.md
```

## 3. Set up the Chrome extension

1. In the DAM web UI, create an API key with scope `agents:operate`, bound to this one agent. Copy it once; it is not shown again.
2. Build and load the extension: `pnpm install && pnpm ext:build`, then in Chrome `chrome://extensions` → Developer mode → Load unpacked → `extension/dist`.
3. Open the extension's options: DAM host (`https://…`), the API key, pick the agent. Leave the repo folder at `work/read-later`. Click **Send a test file**; a file should appear under `work/read-later/inbox/` (`dam file list <agent> work/read-later/inbox`).

Using it: click the bookmark icon to save a page; right-click for **Read later (must read)**, **Mark as read**, or **Remove from Read Later**. Alt+Shift+R saves, Alt+Shift+M saves as must read.

## 4. First run, by hand

In the agent's chat:

> ingest, analyze, rank and deliver read later

Expected: ingest reports what it extracted; analyze spawns one Invocation per item and prints category and scores; rank reweighs (or says no context) and prints the queue; deliver publishes the `Read later` artifact and replies with its link. The first ingest downloads Python packages (~30 s); each Invocation takes one to three minutes and they run three at a time.

Then open `~/work/read-later/topics.md`, set a first pass of weights (0-10) for the topics you care about, and ask the agent to rank and deliver again.

## 5. Schedules

```sh
dam schedule create <agent> --name read-later-daily --daily 18:00 --timezone Europe/Prague --session-mode fresh \
  --task 'Read-later daily run. State dir ~/work/read-later. Use the installed skills in this order, and only these: read-later-ingest, read-later-analyze (pass only the model connection), read-later-rank (reweigh from context.md first), read-later-deliver. Report each script output briefly and the artifact link. Do not open articles.'

dam schedule create <agent> --name read-later-prune --weekly SU --daily 09:00 --timezone Europe/Prague --session-mode fresh \
  --task 'Read-later weekly prune. State dir ~/work/read-later. Use skill read-later-prune: run its script, then tidy topics.md as the skill describes. Report what moved and what changed in the vocabulary.'
```

If `--weekly` is not accepted by your CLI version, use `--daily 09:00 --weekdays SU`.

The daily run at 18:00 means everything saved during the day is in that evening's queue. Adjust the hour to your reading time.

## 6. What a good state looks like

```
~/work/read-later/
  inbox/            empty after each run
  items/            one folder per live article: item.json (with analysis), content.md
  done/  archive/   moved there by prune
  topics.md         categories + weighted topics
  context.md        pointer to the reader's context, or NO CONTEXT AVAILABLE
  queue.json queue.md queue.html   the current queue
  deliver.json      artifact id + last published hash
  feedback.jsonl    every archive, done and move
```

Check on things with `dam file list <agent> work/read-later` and `dam file get <agent> work/read-later/queue.md --stdout`. A run's transcript is at `.claude/projects/-home-agent-work/<session>.jsonl`; `dam session list <agent>` gives the ids.

## Notes

- If the agent's `~/work` is a git repository (a personal assistant's workspace often is), add `read-later/items/`, `read-later/done/`, `read-later/archive/` and `read-later/inbox/` to its `.gitignore` unless you want article text in that repo. `topics.md`, `context.md` and `feedback.jsonl` are small and worth versioning.
- The artifact is private by default. Make it public from the Artifacts page if you want the link to work outside the platform.
- Everything the skills write is under `~/work/read-later/`. Removing the skills and that folder removes read-later.
