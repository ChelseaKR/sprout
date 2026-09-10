/**
 * Types for `public/data/config.json`, the data half of the port (see
 * `scripts/export_web_bundle.py` for how it's generated from
 * `sprout.config.load_config`). The *algorithms* live in TypeScript source; the
 * thresholds, deny-lists, keyword lists, species aliases, and per-language prompt
 * strings stay data, exported once from the validated Python config so the two
 * implementations cannot drift on what a "toxicity keyword" or a "forbidden safe
 * phrase" is.
 */

import { sha256Hex } from "./sha256.js";

export interface RetrievalConfig {
  top_k: number;
  min_score: number;
  embedding_dim: number;
  hybrid: boolean;
  bm25_k1: number;
  bm25_b: number;
  rrf_k: number;
  dedup_threshold: number;
  topic_filter: boolean;
  species_aliases: Record<string, string>;
}

export interface GenerationConfig {
  max_sentences: number;
  relevance_floor: number;
  support_overlap: number;
}

/**
 * The fitted logistic shape written by `sprout fit-confidence` (ADR-0016) and exported
 * from `config/sprout.yaml`'s `confidence.fit`. Absent (`null`) until a fit is committed.
 */
export interface ConfidenceFit {
  midpoint: number;
  steepness: number;
  margin_bonus: number;
}

export interface ConfidenceConfig {
  abstain_threshold: number;
  low_confidence_threshold: number;
  /** `null` or missing means "use the ADR-0012 defaults", exactly as Python does. */
  fit?: ConfidenceFit | null;
  /**
   * The well-supported / partially-supported cut point (EXP-06), derived in
   * `confidence.py` from the committed reliability diagram and exported here rather
   * than mirrored as a TypeScript constant. A mirrored copy is correct only until the
   * next `sprout fit-confidence` re-derives it, after which the browser and the CLI
   * would place the same confidence in different bands and nothing would fail.
   *
   * Not optional, and `assertBundleIsCurrent` refuses a bundle missing it: an absent
   * cutoff compares as `confidence >= undefined`, which is false for every score, so
   * every answered question would be announced as "partially supported — verify".
   */
  well_supported_cutoff: number;
}

export interface GuardsConfig {
  forbidden_safe_phrases: Record<string, string[]>;
  toxicity_keywords: Record<string, string[]>;
  route_terms: Record<string, string[]>;
}

export interface LanguagesConfig {
  supported: string[];
  default: string;
}

export interface PromptsConfig {
  refusal_by_lang: Record<string, string>;
  disclosure_by_lang: Record<string, string>;
  safety_route_by_lang: Record<string, string>;
  nontoxic_caveat_by_lang: Record<string, string>;
  escalation_card_by_lang: Record<string, string>;
  /**
   * Band key -> language -> the localized words a screen reader announces for that
   * confidence band. Mirrors `PromptConfig.confidence_band_labels`.
   */
  confidence_band_labels: Record<string, Record<string, string>>;
}

/**
 * Which corpus, which settings and which index this bundle was built from — written by
 * `sprout.web_bundle.build_provenance` and re-derived by `sprout bundle-check`.
 *
 * `corpus_fingerprint` is byte-for-byte the value `sprout corpus diff` reports for a
 * corpus root, so a fingerprint shown on the page can be compared directly against a
 * corpus diff report. The dates are three-state: a `fetch_date` that is absent,
 * malformed *or in the future* is counted in `corpus_dates_unmeasurable` and never
 * widens the range, so the banner cannot advertise a snapshot that has not happened.
 * With nothing measurable both bounds are `""`, which must render as unknown.
 */
export interface BundleProvenance {
  corpus_fingerprint: string;
  corpus_documents: number;
  corpus_as_of_earliest: string;
  corpus_as_of_latest: string;
  corpus_dates_unmeasurable: number;
  config_sha256: string;
  index_sha256: string;
  index_chunks: number;
  index_chunk_ids_sha256: string;
}

export interface WebConfig {
  format_version: number;
  provenance: BundleProvenance;
  retrieval: RetrievalConfig;
  generation: GenerationConfig;
  confidence: ConfidenceConfig;
  guards: GuardsConfig;
  languages: LanguagesConfig;
  prompts: PromptsConfig;
}

/**
 * Schema version of `data/config.json`. Must equal `BUNDLE_FORMAT_VERSION` in
 * `src/sprout/web_bundle.py`; `tests/test_web_bundle.py` asserts the two agree.
 */
export const BUNDLE_FORMAT_VERSION = 3;

/**
 * Reject a bundle this build cannot vouch for, before it answers anything.
 *
 * The config bundle carried a `format_version` from the first export and *nothing read
 * it* — `store.ts` checks the index's version, which is a different file. So a bundle
 * from before provenance existed loaded silently and answered confidently, and no
 * surface could say which corpus it was answering from. A version field no reader
 * checks is not a compatibility guard; it is a comment.
 */
export function assertBundleIsCurrent(cfg: WebConfig): void {
  if (cfg.format_version !== BUNDLE_FORMAT_VERSION) {
    throw new Error(
      `unsupported bundle format: ${String(cfg.format_version)} (expected ` +
        `${BUNDLE_FORMAT_VERSION}) — re-export with \`make web-static-bundle\``,
    );
  }
  const provenance = cfg.provenance;
  if (!provenance || typeof provenance.corpus_fingerprint !== "string" || !provenance.corpus_fingerprint) {
    throw new Error(
      "bundle carries no corpus fingerprint, so which corpus it answers from is " +
        "unrecorded — re-export with `make web-static-bundle`",
    );
  }
  // A hand-edited bundle can declare the current version and still be missing the band
  // cut point. Absent, it compares as `confidence >= undefined` — false for every
  // score — so every answered question would be announced as "partially supported",
  // which is a missing threshold rendered as a calibration result. Refuse it here
  // rather than let it read as a measurement.
  const cutoff = cfg.confidence?.well_supported_cutoff;
  if (typeof cutoff !== "number" || !Number.isFinite(cutoff)) {
    throw new Error(
      "bundle carries no confidence.well_supported_cutoff, so no answer could be " +
        "placed in a confidence band — re-export with `make web-static-bundle`",
    );
  }
}

