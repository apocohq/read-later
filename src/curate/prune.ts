import { latestAnalysis, mustRead } from "../domain/index.js";
import type { Item } from "../domain/index.js";

/**
 * The queue is finite on purpose. Pruning archives what went stale instead of
 * letting skeletons pile up. Archiving never deletes; items stay searchable
 * and restorable.
 */
export interface PrunePolicy {
  /** Return true when the item should be archived now. */
  shouldArchive(item: Item, now: Date): boolean;
}

export interface PruneOptions {
  /** Days a ranked-but-unread item stays before it is archived. */
  maxAgeDays: number;
  /** Buckets that are archived immediately after processing. */
  archiveBuckets: ReadonlyArray<"summary_enough" | "filter_out">;
}

export const defaultPruneOptions: PruneOptions = { maxAgeDays: 14, archiveBuckets: ["filter_out"] };

export class DefaultPrunePolicy implements PrunePolicy {
  constructor(private readonly options: PruneOptions = defaultPruneOptions) {}

  shouldArchive(item: Item, now: Date): boolean {
    if (item.status !== "ranked" || mustRead(item)) return false;
    const analysis = latestAnalysis(item);
    if (!analysis) return false;
    if ((this.options.archiveBuckets as readonly string[]).includes(analysis.recommendation)) return true;
    if (analysis.expiresAt && new Date(analysis.expiresAt) < now) return true;
    const ageDays = (now.getTime() - new Date(item.updatedAt).getTime()) / 86_400_000;
    return ageDays > this.options.maxAgeDays;
  }
}

export function prune(items: Item[], policy: PrunePolicy, now = new Date()): Item[] {
  return items.map((item) =>
    policy.shouldArchive(item, now) ? { ...item, status: "archived", updatedAt: now.toISOString() } : item,
  );
}
