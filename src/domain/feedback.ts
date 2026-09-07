import { z } from "zod";

export const FeedbackAction = z.enum([
  "read",
  "useful",
  "not_useful",
  "misranked",
  "later",
  "summary_enough",
  "must_read",
  "archive",
  "restore",
]);
export type FeedbackAction = z.infer<typeof FeedbackAction>;

/** One line in feedback.jsonl. Explicit outcomes are the learning signal. */
export const FeedbackEvent = z.object({
  itemId: z.string(),
  action: FeedbackAction,
  reason: z.string().optional(),
  createdAt: z.string().datetime(),
});
export type FeedbackEvent = z.infer<typeof FeedbackEvent>;
