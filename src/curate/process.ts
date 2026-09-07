import { createHash } from "node:crypto";
import type { CaptureEvent, Item } from "../domain/index.js";
import { defaultQueuePolicy } from "../domain/index.js";
import type { RepoStore } from "../store/repo-store.js";
import { canonicalizeUrl } from "./canonicalize.js";
import { acquireContent, type ContentSource } from "./content.js";
import { assembleContext, type ContextProvider } from "./context.js";
import type { Evaluator } from "./evaluate.js";
import { prune, type PrunePolicy } from "./prune.js";
import { rankQueue } from "./rank.js";
import { renderQueueMarkdown } from "../consume/render-markdown.js";
import { renderArtifactHtml } from "../consume/render-artifact.js";

export interface ProcessDeps {
  store: RepoStore;
  contentSources: ContentSource[];
  contextProviders: ContextProvider[];
  evaluator: Evaluator;
  prunePolicy: PrunePolicy;
  now?: () => string;
}

const itemIdFor = (canonicalUrl: string): string =>
  createHash("sha256").update(canonicalUrl).digest("hex").slice(0, 12);

/** Attach a capture to its item, creating the item on first sight. */
async function upsertItem(store: RepoStore, capture: CaptureEvent, now: string): Promise<Item> {
  const canonicalUrl = canonicalizeUrl(capture.url);
  const existingId = await store.index.lookup(canonicalUrl);
  const existing = existingId ? await store.items.get(existingId) : undefined;
  if (existing) {
    return { ...existing, captures: [...existing.captures, capture], updatedAt: now };
  }
  const id = itemIdFor(canonicalUrl);
  await store.index.set(canonicalUrl, id);
  return { id, canonicalUrl, status: "captured", captures: [capture], analyses: [], createdAt: now, updatedAt: now };
}

/**
 * Per URL, the last event in the batch decides. A page can be saved, retracted,
 * and saved again between two runs, so a `remove` retracts only the captures
 * that precede it; a capture after it survives and the item is not archived.
 * Retracted captures never reach the fetch or the evaluator. A processed item
 * is archived, never deleted.
 */
async function applyRemovals(store: RepoStore, events: CaptureEvent[], now: () => string): Promise<CaptureEvent[]> {
  if (!events.some((e) => e.action === "remove")) return events;

  const byUrl = new Map<string, CaptureEvent[]>();
  for (const event of events) {
    const url = canonicalizeUrl(event.url);
    byUrl.set(url, [...(byUrl.get(url) ?? []), event]);
  }

  const survivors: CaptureEvent[] = [];
  for (const [url, group] of byUrl) {
    // `capturedAt` is the only ordering the sources agree on; inbox filenames
    // derive from it but an event may arrive with a caller-supplied id. On a tie
    // the remove sorts first, so an equally stamped capture survives: dropping
    // content the principal asked for is worse than keeping one they retracted.
    const ordered = [...group].sort(
      (a, b) => a.capturedAt.localeCompare(b.capturedAt) || Number(a.action === "capture") - Number(b.action === "capture"),
    );
    let lastRemove = -1;
    ordered.forEach((event, i) => {
      if (event.action === "remove") lastRemove = i;
    });

    for (const [i, event] of ordered.entries()) {
      if (event.action === "capture" && i > lastRemove) survivors.push(event);
      else await store.inbox.remove(event.id);
    }
    if (lastRemove === ordered.length - 1) await archiveItem(store, url, ordered[lastRemove]!, now);
  }
  return survivors;
}

/** A retraction that nothing supersedes: archive the item if it was already processed. */
async function archiveItem(store: RepoStore, canonicalUrl: string, remove: CaptureEvent, now: () => string): Promise<void> {
  const itemId = await store.index.lookup(canonicalUrl);
  const item = itemId ? await store.items.get(itemId) : undefined;
  if (!item || item.status === "archived") return;
  await store.items.save({ ...item, status: "archived", updatedAt: now() });
  await store.feedback.append({ itemId: item.id, action: "archive", reason: `removed via ${remove.source}`, createdAt: now() });
}

/** Drain the inbox: one capture at a time, each step idempotent. */
export async function processInbox(deps: ProcessDeps): Promise<{ processed: number; failed: number }> {
  const now = deps.now ?? (() => new Date().toISOString());
  let processed = 0;
  let failed = 0;

  for (const capture of await applyRemovals(deps.store, await deps.store.inbox.list(), now)) {
    let item = await upsertItem(deps.store, capture, now());
    try {
      if (!item.content) item = { ...item, content: await acquireContent(deps.contentSources, item) };
      if (!item.content) throw new Error("no content source could extract this item");
      const alreadyAnalyzed = item.analyses.length > 0 && item.captures.length > 1;
      if (!alreadyAnalyzed) {
        const context = await assembleContext(deps.contextProviders);
        const analysis = await deps.evaluator.evaluate({ content: item.content, captures: item.captures, context });
        item = { ...item, analyses: [...item.analyses, analysis] };
      }
      item = { ...item, status: "ranked", failure: undefined, updatedAt: now() };
      processed++;
    } catch (err) {
      item = { ...item, status: "failed", failure: String(err), updatedAt: now() };
      failed++;
    }
    await deps.store.items.save(item);
    await deps.store.inbox.remove(capture.id);
  }

  await pruneItems(deps.store, deps.prunePolicy);
  await writeQueue(deps.store);
  return { processed, failed };
}

async function pruneItems(store: RepoStore, policy: PrunePolicy): Promise<void> {
  const before = await store.items.list();
  const after = prune(before, policy);
  await Promise.all(after.filter((item, i) => item !== before[i]).map((item) => store.items.save(item)));
}

export async function writeQueue(store: RepoStore): Promise<void> {
  const items = await store.items.list();
  const entries = rankQueue(items, defaultQueuePolicy);
  const byId = new Map(items.map((i) => [i.id, i]));
  await store.queue.write(entries, renderQueueMarkdown(entries, byId), renderArtifactHtml(entries, byId));
}
