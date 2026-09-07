import { titleOf } from "../domain/index.js";
import type { Item, QueueEntry, Recommendation } from "../domain/index.js";

export const BUCKET_TITLES: Record<Recommendation, string> = {
  read_today: "Read today",
  read_next: "Read next",
  skim: "Skim selected sections",
  summary_enough: "Summary is enough",
  filter_out: "Filtered out",
};

export const BUCKET_ORDER = Object.keys(BUCKET_TITLES) as Recommendation[];

/** The Slack-friendly view: a short menu to choose from, not a verdict. */
export function renderQueueMarkdown(entries: QueueEntry[], items: Map<string, Item>): string {
  const lines = ["# Reading queue", ""];
  for (const bucket of BUCKET_ORDER) {
    const inBucket = entries.filter((e) => e.bucket === bucket);
    lines.push(`## ${BUCKET_TITLES[bucket]}`, "");
    if (inBucket.length === 0) lines.push("_nothing_");
    for (const e of inBucket) {
      const item = items.get(e.itemId);
      if (!item) continue;
      lines.push(`- [${titleOf(item)}](${item.canonicalUrl}) — ${e.reason}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}
