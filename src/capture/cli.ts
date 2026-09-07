/**
 * Write one inbox entry. Used by the agent (after a Slack sweep) and by
 * anything else that can run a shell. Reads a CaptureEvent-shaped JSON
 * object from stdin, fills in id/capturedAt when missing.
 *
 *   echo '{"source":"slack","url":"https://…","title":"…"}' | pnpm capture
 */
import { randomBytes } from "node:crypto";
import { text } from "node:stream/consumers";
import { CaptureEvent } from "../domain/index.js";
import { FsRepoStore } from "../store/fs-repo-store.js";

const raw = JSON.parse(await text(process.stdin)) as Record<string, unknown>;
const capturedAt = (raw.capturedAt as string | undefined) ?? new Date().toISOString();
const id = (raw.id as string | undefined) ?? `${capturedAt.replace(/[:.]/g, "-")}-${randomBytes(3).toString("hex")}`;
const event = CaptureEvent.parse({ ...raw, id, capturedAt });

await new FsRepoStore(process.cwd()).inbox.add(event);
console.log(`inbox/${event.id}.json`);
