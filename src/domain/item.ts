import { z } from "zod";
import { CaptureEvent } from "./capture.js";
import { Analysis } from "./analysis.js";

export const ItemStatus = z.enum([
  "captured",
  "processing",
  "ranked",
  "read",
  "archived",
  "failed",
]);
export type ItemStatus = z.infer<typeof ItemStatus>;

export const ContentProvenance = z.enum(["fetch", "capture"]);
export type ContentProvenance = z.infer<typeof ContentProvenance>;

/** Pure text and images. Rendered as `content.md` with frontmatter; consumed by every surface. */
export const Content = z.object({
  markdown: z.string(),
  extractedBy: ContentProvenance,
  contentHash: z.string(),
  extractedAt: z.string().datetime(),
  title: z.string().optional(),
  author: z.string().optional(),
  published: z.string().optional(),
  wordCount: z.number().int().nonnegative().optional(),
});
export type Content = z.infer<typeof Content>;

/**
 * Aggregate for one canonical URL. Persisted as a folder under `items/<id>/`:
 * item.json (this minus content), content.md, analysis.<version>.json.
 */
export const Item = z.object({
  id: z.string(),
  canonicalUrl: z.string().url(),
  status: ItemStatus,
  captures: z.array(CaptureEvent).min(1),
  content: Content.optional(),
  analyses: z.array(Analysis),
  failure: z.string().optional(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
});
export type Item = z.infer<typeof Item>;

export const titleOf = (item: Item): string =>
  item.content?.title ?? item.captures.find((c) => c.title)?.title ?? item.canonicalUrl;
export const mustRead = (item: Item): boolean => item.captures.some((c) => c.mustRead);
export const latestAnalysis = (item: Item): Analysis | undefined => item.analyses.at(-1);
