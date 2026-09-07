import { latestAnalysis, mustRead } from "../domain/index.js";
import type { Item, QueueEntry, QueuePolicy, Recommendation, Scores } from "../domain/index.js";

/** Weights from the brief. Configurable, not sacred. */
export const WEIGHTS: Record<keyof Pick<Scores, "relevance" | "novelty" | "hardWon" | "evidence" | "actionability" | "sourceProximity">, number> = {
  relevance: 0.25,
  novelty: 0.2,
  hardWon: 0.2,
  evidence: 0.15,
  actionability: 0.1,
  sourceProximity: 0.1,
};

const PENALTY_WEIGHT = 0.25;

export function priorityOf(item: Item): number {
  const a = latestAnalysis(item);
  if (!a) return -Infinity;
  const s = a.scores;
  const base = (Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[]).reduce((sum, k) => sum + WEIGHTS[k] * s[k], 0);
  const penalty = PENALTY_WEIGHT * (s.redundancy + s.hypeFomo + s.promotionality + s.readingCost);
  const boost = (mustRead(item) ? 10 : 0) + 0.2 * s.urgency;
  return base - penalty + boost;
}

/** Orders ranked items and applies the finite-queue caps. */
export function rankQueue(items: Item[], policy: QueuePolicy): QueueEntry[] {
  const ranked = items
    .filter((i) => i.status === "ranked" && latestAnalysis(i))
    .map((i) => ({ item: i, priority: priorityOf(i) }))
    .sort((a, b) => b.priority - a.priority);

  let today = 0;
  let next = 0;
  return ranked.map(({ item, priority }) => {
    const analysis = latestAnalysis(item)!;
    let bucket: Recommendation = analysis.recommendation;
    if (mustRead(item)) bucket = "read_today";
    if (bucket === "read_today" && today++ >= policy.readTodayMax) bucket = "read_next";
    if (bucket === "read_next" && next++ >= policy.readNextMax) bucket = "skim";
    return { itemId: item.id, bucket, priority, reason: analysis.tldr };
  });
}
