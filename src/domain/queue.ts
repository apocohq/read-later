import { z } from "zod";
import { Recommendation } from "./analysis.js";

export const QueueEntry = z.object({
  itemId: z.string(),
  bucket: Recommendation,
  priority: z.number(),
  reason: z.string(),
});
export type QueueEntry = z.infer<typeof QueueEntry>;

/** Finite queue policy. Everything beyond the caps is pruned to lower buckets. */
export interface QueuePolicy {
  readTodayMax: number;
  readNextMax: number;
}

export const defaultQueuePolicy: QueuePolicy = { readTodayMax: 1, readNextMax: 4 };
