import { z } from "zod";

export const ContentType = z.enum([
  "hard_won",
  "proven",
  "news",
  "synthesis",
  "opinion",
  "promotional",
]);
export type ContentType = z.infer<typeof ContentType>;

export const Recommendation = z.enum([
  "read_today",
  "read_next",
  "skim",
  "summary_enough",
  "filter_out",
]);
export type Recommendation = z.infer<typeof Recommendation>;

const score = z.number().min(0).max(5);

/** Interpretable 0-5 dimensions. Exist for explanation, not as ground truth. */
export const Scores = z.object({
  relevance: score,
  novelty: score,
  hardWon: score,
  evidence: score,
  actionability: score,
  sourceProximity: score,
  urgency: score,
  redundancy: score,
  hypeFomo: score,
  promotionality: score,
  readingCost: score,
});
export type Scores = z.infer<typeof Scores>;

/** Versioned, append-only model output for one item. */
export const Analysis = z.object({
  analysisVersion: z.string(),
  contentType: ContentType,
  topics: z.array(z.string()),
  tldr: z.string(),
  mainClaims: z.array(z.string()),
  newInsights: z.array(z.string()),
  supportingEvidence: z.array(z.string()),
  weaknesses: z.array(z.string()),
  /** Which profile/context fragments influenced the judgment. */
  contextReasons: z.array(z.string()),
  scores: Scores,
  recommendation: Recommendation,
  confidence: z.number().min(0).max(1),
  estimatedReadingMinutes: z.number().int().nonnegative(),
  expiresAt: z.string().datetime().optional(),
  createdAt: z.string().datetime(),
});
export type Analysis = z.infer<typeof Analysis>;
