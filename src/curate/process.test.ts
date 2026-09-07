import assert from "node:assert/strict";
import { test } from "node:test";
import type { Analysis, CaptureEvent, Content, FeedbackEvent, Item } from "../domain/index.js";
import type { RepoStore } from "../store/repo-store.js";
import type { ContentSource } from "./content.js";
import { StubEvaluator } from "./evaluate.js";
import { processInbox, type ProcessDeps } from "./process.js";

const AT = "2026-01-01T00:00:00.000Z";

/** In-memory store: only the parts the drain touches, so each test states its own preconditions. */
function fakeStore(events: CaptureEvent[], seed: Item[] = []) {
  const inbox = new Map(events.map((e) => [e.id, e]));
  const items = new Map(seed.map((i) => [i.id, i]));
  const index = new Map(seed.map((i) => [i.canonicalUrl, i.id]));
  const feedback: FeedbackEvent[] = [];
  const store: RepoStore = {
    inbox: {
      list: async () => [...inbox.values()],
      add: async (e) => void inbox.set(e.id, e),
      remove: async (id) => void inbox.delete(id),
    },
    items: {
      get: async (id) => items.get(id),
      save: async (item) => void items.set(item.id, item),
      list: async () => [...items.values()],
    },
    index: { lookup: async (url) => index.get(url), set: async (url, id) => void index.set(url, id) },
    feedback: { append: async (e) => void feedback.push(e), list: async () => feedback },
    queue: { write: async () => {} },
    profile: { read: async () => "" },
    cursors: { get: async () => undefined, set: async () => {} },
  };
  return { store, inbox, items, feedback };
}

const content: Content = { markdown: "article text", extractedBy: "capture", contentHash: "h", extractedAt: AT };

const event = (over: Partial<CaptureEvent> & { id: string; capturedAt: string }): CaptureEvent => ({
  action: "capture",
  source: "browser",
  url: "https://example.com/post",
  mustRead: false,
  ...over,
});

const rankedItem = (over: Partial<Item> = {}): Item => ({
  id: "item1",
  canonicalUrl: "https://example.com/post",
  status: "ranked",
  captures: [event({ id: "old", capturedAt: "2025-12-31T09:00:00.000Z" })],
  analyses: [],
  createdAt: "2025-12-31T09:00:00.000Z",
  updatedAt: "2025-12-31T09:00:00.000Z",
  ...over,
});

/** Extraction and evaluation are not under test here; both simply succeed. */
const deps = (store: RepoStore): ProcessDeps => ({
  store,
  contentSources: [{ name: "stub", acquire: async () => content } satisfies ContentSource],
  contextProviders: [],
  evaluator: new StubEvaluator(),
  prunePolicy: { shouldArchive: () => false },
  now: () => AT,
});

test("a remove retracts an earlier capture in the same batch", async () => {
  const { store, inbox, items } = fakeStore([
    event({ id: "a", capturedAt: "2026-01-01T09:00:00.000Z" }),
    event({ id: "b", capturedAt: "2026-01-01T10:00:00.000Z", action: "remove" }),
  ]);
  const result = await processInbox(deps(store));
  assert.equal(result.processed, 0, "the retracted capture must never be evaluated");
  assert.equal(inbox.size, 0, "both events are consumed");
  assert.equal(items.size, 0, "no item is created for a retracted capture");
});

test("a capture after a remove survives and is processed", async () => {
  const { store, inbox, items } = fakeStore([
    event({ id: "a", capturedAt: "2026-01-01T09:00:00.000Z" }),
    event({ id: "b", capturedAt: "2026-01-01T10:00:00.000Z", action: "remove" }),
    event({ id: "c", capturedAt: "2026-01-01T11:00:00.000Z" }),
  ]);
  const result = await processInbox(deps(store));
  assert.equal(result.processed, 1, "the re-save must reach the evaluator");
  assert.equal(inbox.size, 0);
  assert.equal([...items.values()][0]?.status, "ranked", "a re-saved page is not left archived");
});

test("a remove archives an already processed item rather than deleting it", async () => {
  const { store, items, feedback } = fakeStore(
    [event({ id: "b", capturedAt: "2026-01-01T10:00:00.000Z", action: "remove" })],
    [rankedItem()],
  );
  await processInbox(deps(store));
  assert.equal(items.get("item1")?.status, "archived");
  assert.equal(items.size, 1, "archive, never delete");
  assert.deepEqual(feedback, [{ itemId: "item1", action: "archive", reason: "removed via browser", createdAt: AT }]);
});

test("a re-save after a remove leaves a processed item ranked, with no archive recorded", async () => {
  const analysis = await new StubEvaluator().evaluate({ content, captures: [], context: "" });
  const { store, items, feedback } = fakeStore(
    [
      event({ id: "b", capturedAt: "2026-01-01T10:00:00.000Z", action: "remove" }),
      event({ id: "c", capturedAt: "2026-01-01T11:00:00.000Z" }),
    ],
    [rankedItem({ analyses: [analysis satisfies Analysis], content })],
  );
  await processInbox(deps(store));
  assert.equal(items.get("item1")?.status, "ranked");
  assert.deepEqual(feedback, [], "a superseded removal must not log an archive");
});

test("removes are matched per URL, not across the whole batch", async () => {
  const { store, items } = fakeStore([
    event({ id: "a", capturedAt: "2026-01-01T09:00:00.000Z", url: "https://example.com/keep" }),
    event({ id: "b", capturedAt: "2026-01-01T09:30:00.000Z", url: "https://example.com/drop" }),
    event({ id: "c", capturedAt: "2026-01-01T10:00:00.000Z", url: "https://example.com/drop", action: "remove" }),
  ]);
  const result = await processInbox(deps(store));
  assert.equal(result.processed, 1);
  assert.deepEqual(
    [...items.values()].map((i) => i.canonicalUrl),
    ["https://example.com/keep"],
  );
});

test("a capture stamped at the same instant as a remove is kept", async () => {
  const { store } = fakeStore([
    event({ id: "b", capturedAt: "2026-01-01T10:00:00.000Z", action: "remove" }),
    event({ id: "c", capturedAt: "2026-01-01T10:00:00.000Z" }),
  ]);
  const result = await processInbox(deps(store));
  assert.equal(result.processed, 1, "on a tie, keep the content rather than drop it");
});

test("inbox listing order does not decide: the batch resolves by capturedAt", async () => {
  const { store, items } = fakeStore([
    event({ id: "c", capturedAt: "2026-01-01T11:00:00.000Z" }),
    event({ id: "b", capturedAt: "2026-01-01T10:00:00.000Z", action: "remove" }),
    event({ id: "a", capturedAt: "2026-01-01T09:00:00.000Z" }),
  ]);
  const result = await processInbox(deps(store));
  assert.equal(result.processed, 1);
  assert.equal([...items.values()][0]?.status, "ranked");
});

test("a remove for a URL that was never captured is consumed without error", async () => {
  const { store, inbox, items } = fakeStore([event({ id: "b", capturedAt: "2026-01-01T10:00:00.000Z", action: "remove" })]);
  const result = await processInbox(deps(store));
  assert.deepEqual(result, { processed: 0, failed: 0 });
  assert.equal(inbox.size, 0);
  assert.equal(items.size, 0);
});
