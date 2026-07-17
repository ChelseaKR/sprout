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

export interface ConfidenceConfig {
  abstain_threshold: number;
  low_confidence_threshold: number;
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

export interface WebConfig {
  format_version: number;
  retrieval: RetrievalConfig;
  generation: GenerationConfig;
  confidence: ConfidenceConfig;
  guards: GuardsConfig;
  languages: LanguagesConfig;
  prompts: PromptsConfig;
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
