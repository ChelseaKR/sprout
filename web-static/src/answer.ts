/**
 * The Assistant: prompt assembly -> retrieve -> generate -> guard -> answer — a mirror
 * of `answer.py`'s `Assistant`, restricted to the deterministic (offline) providers,
 * which is the only path a zero-server static site can run (EXP-08).
 */

import { isLowConfidence, scoreConfidence, shouldAbstain } from "./confidence.js";
import type { WebConfig } from "./config.js";
import { disclosureFor, refusalFor, safetyDirectiveFor } from "./config.js";
import { ExtractiveGenerator } from "./generator.js";
import { citationGuard, isSafetyQuery, safetyFilter } from "./guards.js";
import { HashingEmbedding } from "./hashEmbedding.js";
import { detectLanguage } from "./lang.js";
import type { Answer, AnswerSentence, RetrievedChunk } from "./models.js";
import { Retriever } from "./retrieve.js";
import { VectorStore } from "./store.js";

/** Round to 4 decimal places, matching Python's `round(x, 4)` for the non-adversarial,
 * never-exactly-at-a-tie-boundary floats this pipeline produces (logistic outputs). */
function round4(x: number): number {
  return Math.round(x * 10000) / 10000;
}

export class Assistant {
  private readonly config: WebConfig;
  private readonly store: VectorStore;
  private readonly embedder: HashingEmbedding;
  private readonly generator: ExtractiveGenerator;
  private readonly retriever: Retriever;

  constructor(config: WebConfig, store: VectorStore) {
    this.config = config;
    this.store = store;
    this.embedder = new HashingEmbedding(config.retrieval.embedding_dim);
    this.generator = new ExtractiveGenerator(config.generation.relevance_floor);
    this.retriever = new Retriever(config.retrieval, store, this.embedder);
  }

  private resolveLanguage(query: string, language: string | null): string {
    const supported = this.config.languages.supported;
    if (language !== null && supported.includes(language)) {
      return language;
    }
    const detected = detectLanguage(query, this.config.languages.default);
    return supported.includes(detected) ? detected : this.config.languages.default;
  }

  /** Public language resolution (used by the photo-ID path in the Python original; kept for parity). */
  resolveLanguagePublic(query: string, language: string | null = null): string {
    return this.resolveLanguage(query, language);
  }

  answer(query: string, language: string | null = null): Answer {
    const lang = this.resolveLanguage(query, language);
    const safety = isSafetyQuery(query, lang, this.config.guards);
    const retrieved = this.retriever.retrieve(query);

    if (safety && this.retriever.namesUncoveredSpecies(query)) {
      return this.refuse(query, lang, safety, "species_not_covered", false, 0.0, retrieved);
    }

    if (!this.retriever.hasGrounding(query, retrieved)) {
      return this.refuse(query, lang, safety, "out_of_scope", false, 0.0, retrieved);
    }

    const candidates = this.generator.generate(query, retrieved, this.config.generation.max_sentences);
    let sentences = citationGuard(candidates, retrieved, this.config.generation.support_overlap);
    sentences = safetyFilter(sentences, lang, this.config.guards);

    if (sentences.length === 0) {
      return this.refuse(query, lang, safety, "no_supported_sentences", false, 0.0, retrieved);
    }

    const confidence = scoreConfidence(retrieved, sentences.length, this.config.confidence);
    if (shouldAbstain(confidence, this.config.confidence)) {
      return this.refuse(query, lang, safety, "low_confidence", true, confidence, retrieved);
    }

    return this.render(query, lang, safety, sentences, retrieved, confidence);
  }

  private render(
    query: string,
    lang: string,
    safety: boolean,
    sentences: AnswerSentence[],
    retrieved: RetrievedChunk[],
    confidence: number,
  ): Answer {
    const citations = sentences.map((s) => s.citation);
    const asOf =
      citations.length > 0
        ? citations.reduce((max, c) => (c.fetch_date > max ? c.fetch_date : max), citations[0]?.fetch_date ?? "")
        : null;
    const topicById = new Map(retrieved.map((rc) => [rc.chunk.chunk_id, rc.chunk.topic]));
    const toxicityCited = sentences.some((s) => topicById.get(s.chunk_id) === "toxicity");
    const route = safety || toxicityCited;
    return {
      question: query,
      language: lang,
      sentences,
      retrieved,
      refused: false,
      refusal_reason: null,
      refusal_text: null,
      is_safety_query: route,
      safety_notice: route ? safetyDirectiveFor(this.config, lang) : null,
      confidence: round4(confidence),
      low_confidence: isLowConfidence(confidence, this.config.confidence),
      abstained: false,
      disclosure: disclosureFor(this.config, lang),
      as_of: asOf,
    };
  }

  private refuse(
    query: string,
    lang: string,
    safety: boolean,
    reason: string,
    abstained: boolean,
    confidence = 0.0,
    retrieved: readonly RetrievedChunk[] = [],
  ): Answer {
    const toxicityCited = retrieved.some((rc) => rc.chunk.topic === "toxicity");
    const route = safety || toxicityCited;
    return {
      question: query,
      language: lang,
      sentences: [],
      retrieved: [],
      refused: true,
      refusal_reason: reason,
      refusal_text: refusalFor(this.config, lang),
      is_safety_query: route,
      safety_notice: route ? safetyDirectiveFor(this.config, lang) : null,
      confidence: round4(confidence),
      low_confidence: true,
      abstained,
      disclosure: disclosureFor(this.config, lang),
      as_of: null,
    };
  }
}
