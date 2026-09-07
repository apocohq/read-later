import { DEFAULT_SETTINGS, inboxPath, isSecureHost, loadSettings, saveSettings, type Settings } from "./contract.js";
import { DamClient } from "./dam-client.js";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const host = $<HTMLInputElement>("host");
const apiKey = $<HTMLInputElement>("apiKey");
const agentSelect = $<HTMLSelectElement>("agentSelect");
const agentId = $<HTMLInputElement>("agentId");
const agentHint = $<HTMLParagraphElement>("agentHint");
const repoDir = $<HTMLInputElement>("repoDir");
const statusEl = $<HTMLSpanElement>("status");

let statusTimer: number | undefined;
function status(msg: string, kind: "ok" | "err" | "" = ""): void {
  statusEl.textContent = msg;
  statusEl.className = kind;
  window.clearTimeout(statusTimer);
  if (kind === "ok") statusTimer = window.setTimeout(() => (statusEl.textContent = ""), 3500);
}

const esc = (text: string): string =>
  text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** Callers own the markup, so every interpolated value must go through `esc` first. */
function hint(html: string, err = false): void {
  agentHint.innerHTML = html;
  agentHint.className = err ? "hint err" : "hint";
}

const current = (): Settings => ({
  host: host.value.trim().replace(/\/+$/, ""),
  apiKey: apiKey.value.trim(),
  agentId: (agentSelect.hidden ? agentId.value : agentSelect.value || agentId.value).trim(),
  repoDir: repoDir.value.trim() || DEFAULT_SETTINGS.repoDir,
});

/** The service worker can only call the DAM origin once the user grants it. */
async function ensureHostPermission(h: string): Promise<boolean> {
  const origin = `${new URL(h).origin}/*`;
  return (await chrome.permissions.contains({ origins: [origin] })) || chrome.permissions.request({ origins: [origin] });
}

function showManualId(): void {
  agentSelect.hidden = true;
  agentId.hidden = false;
  hint(`<button type="button" class="linkbtn" id="retry">Load agents</button> instead`);
  $("retry").addEventListener("click", () => void loadAgents(true));
}

let loading = false;
async function loadAgents(fromUserGesture = false): Promise<void> {
  const s = current();
  if (!s.host || !s.apiKey || loading) return;
  try {
    new URL(s.host);
  } catch {
    return;
  }
  const origin = `${new URL(s.host).origin}/*`;
  if (!fromUserGesture && !(await chrome.permissions.contains({ origins: [origin] }))) {
    hint(`<button type="button" class="linkbtn" id="allow">Allow access to ${esc(new URL(s.host).host)}</button> to list your agents.`);
    $("allow").addEventListener("click", () => void loadAgents(true));
    return;
  }
  loading = true;
  hint(`<span class="spinner"></span>Loading agents…`);
  try {
    if (fromUserGesture && !(await ensureHostPermission(s.host))) throw new Error("permission for the DAM host was denied");
    const agents = await new DamClient(s.host, s.apiKey).listAgents();
    agentSelect.replaceChildren(
      new Option("Choose an agent…", ""),
      ...agents.map((a) => new Option(a.name, a.id)),
    );
    if (s.agentId) agentSelect.value = s.agentId;
    agentSelect.hidden = false;
    agentId.hidden = true;
    hint(`${agents.length} agent${agents.length === 1 ? "" : "s"} · <button type="button" class="linkbtn" id="manual">paste an id</button>`);
    $("manual").addEventListener("click", showManualId);
  } catch (e) {
    const msg = (e as Error).message.replace(/^DAM agents\.list failed: /, "");
    agentSelect.hidden = true;
    agentId.hidden = false;
    hint(`Could not list agents (${esc(msg)}). Paste the agent id, or <button type="button" class="linkbtn" id="retry">retry</button>.`, true);
    $("retry").addEventListener("click", () => void loadAgents(true));
  } finally {
    loading = false;
  }
}

async function save(): Promise<Settings> {
  const s = current();
  if (!s.host || !s.apiKey) throw new Error("host and API key are required");
  if (!isSecureHost(s.host)) throw new Error("the DAM host must be https, so the API key is not sent in the clear");
  if (!(await ensureHostPermission(s.host))) throw new Error("permission for the DAM host was denied");
  await saveSettings(s);
  return s;
}

async function testUpload(): Promise<void> {
  const s = await save();
  if (!s.agentId) throw new Error("choose an agent first");
  const path = inboxPath(s, `test-${Date.now()}`).replace(/\.json$/, ".txt");
  status("Uploading…");
  await new DamClient(s.host, s.apiKey).uploadFile({
    agentId: s.agentId,
    path,
    content: "read-later extension test; safe to delete\n",
    contentType: "text/plain",
  });
  status(`Uploaded ${path}`, "ok");
}

const guard = (fn: () => Promise<void>) => () => fn().catch((e: Error) => status(e.message, "err"));

let debounce: number | undefined;
const scheduleLoad = () => {
  window.clearTimeout(debounce);
  debounce = window.setTimeout(() => void loadAgents(), 500);
};

document.addEventListener("DOMContentLoaded", async () => {
  const s = await loadSettings();
  host.value = s.host;
  apiKey.value = s.apiKey;
  agentId.value = s.agentId;
  repoDir.value = s.repoDir;
  if (s.repoDir !== DEFAULT_SETTINGS.repoDir) $<HTMLDetailsElement>("advanced").open = true;

  host.addEventListener("input", scheduleLoad);
  apiKey.addEventListener("input", scheduleLoad);
  agentSelect.addEventListener("change", () => (agentId.value = agentSelect.value));
  $("form").addEventListener("submit", (e) => {
    e.preventDefault();
    void guard(async () => {
      await save();
      status("Saved", "ok");
    })();
  });
  $("test").addEventListener("click", guard(testUpload));

  if (s.host && s.apiKey) void loadAgents();
  else if (s.agentId) showManualId();
});
