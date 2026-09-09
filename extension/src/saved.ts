/**
 * Local memory of what this browser has captured, so a page you already
 * bookmarked shows as saved when you come back. Stored per browser profile
 * in chrome.storage.local; the agent's repo remains the source of truth.
 */
export interface SavedEntry {
  at: string;
  mustRead: boolean;
  /** Absent means in the queue; `done` means the reader finished it and the agent was told. */
  status?: "done";
}

const KEY = "saved";
const TRACKING = /^(utm_|fbclid|gclid|mc_|ref$|source$|si$)/i;

/** Mirrors src/curate/canonicalize.ts so both sides agree on "the same page". */
export function canonicalize(input: string): string {
  const url = new URL(input);
  url.hash = "";
  url.hostname = url.hostname.toLowerCase().replace(/^www\./, "");
  for (const k of [...url.searchParams.keys()]) if (TRACKING.test(k)) url.searchParams.delete(k);
  url.searchParams.sort();
  if (url.pathname.length > 1) url.pathname = url.pathname.replace(/\/+$/, "");
  return url.toString();
}

async function all(): Promise<Record<string, SavedEntry>> {
  const got = await chrome.storage.local.get(KEY);
  return (got[KEY] as Record<string, SavedEntry> | undefined) ?? {};
}

export async function lookup(url: string): Promise<SavedEntry | undefined> {
  try {
    return (await all())[canonicalize(url)];
  } catch {
    return undefined;
  }
}

export async function remember(url: string, entry: SavedEntry): Promise<void> {
  const map = await all();
  map[canonicalize(url)] = entry;
  await chrome.storage.local.set({ [KEY]: map });
}

/** Keep the entry but flag it read, so a revisit shows the done icon and a click re-captures instead of removing. */
export async function markDone(url: string, at: string): Promise<void> {
  const map = await all();
  map[canonicalize(url)] = { ...(map[canonicalize(url)] ?? { mustRead: false }), at, status: "done" };
  await chrome.storage.local.set({ [KEY]: map });
}

export async function forget(url: string): Promise<void> {
  const map = await all();
  delete map[canonicalize(url)];
  await chrome.storage.local.set({ [KEY]: map });
}
