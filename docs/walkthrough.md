# Walkthrough

What works today, what is next. One step at a time, each step tested before the next.

## Step 1 · Chrome extension → agent file system  ✅ works

```
 Chrome                          DAM api-server                 Agent pod
┌──────────────────────┐  HTTPS   ┌──────────────────┐  writes  ┌───────────────────────────┐
│ page + selection     │ ───────▶ │ files.upload     │ ───────▶ │ ~/work/read-later/inbox/  │
│ extension builds     │  API key │ checks key scope │  wakes   │   <id>.json               │
│ one inbox event      │          │ refuses overwrite│  pod     │ read by read-later-ingest │
└──────────────────────┘          └──────────────────┘          └───────────────────────────┘
```

**The call** (`extension/src/dam-client.ts`)

```
POST <host>/api/trpc/files.upload
Authorization: Bearer pk_…          # scope agents:operate, bound to the one agent
{ agentId, path: "work/read-later/inbox/<id>.json", contentBase64, contentType: "application/json", overwrite: false }
```

**The file** (`extension/src/contract.ts`; the authoritative description is `skills/read-later-ingest/references/contract.md`)

```json
{
  "id": "2026-09-07T06-12-31-482Z-k3f9a",   // unique, time-sortable, also the filename
  "action": "capture",                      // "remove" = retract / archive, "done" = finished reading, "delete" = remove for good
  "source": "browser",
  "url": "https://…",                       // raw; the agent canonicalizes
  "title": "…",
  "selectedText": "…",                      // optional, what the user highlighted
  "html": "<html>…",                        // rendered DOM minus scripts and styles, so paywalled/JS pages work
  "note": "…",                              // optional
  "mustRead": false,
  "capturedAt": "2026-09-07T06:12:31.482Z"
}
```

Nothing flows back to the browser. The extension keeps its own local list of saved URLs (with a `done` flag for finished ones) for the icon state.

**Tested:** a bookmark in Chrome lands as a file in `~/work/read-later/inbox/` on the agent.

## Step 2 · Agent turns an inbox file into a clean article  ✅ works

The code ships as an **Agent Skill** (`skills/read-later-ingest/`), installed onto agents from this repo. No code to copy per agent and no bundled libraries: the script declares its dependencies inline (PEP 723) and `uv run` installs them on first use. uv is in the DAM agent image.

```
skills/read-later-ingest/
  SKILL.md                 when to use it, how to run it, the rules
  scripts/ingest.py       inbox → items   (uv run scripts/ingest.py ~/work/read-later)
  references/contract.md   inbox event, item.json, content.md shapes
```

What `ingest.py` does per inbox file, in order:

1. **Canonicalize + dedupe** — strip fragment, `www.`, tracking params. Same page twice = one item. `done` and `remove` events handled first (mark read / archive).
2. **Extract** — captured HTML → readability → Markdown with images and tables; title/author/date via trafilatura. Fallback: fetch the URL; a PDF response goes through PyMuPDF's layout analysis instead (headings, tables, no OCR, no images), with arXiv's abstract page for metadata. Fails visibly if nothing yields ≥ 80 words.
3. **Save** — `items/<time>-<slug>/item.json` + `content.md`, drop the html, delete the inbox file.

Tested locally on a real 211 KB capture: 2682 words extracted, duplicate capture merged into one item, remove handled, non-JSON file skipped, rerun is a no-op.

**Tested on the agent:** installed via `dam skill source add <repo url>` + `dam skill install <agent> --source <repo url> --name read-later-ingest`; bookmarks in Chrome became items with images, author and date; removes and duplicates accounted for; the agent reports the script output and stops.

## Step 3 · Analyze: TL;DR, category, topics, two scores  ✅ works

Skill `read-later-analyze`. Decided in the grilling of 2026-09-07:

- Analysis describes the **article only**, never the reader, so it runs once and never goes stale. Seven fields: `tldr` (2-4 sentences stating the claim), `keyClaims` (1-3), `contentType`, `category` (one shelf from a hand-edited list), `topics` (2-5 labels from a shared vocabulary, new ones coined only when the main subject has no match), `hardWon` and `grounded` (0-10 with a one-sentence reason, anchors at 0/5/10).
- The reader's interests live in **`~/work/read-later/topics.md`** as weights on topics. `context.md` only says where the agent should look to adjust them (or `NO CONTEXT AVAILABLE`). Categories and topics are orthogonal: shelf vs labels.
- The judgment runs in an **ephemeral DAM Invocation** per article with the model connection only, spawned by `scripts/analyze.mjs` through the platform's `dam-invoke` SDK; the platform validates the result against a JSON Schema derived from the category list. Article text never enters the agent's session, and the evaluator has nothing to exfiltrate to.
- Rubric in `prompts/{tldr,categorize,score}.md`; a copy in `~/work/read-later/prompts/` overrides.

