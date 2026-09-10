/**
 * Public entry point for the browser port (EXP-08). A page (or the future PWA shell)
 * imports {@link loadAssistant}, points it at the two static JSON assets
 * `scripts/export_web_bundle.py` produces, and gets back an {@link Assistant} whose
 * `.answer(query, language)` is the TypeScript twin of `sprout.answer.Assistant.answer`
 * — same retrieval, same generation, same guards, same confidence, run entirely
 * client-side with no server to trust.
 */

export { Assistant } from "./answer.js";
export type { BundleProvenance, WebConfig } from "./config.js";
export {
  BUNDLE_FORMAT_VERSION,
  assertBundleIsCurrent,
  bundleAsOfDisplay,
  confidenceBandLabelFor,
} from "./config.js";
export {
  BAND_INSUFFICIENT_EVIDENCE,
  BAND_PARTIALLY_SUPPORTED,
  BAND_WELL_SUPPORTED,
  confidenceBand,
} from "./confidence.js";
export { VectorStore } from "./store.js";
export type {
  Answer,
  AnswerSentence,
  Chunk,
  Citation,
  RetrievedChunk,
} from "./models.js";
export { answerCitations, answerDisplayText, answerText } from "./models.js";

import { Assistant } from "./answer.js";
import { assertBundleDescribesIndex, assertBundleIsCurrent } from "./config.js";
import type { WebConfig } from "./config.js";
import { indexChunkIds, VectorStore } from "./store.js";

/**
 * Fetch `config.json` and `index.json` from `dataBaseUrl` (default: same-origin
 * `./data/`) and construct a ready-to-use {@link Assistant}. The two files are the only
 * network requests the whole assistant ever makes — both same-origin static assets, no
 * API, no telemetry.
 */
export async function loadAssistant(dataBaseUrl = "./data/"): Promise<Assistant> {
  const base = dataBaseUrl.endsWith("/") ? dataBaseUrl : `${dataBaseUrl}/`;
  const [configRes, indexRes] = await Promise.all([
    fetch(`${base}config.json`),
    fetch(`${base}index.json`),
  ]);
  if (!configRes.ok) {
    throw new Error(`failed to fetch ${base}config.json: ${configRes.status}`);
  }
  if (!indexRes.ok) {
    throw new Error(`failed to fetch ${base}index.json: ${indexRes.status}`);
  }
  const config = (await configRes.json()) as WebConfig;
  assertBundleIsCurrent(config);
  const indexJson = await indexRes.json();
  // The two files are separate fetches of separate static assets, and nothing until
  // now compared them. `config.json` carries the index's chunk count and chunk-id
  // digest precisely so it can be held to the index beside it; a page that skips the
  // comparison can render one bundle's provenance over another bundle's passages.
  assertBundleDescribesIndex(config, indexChunkIds(indexJson));
  const store = VectorStore.fromIndexJson(indexJson);
  return new Assistant(config, store);
}
