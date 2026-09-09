/**
 * Wire contract between the extension and the agent inbox. Mirrors
 * `skills/read-later-ingest/references/contract.md`; keep the two in sync.
 */
export interface BrowserCapture {
  id: string;
  /** `remove` retracts an earlier capture of the same URL; `done` marks it as read. */
  action: "capture" | "remove" | "done";
  source: "browser";
  url: string;
  title?: string;
  selectedText?: string;
  /** Full rendered page HTML. The agent extracts the article from it. Omitted for non-HTML tabs (PDF viewer); the agent fetches those. */
  html?: string;
  note?: string;
  mustRead: boolean;
  capturedAt: string;
}

export interface Settings {
  /** DAM api-server origin, e.g. https://dam.example.com */
  host: string;
  /** DAM API key (pk_…) with agents:operate, bound to the agent. */
  apiKey: string;
  agentId: string;
  /** Folder the repo lives in, relative to the agent's home directory. Scoped under `work/` so one agent can host other tools. */
  repoDir: string;
}

export const DEFAULT_SETTINGS: Settings = { host: "", apiKey: "", agentId: "", repoDir: "work/read-later" };

/**
 * Settings live in chrome.storage.local, never sync: the API key must not be
 * uploaded to the browser vendor's sync servers. Other extensions and web
 * pages cannot read it; the browser profile on disk is the trust boundary.
 */
export async function loadSettings(): Promise<Settings> {
  const stored = (await chrome.storage.local.get(DEFAULT_SETTINGS)) as Partial<Settings>;
  return { ...DEFAULT_SETTINGS, ...stored };
}

export const saveSettings = (s: Settings) => chrome.storage.local.set(s);

/**
 * The API key travels as a bearer token, so the host must be TLS or the key is
 * readable by anything on the wire. Loopback is exempt: a local DAM over plain
 * http never leaves the machine.
 */
export function isSecureHost(host: string): boolean {
  try {
    const url = new URL(host);
    // Mirrors the loopback origins in manifest.json `optional_host_permissions`.
    return url.protocol === "https:" || ["localhost", "127.0.0.1"].includes(url.hostname);
  } catch {
    return false;
  }
}

export const inboxPath = (settings: Settings, id: string): string =>
  [settings.repoDir.replace(/^\/+|\/+$/g, ""), "inbox", `${id}.json`].filter(Boolean).join("/");