```
node scripts/analyze.mjs --connection ibm-litellm ~/work/read-later
```

## Step 4 · Rank: tonight's queue  ✅ works

Skill `read-later-rank`. First the agent reweighs `topics.md` from the reader's context (skipped when `context.md` is missing or says `NO CONTEXT AVAILABLE`), then `scripts/rank.py`, standard library only, no model. Per item: relevance = mean of the two highest topic weights among its topics; quality = mean of hard-won and grounded; priority = half of each, −1 for over 4000 words, +3 for must-read. Excludes done, archived, unanalyzed, not-an-article, and news older than 14 days. Top three = Read today, next four = Read next, rest = Later. Writes `queue.json`. Changing a weight in `topics.md` and rerunning is the feedback loop; the daily reweigh does it from context, you can do it by hand or in chat.

Tested locally on the three test articles with a stub SDK: ingest → analyze (one injected failure, retried next run, coined topics appended to `topics.md`) → rank; raising `code-review` to 10 lifted the Fowler piece from third to second (its quality scores still keep it below the Uber piece).

**Tested on first-reader (2026-09-07):** a scheduled unattended run did ingest → analyze → rank end to end. Analyze spawned three Invocations in parallel, each with the model connection only; all three returned schema-valid results in about three minutes. Scores: Uber hard-won 9 / grounded 8, KubeStellar 8 / 7, Fowler 5 / 7, each with a reason that names evidence from the text. TL;DRs 70-76 words. Four topics coined (`open-source-maintenance`, `prompt-caching`, `context-engineering`, `pair-programming`) and appended to `topics.md`. Rank put Uber in Read today. The agent reported the script outputs and stopped.

Known gaps from that run: the analyzer put KubeStellar under `ai-and-agents` where the categorize prompt's "reader's angle" rule suggests `engineering`; all topic weights were still 5, so relevance did not separate the items yet.

## Step 5 · Deliver + prune + schedules  ✅ works

