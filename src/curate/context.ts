import type { RepoStore } from "../store/repo-store.js";

/**
 * Supplies the personal context the evaluator judges relevance against.
 * Today: profile.md. Later: the digital-traces agent's output, recent
 * Slack/GitHub activity, previously accepted insights. Providers are
 * concatenated in order; each returns plain text or nothing.
 */
export interface ContextProvider {
  readonly name: string;
  provide(): Promise<string | undefined>;
}

export class ProfileContextProvider implements ContextProvider {
  readonly name = "profile";
  constructor(private readonly store: RepoStore) {}
  provide = () => this.store.profile.read().catch(() => undefined);
}

/** Reads a context file another agent maintains (e.g. a synced `context/current.md`). */
export class FileContextProvider implements ContextProvider {
  readonly name = "file";
  constructor(private readonly path: string) {}
  async provide(): Promise<string | undefined> {
    const { readFile } = await import("node:fs/promises");
    return readFile(this.path, "utf8").catch(() => undefined);
  }
}

export async function assembleContext(providers: ContextProvider[]): Promise<string> {
  const parts = await Promise.all(providers.map(async (p) => [p.name, await p.provide()] as const));
  return parts
    .filter((entry): entry is readonly [string, string] => Boolean(entry[1]))
    .map(([name, text]) => `## Context: ${name}\n\n${text.trim()}`)
    .join("\n\n");
}