/**
 * `(count, digest)` over a sorted chunk-id list — the browser's mirror of
 * `web_bundle.index_chunk_ids_digest`.
 *
 * Python hashes the canonical JSON encoding of the sorted id list: sorted keys, compact
 * separators, no ASCII escaping. For a list of hex strings that is exactly what
 * `JSON.stringify` produces, so the two languages agree without a canonicaliser here.
 * `test/bundle-pairing.test.ts` holds that to the digest Python actually wrote into the
 * committed bundle rather than to this paragraph.
 */
export function indexChunkIdsDigest(ids: readonly string[]): { count: number; digest: string } {
  return { count: ids.length, digest: `sha256:${sha256Hex(JSON.stringify(ids))}` };
}

/**
 * Refuse a bundle whose provenance does not describe the index the page will answer from.
 *
 * `assertBundleIsCurrent` above checks the config against itself. Nothing checked it
 * against the file beside it — and the two are separate fetches of separate static
 * files, so they can come from different exports in three ordinary ways: a deploy
 * landing between the page's two requests; the service worker's fetch handler, which
 * refreshes cached entries **one request at a time**, so an offline load can pair a new
 * config with an old index; and a hand-copied `public/data/`.
 *
 * The consequence is the one this project refuses everywhere else. The page renders a
 * corpus fingerprint, a document count and an "as of" range out of `config.json` while
 * retrieving from whatever `index.json` it loaded, so a provenance banner can describe
 * a corpus the answers did not come from. `sprout bundle-check` makes exactly this
 * comparison and says so in terms — "config.json and the index beside it were not
 * written by the same export" — but it runs at build time, over the repository's copy,
 * and cannot see what a browser has cached.
 *
 * Two fields, not one. `index_chunks` catches the coarse case and reads well in the
 * message; `index_chunk_ids_sha256` is what actually closes it, because an index with
 * the same number of different passages is the interesting failure. Refusing rather
 * than warning is deliberate: an answer drawn from passages the banner does not
 * describe is worse than no answer, and there is no partial state a caller could
 * usefully render.
 */
export function assertBundleDescribesIndex(cfg: WebConfig, ids: readonly string[]): void {
  const { count, digest } = indexChunkIdsDigest(ids);
  const recorded = cfg.provenance;
  if (recorded.index_chunks !== count) {
    throw new Error(
      `bundle mismatch: config.json records an index of ${String(recorded.index_chunks)} ` +
        `chunk(s) and index.json holds ${String(count)} — config.json and the index beside ` +
        "it were not written by the same export, so the provenance shown on the page would " +
        "not describe the passages answering. Re-export with `make web-static-bundle`.",
    );
  }
  if (recorded.index_chunk_ids_sha256 !== digest) {
    throw new Error(
      "bundle mismatch: config.json records index chunk ids " +
        `${recorded.index_chunk_ids_sha256} and index.json holds ${digest} — the same ` +
        "number of different passages. The corpus fingerprint on the page would describe " +
        "a corpus these answers did not come from. Re-export with `make web-static-bundle`.",
    );
  }
}

/**
 * What the page may say about this bundle's dates, including when it may not.
 *
 * Mirrors `BundleProvenance.as_of_display` in Python. Never invents a date: with no
 * measurable `fetch_date` anywhere in the corpus the answer is the word `unknown`,
 * because "as of " with nothing after it reads as a rendering bug and "as of today"
 * would be a lie.
 */
export function bundleAsOfDisplay(provenance: BundleProvenance): string {
  const { corpus_as_of_earliest: earliest, corpus_as_of_latest: latest } = provenance;
  if (!earliest || !latest) {
    return "unknown";
  }
  return earliest === latest ? latest : `${earliest} to ${latest}`;
}

function byLang(map: Record<string, string>, language: string): string {
  return map[language] ?? (map["en"] as string);
}

export function refusalFor(cfg: WebConfig, language: string): string {
  return byLang(cfg.prompts.refusal_by_lang, language);
}

export function disclosureFor(cfg: WebConfig, language: string): string {
  return byLang(cfg.prompts.disclosure_by_lang, language);
}

/**
 * The localized words for a confidence band — mirrors
 * `PromptConfig.confidence_band_label_for`, including its three-level fallback: the
 * requested language, then English, then the band key itself. The last rung matters: a
 * band with no label at all must announce `well_supported`, which reads as a missing
 * translation, rather than the empty string, which reads as no band at all.
 */
export function confidenceBandLabelFor(cfg: WebConfig, band: string, language: string): string {
  const labels = cfg.prompts.confidence_band_labels[band] ?? {};
  return labels[language] ?? labels["en"] ?? band;
}

/**
 * The full safety message shown on every toxicity answer/refusal — mirrors
 * `PromptConfig.safety_directive_for`: routing line, then the "silence isn't safety"
 * caveat, then the escalation card, joined with single spaces in that order.
 */
export function safetyDirectiveFor(cfg: WebConfig, language: string): string {
  return [
    byLang(cfg.prompts.safety_route_by_lang, language),
    byLang(cfg.prompts.nontoxic_caveat_by_lang, language),
    byLang(cfg.prompts.escalation_card_by_lang, language),
  ].join(" ");
}
