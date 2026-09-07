import { mkdir, readFile, readdir, rm, writeFile, appendFile } from "node:fs/promises";
import { join } from "node:path";
import { CaptureEvent, FeedbackEvent, Item, titleOf } from "../domain/index.js";
import type { QueueEntry } from "../domain/index.js";
import type { RepoStore } from "./repo-store.js";

const readJson = async <T>(path: string, parse: (raw: unknown) => T): Promise<T | undefined> => {
  try {
    return parse(JSON.parse(await readFile(path, "utf8")));
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw err;
  }
};

const writeJson = async (path: string, value: unknown): Promise<void> => {
  await mkdir(join(path, ".."), { recursive: true });
  await writeFile(path, JSON.stringify(value, null, 2) + "\n");
};

/** content.md carries frontmatter so any reader (artifact, e-ink, TTS) can render it standalone. */
const withFrontmatter = (item: Item): string => {
  const c = item.content!;
  const fm = { title: titleOf(item), url: item.canonicalUrl, author: c.author, published: c.published, words: c.wordCount, extracted_by: c.extractedBy };
  const lines = Object.entries(fm).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}: ${JSON.stringify(v)}`);
  return `---\n${lines.join("\n")}\n---\n\n${c.markdown}`;
};
const stripFrontmatter = (file: string): string => file.replace(/^---\n[\s\S]*?\n---\n\n?/, "");

/** Plain-files implementation. Layout is documented in CLAUDE.md. */
export class FsRepoStore implements RepoStore {
  constructor(private readonly root: string) {}

  private p = (...parts: string[]) => join(this.root, ...parts);

  inbox: RepoStore["inbox"] = {
    list: async () => {
      const files = (await readdir(this.p("inbox"))).filter((f) => f.endsWith(".json")).sort();
      const events = await Promise.all(
        files.map((f) => readJson(this.p("inbox", f), (raw) => CaptureEvent.parse(raw))),
      );
      return events.filter((e): e is CaptureEvent => e !== undefined);
    },
    add: (event) => writeJson(this.p("inbox", `${event.id}.json`), event),
    remove: (id) => rm(this.p("inbox", `${id}.json`), { force: true }),
  };

  items: RepoStore["items"] = {
    get: async (id) => {
      const item = await readJson(this.p("items", id, "item.json"), (raw) => Item.parse(raw));
      if (!item) return undefined;
      const file = await readFile(this.p("items", id, "content.md"), "utf8").catch(() => undefined);
      return item.content && file ? { ...item, content: { ...item.content, markdown: stripFrontmatter(file) } } : item;
    },
    save: async (item) => {
      const dir = this.p("items", item.id);
      await mkdir(dir, { recursive: true });
      if (item.content) await writeFile(join(dir, "content.md"), withFrontmatter(item));
      for (const a of item.analyses) await writeJson(join(dir, `analysis.${a.analysisVersion}.json`), a);
      const content = item.content ? { ...item.content, markdown: "" } : undefined;
      const captures = item.content ? item.captures.map(({ html: _html, ...c }) => c) : item.captures;
      await writeJson(join(dir, "item.json"), { ...item, captures, content });
    },
    list: async () => {
      const ids = (await readdir(this.p("items"), { withFileTypes: true }))
        .filter((d) => d.isDirectory())
        .map((d) => d.name);
      const items = await Promise.all(ids.map((id) => this.items.get(id)));
      return items.filter((i): i is Item => i !== undefined);
    },
  };

  private readIndex = async (): Promise<Record<string, string>> =>
    (await readJson(this.p("index.json"), (raw) => raw as Record<string, string>)) ?? {};

  index: RepoStore["index"] = {
    lookup: async (url) => (await this.readIndex())[url],
    set: async (url, itemId) => writeJson(this.p("index.json"), { ...(await this.readIndex()), [url]: itemId }),
  };

  feedback: RepoStore["feedback"] = {
    append: (event) => appendFile(this.p("feedback.jsonl"), JSON.stringify(event) + "\n"),
    list: async () => {
      const raw = await readFile(this.p("feedback.jsonl"), "utf8").catch(() => "");
      return raw
        .split("\n")
        .filter(Boolean)
        .map((line) => FeedbackEvent.parse(JSON.parse(line)));
    },
  };

  queue: RepoStore["queue"] = {
    write: async (entries: QueueEntry[], markdown: string, html: string) => {
      await writeJson(this.p("queue.json"), entries);
      await writeFile(this.p("queue.md"), markdown);
      await writeFile(this.p("queue.html"), html);
    },
  };

  profile: RepoStore["profile"] = {
    read: () => readFile(this.p("profile.md"), "utf8"),
  };

  cursors: RepoStore["cursors"] = {
    get: async (name) => (await readJson(this.p("cursors.json"), (raw) => raw as Record<string, string>))?.[name],
    set: async (name, value) => {
      const current = (await readJson(this.p("cursors.json"), (raw) => raw as Record<string, string>)) ?? {};
      await writeJson(this.p("cursors.json"), { ...current, [name]: value });
    },
  };
}
