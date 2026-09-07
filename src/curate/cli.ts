/** Drain the inbox, evaluate, prune, and regenerate the queue. Run from the repo root. */
import { FsRepoStore } from "../store/fs-repo-store.js";
import { CaptureHtmlContentSource, CaptureTextContentSource, FetchContentSource } from "./content.js";
import { ProfileContextProvider } from "./context.js";
import { StubEvaluator } from "./evaluate.js";
import { processInbox } from "./process.js";
import { DefaultPrunePolicy } from "./prune.js";

const store = new FsRepoStore(process.cwd());
const result = await processInbox({
  store,
  contentSources: [new CaptureHtmlContentSource(), new FetchContentSource(), new CaptureTextContentSource()],
  contextProviders: [new ProfileContextProvider(store)],
  evaluator: new StubEvaluator(),
  prunePolicy: new DefaultPrunePolicy(),
});
console.log(JSON.stringify(result));
