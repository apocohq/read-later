import { latestAnalysis, titleOf } from "../domain/index.js";
import type { Item, QueueEntry } from "../domain/index.js";
import { BUCKET_ORDER, BUCKET_TITLES } from "./render-markdown.js";

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

/**
 * One self-contained HTML page for the DAM artifact library. Deterministic:
 * rendered from files by code, so regenerating it costs no model tokens.
 * TODO: reader view per item (content.md rendered clean), feedback links.
 */
export function renderArtifactHtml(entries: QueueEntry[], items: Map<string, Item>): string {
  const sections = BUCKET_ORDER.map((bucket) => {
    const cards = entries
      .filter((e) => e.bucket === bucket)
      .map((e) => items.get(e.itemId))
      .filter((i): i is Item => Boolean(i))
      .map((item) => {
        const a = latestAnalysis(item);
        const minutes = a ? `${a.estimatedReadingMinutes} min` : "";
        return `<article>
  <h3><a href="${esc(item.canonicalUrl)}" target="_blank" rel="noopener">${esc(titleOf(item))}</a></h3>
  <p class="meta">${esc(new URL(item.canonicalUrl).hostname)} · ${esc(minutes)} · confidence ${a ? Math.round(a.confidence * 100) : 0}%</p>
  <p>${esc(a?.tldr ?? "")}</p>
</article>`;
      });
    return `<section><h2>${BUCKET_TITLES[bucket]}</h2>${cards.join("\n") || "<p class=\"empty\">nothing</p>"}</section>`;
  });

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DAM Read Later</title>
<style>
  body{max-width:42rem;margin:2rem auto;padding:0 1rem;font:16px/1.55 system-ui,sans-serif;color:#1a1a1a;background:#fbfaf7}
  h1{font-weight:600}h2{margin-top:2.5rem;font-size:1rem;text-transform:uppercase;letter-spacing:.08em;color:#666}
  article{padding:1rem 0;border-top:1px solid #e6e2d8}h3{margin:0 0 .25rem;font-size:1.15rem}a{color:inherit}
  .meta,.empty{color:#777;font-size:.9rem}
</style></head>
<body><h1>DAM Read Later</h1><p class="meta">Generated ${esc(new Date().toISOString())}</p>
${sections.join("\n")}
</body></html>
`;
}
