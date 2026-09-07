# Evaluate

Judge the piece for this one reader, using the reader context above. Every score is an integer from 0 to 5. Score what the text supports, not what the title promises.

Value dimensions (higher is better):
- `relevance`: how directly it bears on what the reader is working on or deciding now. 0 = unrelated, 3 = adjacent, 5 = about their current problem.
- `novelty`: how much is new to a reader with the context above. 0 = they know all of this, 5 = a genuinely new idea, result or framing.
- `hardWon`: how much of it comes from real experience, data or building, versus restating common knowledge. 0 = recycled, 5 = first-hand, specific, costly to obtain.
- `evidence`: how well claims are supported. 0 = assertions only, 3 = examples and anecdotes, 5 = data, methodology, or reproducible detail.
- `actionability`: whether the reader can do something differently after reading. 0 = nothing to act on, 5 = a concrete change they could make this week.
- `urgency`: whether the value decays. 0 = evergreen, 5 = worthless in a month.

Cost dimensions (higher is worse):
- `redundancy`: overlap with what the reader already knows or has saved, per the context. 0 = none, 5 = a rehash.
- `hypeFomo`: how much the piece runs on excitement, fear of missing out, or trend-chasing rather than substance.
- `promotionality`: how much it exists to sell a product, service, or the author.
- `readingCost`: time and effort to extract the value. 0 = a 3-minute read that pays off fast, 5 = long, dense, or padded relative to its payoff.

Then decide:
- `recommendation`, one of: `read_today` (drop what you are doing), `read_next` (worth the full read soon), `skim` (headings and one section are enough), `summary_enough` (the TL;DR above is all they need), `filter_out` (no value for this reader).
- `whyItMatters`: one or two sentences addressed to the reader, naming the specific connection to their context. If there is no connection, say so plainly.
- `weaknesses`: 0 to 3 short items: what the piece gets wrong, leaves out, or overstates.
- `readingMinutes`: honest estimate for a careful read.
- `confidence`: 0 to 1, how sure you are of the recommendation. Lower it when the context is thin or the text is truncated.

Rules:
- A `mustRead` flag on the item means the reader has already decided to read it. Still score honestly, but never recommend `filter_out` or `summary_enough` for it.
- `selectedText` and `note` on a capture are the reader's own signal about why they saved it. Weigh them heavily for relevance.
- Be harsh. Most saved articles deserve `skim` or `summary_enough`. `read_today` is for perhaps one item in twenty.
