import type { CaptureEvent, FeedbackEvent, Item, QueueEntry } from "../domain/index.js";

/**
 * The git repo is the system of record. This interface is the only way the
 * pipeline touches it, so the layout can change without touching steps.
 */
export interface RepoStore {
  inbox: {
    list(): Promise<CaptureEvent[]>;
    add(event: CaptureEvent): Promise<void>;
    remove(id: string): Promise<void>;
  };
  items: {
    get(id: string): Promise<Item | undefined>;
    save(item: Item): Promise<void>;
    list(): Promise<Item[]>;
  };
  index: {
    lookup(canonicalUrl: string): Promise<string | undefined>;
    set(canonicalUrl: string, itemId: string): Promise<void>;
  };
  feedback: {
    append(event: FeedbackEvent): Promise<void>;
    list(): Promise<FeedbackEvent[]>;
  };
  queue: {
    write(entries: QueueEntry[], markdown: string, html: string): Promise<void>;
  };
  profile: {
    read(): Promise<string>;
  };
  /** Opaque per-source cursors, e.g. the Slack sweep's last seen timestamp. */
  cursors: {
    get(name: string): Promise<string | undefined>;
    set(name: string, value: string): Promise<void>;
  };
}
