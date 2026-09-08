# Content type, category, topics

`contentType`, one of: `article`, `paper`, `announcement`, `news`, `tutorial`, `opinion`, `reference`, `thread`, `transcript`, `video`, `podcast`, `not-an-article`.

`category`: exactly one from the CATEGORIES list in the vocabulary below. It is the shelf the reader would file this under, chosen by the reader's angle, not the author's: a piece about AI agents whose real lesson is how to run a team goes under `leadership`.

`topics`: 2 to 5 labels for the subjects the text is actually about. Form: lowercase, singular, hyphenated noun phrase (`code-review`, `agent-cost`, `mcp`). Then:
- Reuse a label from the TOPICS list in the vocabulary whenever it fits. Do not coin a near-synonym of an existing label.
- Coin a new label only when the article's main subject has no match in the list. Make it specific enough to be useful and general enough to be reused (`token-cost`, not `uber-token-cost-2026`).
- Never use the category name as a topic.
