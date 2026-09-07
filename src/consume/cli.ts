/** Re-rank and rewrite queue.md, queue.json and queue.html without processing anything. */
import { FsRepoStore } from "../store/fs-repo-store.js";
import { writeQueue } from "../curate/process.js";

await writeQueue(new FsRepoStore(process.cwd()));
console.log("queue.md queue.json queue.html");
