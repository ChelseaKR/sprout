/**
 * Input/output guards — a mirror of `guards.py`. The citation guard is the load-bearing
 * gate: it re-verifies every candidate sentence against the chunk it claims to come
 * from and drops anything it cannot support, so an ungrounded sentence is structurally
 * impossible to render in the TypeScript port too, not merely discouraged.
 */

import type { AnswerSentence, RetrievedChunk } from "./models.js";
import {
  containsPhrase,
  coverage,
  hasNegation,
  normalizeText,
  stripAccents,
  tokenSet,
  tokenize,
} from "./text.js";
import type { GuardsConfig } from "./config.js";

// --- input classification --------------------------------------------------------

/** True if the question is about toxicity/ingestion safety (either language). Mirrors `is_safety_query`. */
export function isSafetyQuery(query: string, language: string, cfg: GuardsConfig): boolean {
  const qTokens = new Set(tokenize(query));
  for (const lang of new Set([language, "en"])) {
    for (const kw of cfg.toxicity_keywords[lang] ?? []) {
      if (kw.includes(" ")) {
        if (containsPhrase(query, kw)) {
          return true;
        }
      } else if (qTokens.has(kw) || [...qTokens].some((t) => t.includes(kw))) {
        return true;
      }
    }
  }
  return false;
}

interface InjectionPattern {
  name: string;
  pattern: RegExp;
}

const INJECTION_PATTERNS: InjectionPattern[] = [
  {
    name: "instruction_override",
    pattern: /\b(ignore|disregard|forget)\b.{0,30}\b(previous|above|prior|instructions?|rules?)\b/i,
  },
  { name: "role_play", pattern: /\b(you are now|pretend to be|act as|roleplay)\b/i },
  {
    name: "system_prompt_probe",
    pattern: /\b(system prompt|your instructions|reveal|print).{0,20}\b(prompt|rules|instructions)\b/i,
  },
  {
    name: "safety_override",
    pattern: /\b(just (tell|say)|simply confirm).{0,20}\b(safe|fine|ok)\b/i,
  },
];

/**
 * Return matched prompt-injection category names (observability, not defense) — mirrors
 * `detect_injection`. Defense against injection is structural (the citation guard); this
 * only labels attempts for the refusal/adversarial eval suite / logging.
 */
export function detectInjection(text: string): string[] {
  return INJECTION_PATTERNS.filter((p) => p.pattern.test(text))
    .map((p) => p.name)
    .sort();
}

interface PiiPattern {
  pattern: RegExp;
  replacement: string;
}

const PII_PATTERNS: PiiPattern[] = [
  { pattern: /[\w.+-]{1,64}@[\w-]{1,255}\.[\w.-]{1,255}/g, replacement: "[email]" },
  { pattern: /\b\d{3}-\d{2}-\d{4}\b/g, replacement: "[ssn]" },
  { pattern: /\b(?:\+?\d[\s.-]?){9,13}\d\b/g, replacement: "[phone]" },
];

/** Best-effort redaction of text sent to a network provider. Mirrors `redact_pii`. */
export function redactPii(text: string): string {
  let out = text;
  for (const { pattern, replacement } of PII_PATTERNS) {
    out = out.replace(pattern, replacement);
  }
  return out;
}

// --- output guards ---------------------------------------------------------------

/** Mirrors `_fold`: lower-case, collapse space, fold accents and hyphens. */
function fold(text: string): string {
  return stripAccents(normalizeText(text)).replace(/-/g, " ");
}

// Toxicity/harm terms whose negation amounts to a safety certification (EN + ES, folded).
const HARM_TOKENS = new Set([
  "toxic", "toxico", "toxica", "poison", "poisonous", "venenosa", "veneno", "harm",
  "harmful", "danger", "dangerous", "risk", "riesgo", "hurt",
]);
// Source-attribution markers: their presence means the sentence reports what the cited
// source says (or does not say), not a bare certification.
const SOURCE_MARKERS = new Set([
  "cited", "reference", "source", "list", "listed", "according", "states", "fuente",
  "citada", "indica", "lista", "listada", "menciona", "segun",
]);

/**
 * True if `text` contains a forbidden safety-certification phrase (any phrasing) —
 * mirrors `asserts_safety`.
 */
export function assertsSafety(text: string, language: string, cfg: GuardsConfig): boolean {
  const haystack = fold(text);
  for (const lang of new Set([language, "en"])) {
    for (const phrase of cfg.forbidden_safe_phrases[lang] ?? []) {
      if (haystack.includes(fold(phrase))) {
        return true;
      }
    }
  }
  if (hasNegation(text)) {
    const toks = new Set(tokenize(text).map((t) => stripAccents(t)));
    const hasHarm = [...toks].some((t) => HARM_TOKENS.has(t));
    const hasSource = [...toks].some((t) => SOURCE_MARKERS.has(t));
    if (hasHarm && !hasSource) {
      return true;
    }
  }
  return false;
}

/**
 * A sentence is supported iff it is verbatim-contained, or sufficiently covered AND its
 * negation polarity matches the source — mirrors `_supported_by`.
 */
function supportedBy(sentence: string, chunkText: string, supportOverlap: number): boolean {
  if (containsPhrase(chunkText, sentence)) {
    return true;
  }
  if (tokenSet(sentence).size === 0) {
    return false;
  }
  if (hasNegation(sentence) !== hasNegation(chunkText)) {
    return false;
  }
  return coverage(sentence, chunkText) >= supportOverlap;
}

/**
 * Re-verify each candidate sentence against its cited chunk; drop the unsupported —
 * mirrors `citation_guard`, the structural reason ungrounded generation is impossible.
 */
export function citationGuard(
  candidates: readonly [string, string][],
  retrieved: readonly RetrievedChunk[],
  supportOverlap: number,
): AnswerSentence[] {
  const byId = new Map(retrieved.map((rc) => [rc.chunk.chunk_id, rc.chunk]));
  const out: AnswerSentence[] = [];
  const seen = new Set<string>();
  for (const [text, chunkId] of candidates) {
    const chunk = byId.get(chunkId);
    if (!chunk) {
      continue;
    }
    if (!supportedBy(text, chunk.text, supportOverlap)) {
      continue;
    }
    const key = normalizeText(text);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    out.push({
      text,
      chunk_id: chunkId,
      citation: {
        chunk_id: chunk.chunk_id,
        doc_id: chunk.doc_id,
        title: chunk.title,
        source: chunk.source,
        quote: chunk.text,
        license: chunk.license,
        fetch_date: chunk.fetch_date,
        url: chunk.url,
      },
      provenance: "corpus",
    });
  }
  return out;
}

/** Drop any rendered sentence that certifies a plant 'safe' — mirrors `safety_filter`. */
export function safetyFilter(
  sentences: readonly AnswerSentence[],
  language: string,
  cfg: GuardsConfig,
): AnswerSentence[] {
  return sentences.filter((s) => !assertsSafety(s.text, language, cfg));
}
