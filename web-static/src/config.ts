/**
 * Types for `public/data/config.json`, the data half of the port (see
 * `scripts/export_web_bundle.py` for how it's generated from
 * `sprout.config.load_config`). The *algorithms* live in TypeScript source; the
 * thresholds, deny-lists, keyword lists, species aliases, and per-language prompt
 * strings stay data, exported once from the validated Python config so the two
 * implementations cannot drift on what a "toxicity keyword" or a "forbidden safe
 * phrase" is.
 */

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
export const BUNDLE_FORMAT_VERSION = 2;

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
