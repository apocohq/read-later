import { createHash } from "node:crypto";
import { JSDOM } from "jsdom";
import { Defuddle } from "defuddle/node";
import type { Content, Item } from "../domain/index.js";

/**
 * A way to obtain readable content for an item. Tried in order; the first
 * one that returns content wins. Returning undefined means "not from me".
 */
export interface ContentSource {
  readonly name: string;
  acquire(item: Item): Promise<Content | undefined>;
}

export const hashContent = (markdown: string): string =>
  createHash("sha256").update(markdown).digest("hex").slice(0, 16);

const MIN_WORDS = 80;

/** Reader-view extraction of an HTML document to Markdown; undefined when too thin to be an article. */
async function extract(html: string, url: string): Promise<Omit<Content, "extractedBy" | "extractedAt"> | undefined> {
  const dom = new JSDOM(html, { url });
  const parsed = await Defuddle(dom, url, { markdown: true });
  if (!parsed.content || parsed.wordCount < MIN_WORDS) return undefined;
  return {
    markdown: parsed.content,
    contentHash: hashContent(parsed.content),
    title: parsed.title || undefined,
    author: parsed.author || undefined,
    published: parsed.published || undefined,
    wordCount: parsed.wordCount,
  };
}

/** The browser saw the page as the principal did: logged in, JS rendered. Preferred when present. */
export class CaptureHtmlContentSource implements ContentSource {
  readonly name = "capture-html";
  async acquire(item: Item): Promise<Content | undefined> {
    const html = item.captures.map((c) => c.html).find((h) => h && h.length > 0);
    if (!html) return undefined;
    const extracted = await extract(html, item.canonicalUrl);
    return extracted && { ...extracted, extractedBy: "capture", extractedAt: new Date().toISOString() };
  }
}

/**
 * Server-side fetch + reader-view extraction (Defuddle, the Obsidian clipper's
 * parser) to Markdown. Goes through HTTPS_PROXY when set, so it works inside
 * the DAM pod. Gives up quietly on non-HTML, login walls, and thin pages.
 */
export class FetchContentSource implements ContentSource {
  readonly name = "fetch";
  constructor(private readonly timeoutMs = 20_000) {}

  async acquire(item: Item): Promise<Content | undefined> {
    const res = await fetch(item.canonicalUrl, {
      signal: AbortSignal.timeout(this.timeoutMs),
      headers: { "user-agent": "Mozilla/5.0 (compatible; ReadLater/0.1)", accept: "text/html,*/*;q=0.8" },
      redirect: "follow",
    }).catch(() => undefined);
    if (!res?.ok || !(res.headers.get("content-type") ?? "").includes("html")) return undefined;

    const extracted = await extract(await res.text(), item.canonicalUrl);
    return extracted && { ...extracted, extractedBy: "fetch", extractedAt: new Date().toISOString() };
  }
}

/** Falls back to text the capturer supplied (extension Readability, Slack text). */
export class CaptureTextContentSource implements ContentSource {
  readonly name = "capture";
  async acquire(item: Item): Promise<Content | undefined> {
    const text = item.captures.map((c) => c.text).find((t) => t && t.trim().length > 0);
    if (!text) return undefined;
    return {
      markdown: text,
      extractedBy: "capture",
      contentHash: hashContent(text),
      extractedAt: new Date().toISOString(),
      wordCount: text.split(/\s+/).length,
    };
  }
}

export async function acquireContent(sources: ContentSource[], item: Item): Promise<Content | undefined> {
  for (const source of sources) {
    const content = await source.acquire(item);
    if (content) return content;
  }
  return undefined;
}
