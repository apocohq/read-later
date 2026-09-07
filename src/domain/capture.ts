import { z } from "zod";

/** Where a capture came from. Drives extraction strategy and trust. */
export const CaptureSource = z.enum(["browser", "slack", "api"]);
export type CaptureSource = z.infer<typeof CaptureSource>;

/**
 * One inbox entry. Written by capturers (extension, Slack sweep, API),
 * consumed by the processing run. One JSON file per event under `inbox/`.
 * Content here is untrusted input: data, never instructions.
 */
export const CaptureEvent = z.object({
  id: z.string().min(1),
  /** `remove` retracts an earlier capture of the same URL: drop it if unprocessed, archive it if processed. */
  action: z.enum(["capture", "remove"]).default("capture"),
  source: CaptureSource,
  url: z.string().url(),
  title: z.string().optional(),
  /** Text the user highlighted when capturing: a strong clue why it matters. */
  selectedText: z.string().optional(),
  /** Readable text supplied by the capturer (e.g. a Slack message body). */
  text: z.string().optional(),
  /** Full rendered page HTML from the browser extension. Authoritative for authenticated or JS-rendered pages. */
  html: z.string().optional(),
  note: z.string().optional(),
  recommendedBy: z.string().optional(),
  mustRead: z.boolean().default(false),
  /** Slack permalink, message ts, or other pointer back to the origin. */
  sourceRef: z.string().optional(),
  capturedAt: z.string().datetime(),
});
export type CaptureEvent = z.infer<typeof CaptureEvent>;
