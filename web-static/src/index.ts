/**
 * Public entry point for the browser port (EXP-08). A page (or the future PWA shell)
 * imports {@link loadAssistant}, points it at the two static JSON assets
 * `scripts/export_web_bundle.py` produces, and gets back an {@link Assistant} whose
 * `.answer(query, language)` is the TypeScript twin of `sprout.answer.Assistant.answer`
 * — same retrieval, same generation, same guards, same confidence, run entirely
 * client-side with no server to trust.
 */

export { Assistant } from "./answer.js";
export type { WebConfig } from "./config.js";
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
import type { WebConfig } from "./config.js";
import { VectorStore } from "./store.js";

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
  const indexJson = await indexRes.json();
  const store = VectorStore.fromIndexJson(indexJson);
  return new Assistant(config, store);
}
