# Categorize

Set `contentType`, one of: `article`, `paper`, `announcement`, `tutorial`, `opinion`, `reference`, `thread`, `transcript`, `not-an-article`.

Set `category`, exactly one from this list. Pick the reader's angle, not the author's: an article about AI agents that is really about how to run an engineering team goes under leadership.

- `ai-and-agents`: models, agents, prompting, evaluation, the AI tooling landscape
- `engineering`: software craft, architecture, testing, infrastructure, developer productivity
- `product`: product management, UX, discovery, what to build
- `business-and-strategy`: markets, positioning, pricing, company building, competitors
- `leadership`: managing people and teams, hiring, culture, organisation design
- `research`: academic or industrial research results and methods
- `news`: events, releases, funding, industry moves; value decays fast
- `personal`: health, family, hobbies, finance, life
- `other`: nothing above fits

Set `topics`: 2 to 5 lowercase tags, specific nouns a reader would search for later (`code-review`, `mcp`, `token-cost`), not the category repeated.

To change this list for one reader, put an edited copy of this file at `<state dir>/prompts/categorize.md`. Keep the category ids stable once items use them.
