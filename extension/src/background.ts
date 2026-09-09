/**
 * Service worker: toolbar button, shortcuts, and context menu all funnel into
 * one capture. The page snapshot is taken in the tab; the upload goes straight
 * to the DAM api-server, which drops the file into the agent's workspace.
 */
import { inboxPath, loadSettings, type BrowserCapture } from "./contract.js";
import { fromSettings } from "./dam-client.js";
import { forget, lookup, markDone, remember, type SavedEntry } from "./saved.js";

interface PageSnapshot {
  url: string;
  title: string;
  selectedText: string;
  html: string;
}

/** Runs inside the page. Must be self-contained: no imports, no closures. */
function snapshotPage(): PageSnapshot {
  return {
    url: location.href,
    title: document.title,
    selectedText: window.getSelection()?.toString() ?? "",
    html: document.documentElement.outerHTML,
  };
}

/** URLs with an upload in flight; a second click or shortcut while pending is ignored. */
const inFlight = new Set<string>();

const newId = () =>
  `${new Date().toISOString().replace(/[:.]/g, "-")}-${crypto.randomUUID().slice(0, 6)}`;

type IconState = "default" | "busy1" | "busy2" | "busy3" | "saved" | "must" | "done" | "error";
/** Mid-grey outline: the usual compromise that reads on both light and dark toolbars. */
const iconPaths = (state: IconState) =>
  Object.fromEntries([16, 32, 48, 128].map((s) => [String(s), `icons/${state}-${s}.png`]));

/** The toolbar icon is the only feedback: a marching dashed outline while working, filled shape on outcome. */
async function showState(state: IconState, tabId?: number): Promise<void> {
  await chrome.action.setIcon({ ...(tabId ? { tabId } : {}), path: iconPaths(state) }).catch(() => {});
}

/**
 * Cycle three dash offsets so the outline appears to march until stopped. The returned
 * stop resolves no earlier than a minimum display time, so a fast upload still
 * visibly "works" instead of flashing straight to the result.
 */
function startBusy(tabId: number, minMs = 900): () => Promise<void> {
  const frames: IconState[] = ["busy1", "busy2", "busy3"];
  const started = Date.now();
  let i = 0;
  void showState(frames[0]!, tabId);
  const timer = setInterval(() => void showState(frames[(i = (i + 1) % frames.length)]!, tabId), 300);
  return async () => {
    await new Promise((r) => setTimeout(r, Math.max(0, minMs - (Date.now() - started))));
    clearInterval(timer);
  };
}

/** Colour means "in your queue"; done stays grey like idle, the check tells it apart. */
const iconFor = (entry?: SavedEntry): IconState =>
  !entry ? "default" : entry.status === "done" ? "done" : entry.mustRead ? "must" : "saved";

/** Restore the saved/must/done icon for pages this browser already captured. */
async function reflectSaved(tabId: number, url?: string): Promise<void> {
  if (!url || !/^https?:/.test(url)) return;
  await showState(iconFor(await lookup(url)), tabId);
}

async function capture(opts: { mustRead: boolean; note?: string }): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url || !/^https?:/.test(tab.url)) return;

  const settings = await loadSettings();
  if (!settings.host || !settings.apiKey || !settings.agentId) {
    await chrome.runtime.openOptionsPage();
    return;
  }
  if (inFlight.has(tab.url)) return;
  inFlight.add(tab.url);

  const stopBusy = startBusy(tab.id);
  try {
    const [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: snapshotPage });
    const page = result?.result as PageSnapshot | undefined;
    const id = newId();
    const event: BrowserCapture = {
      id,
      action: "capture",
      source: "browser",
      url: page?.url ?? tab.url,
      title: page?.title || tab.title || undefined,
      selectedText: page?.selectedText || undefined,
      html: page?.html,
      note: opts.note,
      mustRead: opts.mustRead,
      capturedAt: new Date().toISOString(),
    };
    await fromSettings(settings).uploadFile({
      agentId: settings.agentId,
      path: inboxPath(settings, id),
      content: JSON.stringify(event),
      contentType: "application/json",
    });
    await remember(event.url, { at: event.capturedAt, mustRead: opts.mustRead });
    await stopBusy();
    await showState(opts.mustRead ? "must" : "saved", tab.id);
  } catch (err) {
    await stopBusy();
    console.error("[read-later] capture failed", err);
    await showState("error", tab.id);
    setTimeout(() => void reflectSaved(tab.id!, tab.url), 5000);
  } finally {
    inFlight.delete(tab.url);
  }
}

/**
 * Send a `remove` or `done` event for the current tab. Remove forgets the page locally;
 * done keeps it with a `done` flag so the icon can say "you read this" on a revisit.
 */
async function sendAction(action: "remove" | "done"): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url) return;
  const settings = await loadSettings();
  if (!settings.host || !settings.apiKey || !settings.agentId) {
    await chrome.runtime.openOptionsPage();
    return;
  }
  if (inFlight.has(tab.url)) return;
  inFlight.add(tab.url);
  const stopBusy = startBusy(tab.id);
  try {
    const id = newId();
    const event: BrowserCapture = { id, action, source: "browser", url: tab.url, mustRead: false, capturedAt: new Date().toISOString() };
    await fromSettings(settings).uploadFile({
      agentId: settings.agentId,
      path: inboxPath(settings, id),
      content: JSON.stringify(event),
      contentType: "application/json",
    });
    if (action === "done") await markDone(tab.url, event.capturedAt);
    else await forget(tab.url);
    await stopBusy();
    await showState(action === "done" ? "done" : "default", tab.id);
  } catch (err) {
    await stopBusy();
    console.error(`[read-later] ${action} failed`, err);
    await showState("error", tab.id);
    setTimeout(() => void reflectSaved(tab.id!, tab.url), 5000);
  } finally {
    inFlight.delete(tab.url);
  }
}

const remove = () => sendAction("remove");

/** Toolbar click: queued page → remove; done page → back into the queue; anything else → capture. */
async function toggle(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url) return;
  const entry = await lookup(tab.url);
  await (entry && entry.status !== "done" ? remove() : capture({ mustRead: false }));
}

/** Chrome groups several items under a "DAM Read Later" submenu; rebuild them on install, update, and reload. */
function installMenus(): void {
  chrome.contextMenus.removeAll(() => {
    const contexts: chrome.contextMenus.ContextType[] = ["page", "link", "selection", "action"];
    chrome.contextMenus.create({ id: "capture", title: "Read later", contexts });
    chrome.contextMenus.create({ id: "capture-must-read", title: "Read later (must read)", contexts });
    chrome.contextMenus.create({ id: "done", title: "Mark as read", contexts });
    chrome.contextMenus.create({ id: "remove", title: "Remove from Read Later", contexts });
  });
}
chrome.runtime.onInstalled.addListener(installMenus);
chrome.runtime.onStartup.addListener(installMenus);

chrome.tabs.onActivated.addListener(({ tabId }) => void chrome.tabs.get(tabId).then((t) => reflectSaved(tabId, t.url)).catch(() => {}));
chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.status === "complete" || change.url) void reflectSaved(tabId, tab.url);
});

chrome.action.onClicked.addListener(() => void toggle());
chrome.commands.onCommand.addListener((cmd) => void capture({ mustRead: cmd === "capture-must-read" }));
chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "remove") return void remove();
  if (info.menuItemId === "done") return void sendAction("done");
  void capture({ mustRead: info.menuItemId === "capture-must-read", note: info.linkUrl ? `link: ${info.linkUrl}` : undefined });
});