- `read-later-deliver`: the page is a **template** (`assets/template.html`: a Kindle-like shelf of book tiles per bucket, score bars under each, click opens a reader pane with TL;DR, claims, score reasons and the full article text) and `render.py` injects the data from `queue.json` plus each item's `item.json` and `content.md`. Self-contained HTML, no CDN; light and dark. The agent publishes it once with `create_artifact` and then `update_artifact`s the same artifact whenever the data hash changes (`deliver.json`). Unchanged → no new version. Private by default. The page cannot call the agent back (DAM's artifact bridge is planned, not built), so read/remove actions go through the extension. `queue.md` is gone; `queue.json` is the rank → deliver contract.
- Extension: new **Mark as read** menu → `action: "done"`; ingest sets status `done`. Un-bookmark stays `remove` → `archived`.
- `read-later-prune` (weekly): moves `done` → `done/`, `archived`/not-an-article/unread-30-days → `archive/`; the agent then weighs new labels and merges duplicates in `topics.md`.
- Reweighing moved into `read-later-rank`, every run: read `context.md` (pointer to the reader's context, or `NO CONTEXT AVAILABLE` → skip), adjust weights, then rank.
- Schedules: `read-later-refresh` at 18:00 Prague (ingest → analyze → rank → deliver; named for what it does, the cadence can change), `read-later-prune` weekly. The old `daily` schedule is gone.
- `INSTALL.md` at the repo root: the whole setup for a new agent, from the CLI or by the agent itself (the platform MCP exposes `install_skill` and `create_schedule`).

**Tested on a fresh agent (2026-09-08):** `read-later-test` was created with the CLI and set up by following INSTALL.md step by step (model connection, network preset, five skills, `context.md` with `NO CONTEXT AVAILABLE`, the three test articles seeded into the inbox, both schedules). One scheduled run did ingest (3 extracted) → analyze (3 Invocations, scores 8/7, 8/7, 5/7, three topics coined) → rank (reweigh skipped on the marker, KubeStellar in Read today on the tie-break) → deliver (artifact `Read later` created, version 1, id stored in `deliver.json`). The agent reported and stopped. One correction to INSTALL.md came out of it: the CLI has no `--weekly`, the prune schedule uses `--daily 09:00 --weekdays SU`. Still open from this run: the analyzer put both the Uber and KubeStellar pieces under `ai-and-agents`; all weights are 5 until someone sets them.

**Library page verified (2026-09-08):** after the redesign, a refresh on the test agent published version 2 of the same artifact (67 KB, `text/html`, three articles with full text). The two refreshes after it reported `changed: false` and did not republish. A second design pass (segmented 0-10 bars with the value beside them, no topic line under tiles, no footnote, Tonight holds three picks) went out as version 3.

**Second rehearsal (2026-09-08, `read-later-test2`):** a brand-new agent set up by following INSTALL.md again, this time with only the doc's chat phrase, *"ingest, analyze, rank and deliver read later"*, as the run's instruction. It passed: 3 ingested, 3 analyzed, 3 ranked, artifact created (version 1), report and stop. The skills carry the run without a detailed prompt. Two findings: `dam skill source add` errors when the source is already registered (documented), and a temporary `--every 10m` trigger keeps running until deleted, each tick a short agent turn that ends in "unchanged" (a note for testers, not for INSTALL.md).

**Highlights verified on a temporary agent (2026-09-08):** `read-later-hl-test` was created fresh, the five skills copied from the `feat/highlights` branch, two captures seeded. One refresh turn (`claude -p` over SSH) did ingest → analyze → rank → deliver and created the artifact. A *Done reading* paste with two highlights produced from the published page (jsdom driving the template): the agent wrote `highlights.json` verbatim into the item folder and filed the `done` event through ingest. A *Copy for chat* paste on the unread KubeStellar item stored two highlights and left the status alone. Rank + deliver then published version 2 of the same artifact; loading that page in a fresh browser with no localStorage showed both highlights as synced marks, the note on hover. The done item left the queue as designed. Verified in a real browser afterwards (2026-09-09): the DAM viewer is an `about:srcdoc` frame with a null origin, so localStorage and `history.replaceState` throw. The page now guards both; highlights live in memory while the page is open and a warning says to copy them before leaving. Better storage support is a DAM change for the next iteration.

**Both install paths rehearsed on fresh agents (2026-09-09):** `rl-cli-test` was set up from the CLI by following INSTALL.md section B literally (five skills, `context.md` with the marker, two schedules). `rl-self-test` got the single chat line from section A pointing at the branch's INSTALL.md; with only its platform tools it installed the five skills onto itself at the same commit, created `inbox/`, wrote the marker `context.md` after finding no reader files, ran ingest once for the dependencies, created both schedules with the task texts verbatim (checked with `dam schedule get`), skipped the git step because `~/work` is not a repo, and reported what remained for the owner. One seeded bookmark and the "ingest, analyze, rank and deliver read later" phrase then produced a `Read later` artifact on each agent.

## Step 6 · Slack as a second producer  ✅ built, on guido

`read-later-slack`: `scripts/slack.py` searches `is:saved has:link` through the MCP server at `mcp.slack.com` (a script on the agent can call it directly; the gateway adds the token, verified 2026-09-09) and writes one inbox event per new link in a message the reader saved with Slack's **Save for later**. No judgment: saving is the explicit action. Unreachable links (logins, social) land in `slack/skipped.json` and rank lists them under *Needs attention*; deliver shows "shared by X in #channel" and the poster's words in the reader pane. The first version (PR #9) swept every shared link in every channel and DM and had the agent judge a numbered shortlist; a dry run on the real workspace gave 43 candidates from one week, and the live run captured 23 links, too many of them noise. Reduced to saved messages only the next day.

## Step 7 · Videos and podcasts  ✅ works

Bookmarking a YouTube video or a Spotify episode used to fail ingest (no 80 words of article) or pass with comment noise. Now `ingest.py` checks the page's Open Graph type before readability: `video.*` → `kind: "video"`, `music.*` (Spotify labels episodes `music.song`) → `kind: "audio"`; JSON-LD `VideoObject`/`PodcastEpisode` only when the page declares no type and no article. The item keeps what the page declares: title, the channel or show as `author`, date, `durationSeconds`, cover `image`, and the publisher's description as `content.md` (YouTube's full description comes from the player response the page embeds; the meta tag is truncated). No transcript, no per-site API, no change to the extension or the inbox event: the captured DOM already carries these tags, so Vimeo or Apple Podcasts pages work the same way.

Downstream: analyze knows the text is a description (`contentType` `video`/`podcast`, `ANALYSIS_VERSION` 3), rank takes minutes from the duration and applies the long penalty above 18 minutes for everything, the page shows `video · 19 min` instead of a word count. Spotify's `si`, `nd` and `dlsi` share parameters are stripped on canonicalization.

**Tested locally:** a headless-Chrome DOM of a YouTube video and of a Spotify episode, plus a fetched Wikipedia article, in one inbox: video (3Blue1Brown, 2017-10-05, 1120 s, 480-word description), podcast (Lex Fridman Podcast, 2026-02-12, 12318 s, 271 words), article via readability as before; rank and render carry kind and minutes through.

## Step 8 · Cheaper refreshes, better media items  ✅ built

A review on a fresh agent (2026-09-10/11) found where a refresh loses time and where video and podcast items fall short. Fixed:

- **uv bootstrap.** The image's lazy `uv` shim installs uv through mise, which verifies GitHub attestations via `tuf-repo-cdn.sigstore.dev`; outside the `trusted` preset that host is blocked and the shim loops for good (an ingest hung 25 minutes). INSTALL.md now lists the two hosts. The run command sets `UV_CACHE_DIR=~/work/.cache/uv`, because the default cache under `/tmp` is lost on every hibernation (measured: 199 s and 316 MB per wake). PyMuPDF moved out of the script's dependencies into `pdf_to_md.py`, a subprocess run on the first PDF only; agents without PDFs download about 30 MB instead of 316.
- **Analyze on a bad day.** After three Invocation failures in a row with no success, `analyze.mjs` stops spawning and prints `model connection unavailable`; the skill tells the agent to report that line and move on, not to diagnose the platform (guido once spent 51 minutes and 72 steps on exactly that). A version bump redoes old analyses only for the kinds it changed (`REDO_KINDS`), so a prompt tweak for audio items does not re-judge thirty articles.
- **Media descriptions.** Spotify's meta tags hold one run-on string; ingest now restores line breaks (sentence ends, chapter timestamps, ALL-CAPS headings, URLs glued to the next sentence), cuts the trailer blocks (sponsors, social, episode links) into `item.json.links`, and keeps chapter lines as hard breaks so the page shows them as lines. When the description links a transcript on the publisher's site, ingest fetches it into `transcript.md` and the analyzer judges that instead of the blurb. The cover image reaches the page: media tiles and the reader header show it.
- **Topics.** The categorize prompt caps coinage at one new label per article and forbids product, person and place names; four test items had coined twelve labels (`helix`, `vim`, `abraham-lincoln`).
- **YouTube.** `youtu.be/ID`, `m.youtube.com`, `shorts/ID`, `&t=`, `&list=` all canonicalize to `https://youtube.com/watch?v=ID`; the same rule in `slack.py`.

## Where things stand

- Steps 1-7 work end to end on two agents: `first-reader` (your bookmarks) and `read-later-test` (the INSTALL.md rehearsal). Both run `read-later-refresh` at 18:00 Prague and `read-later-prune` on Sundays.
- Marking as read: *Mark as read* in the extension, or tell the agent in chat; either way it is a `done` event through ingest. The artifact cannot call the agent back until DAM ships its artifact bridge.
- Highlights: the reader pane has a highlighter (toggle, select text, click a mark for a note or to remove it). Highlights stay in the browser until *Copy for chat* or *Done reading* puts the content of `highlights.json` on the clipboard and you paste it to the agent; the agent writes the file into the item folder verbatim (no ingest) and the next deliver shows them on every device. Until the bridge, that paste is the only path, so highlights made on one device reach another only after you have sent them. In DAM's viewer they also do not survive a reload, so send before you leave; a DAM change for storage is the next step.
- Open polish, all small: the analyzer files engineering-flavoured agent pieces under `ai-and-agents`; every topic weight is still 5 until you or the host agent sets them; `first-reader` has a stray `context.md` and `index.json` from earlier versions, harmless.

## Next

1. Set a first pass of topic weights, or move to an agent that knows you (Guido) and point `context.md` at its memory files so the nightly reweigh does it.
2. Point the extension at that agent (new key bound to it) and use *Mark as read* for a week; check that `done/` fills and Tonight changes.
3. Feed what you finish reading back into the weights (topics of `done/` items drift up).
4. When DAM's artifact bridge ships: the page sends the highlight event itself, on every change. One transport function in the template, nothing on the agent.
5. Use Save for later in Slack for a week; tune the drop and skip lists in `slack.py` if noise gets through. Then the multi-user template; a name.

