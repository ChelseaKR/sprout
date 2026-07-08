/**
 * Hybrid retrieval (dense + BM25 via RRF), species filter, threshold gate — a mirror of
 * `retrieve.py`'s `Retriever`.
 */

import { HashingEmbedding } from "./hashEmbedding.js";
import { BM25Index } from "./lexical.js";
import type { Chunk, RetrievedChunk } from "./models.js";
import { VectorStore } from "./store.js";
import { jaccardSets, tokenSet } from "./text.js";
import type { RetrievalConfig } from "./config.js";

// Slug tokens too generic to identify a species on their own — mirrors `_GENERIC`.
const GENERIC = new Set([
  "plant", "plants", "tree", "trees", "fig", "palm", "fern", "ivy", "lily", "vine",
  "leaf", "leaves", "care", "house", "houseplant", "indoor",
]);

/** Language-invariant species key: 'pothos.es.md' and 'pothos.md' -> 'pothos'. Mirrors `_canonical_slug`. */
function canonicalSlug(source: string): string {
  const base = source.split("/").pop() ?? source;
  const stem = base.includes(".") ? (base.split(".")[0] as string) : base;
  return stem;
}

/** Public alias of the language-invariant species key (used by the photo-ID path in Python; kept for parity). */
export function speciesSlug(source: string): string {
  return canonicalSlug(source);
}

function slugTokens(source: string): string[] {
  return canonicalSlug(source)
    .replace(/_/g, "-")
    .split("-")
    .filter((t) => t.length > 0);
}

export class Retriever {
  private readonly config: RetrievalConfig;
  private readonly store: VectorStore;
  private readonly embedder: HashingEmbedding;
  private readonly chunks: Chunk[];

  constructor(config: RetrievalConfig, store: VectorStore, embedder: HashingEmbedding) {
    this.config = config;
    this.store = store;
    this.embedder = embedder;
    this.chunks = store.allChunks();
  }

  private namedSpecies(query: string): Set<string> {
    const qTokens = tokenSet(query);
    const named = new Set<string>();
    for (const chunk of this.chunks) {
      const distinctive = tokenSet(
        slugTokens(chunk.source)
          .filter((t) => !GENERIC.has(t))
          .join(" "),
      );
      if (distinctive.size > 0 && [...distinctive].some((t) => qTokens.has(t))) {
        named.add(canonicalSlug(chunk.source));
      }
    }
    for (const [alias, slug] of Object.entries(this.config.species_aliases)) {
      const aliasTokens = tokenSet(alias);
      if (aliasTokens.size > 0 && [...aliasTokens].every((t) => qTokens.has(t))) {
        named.add(slug);
      }
    }
    return named;
  }

  private candidates(query: string): Chunk[] {
    if (!this.config.topic_filter) {
      return [...this.chunks];
    }
    const named = this.namedSpecies(query);
    if (named.size === 0) {
      return [...this.chunks];
    }
    return this.chunks.filter((c) => named.has(canonicalSlug(c.source)));
  }

  retrieve(query: string): RetrievedChunk[] {
    const rcfg = this.config;
    const candidates = this.candidates(query);
    if (candidates.length === 0) {
      return [];
    }

    const qvec = this.embedder.embed(query);
    const dense = this.store.search(qvec, this.store.length);
    const cosine = new Map<string, number>();
    for (const rc of dense) {
      cosine.set(rc.chunk.chunk_id, rc.score);
    }
    const candidateIds = new Set(candidates.map((c) => c.chunk_id));
    const denseRanking = dense
      .filter((rc) => candidateIds.has(rc.chunk.chunk_id))
      .map((rc) => rc.chunk.chunk_id);

    const rankings: string[][] = [denseRanking];
    if (rcfg.hybrid) {
      const bm25 = new BM25Index(
        candidates.map((c) => c.text),
        rcfg.bm25_k1,
        rcfg.bm25_b,
      );
      const bm25Ranking = bm25.ranking(query).map((i) => (candidates[i] as Chunk).chunk_id);
      rankings.push(bm25Ranking);
    }

    const fused = Retriever.reciprocalRankFusion(rankings, rcfg.rrf_k);
    const byId = new Map(candidates.map((c) => [c.chunk_id, c]));
    const ordered: RetrievedChunk[] = [];
    for (const cid of fused) {
      const chunk = byId.get(cid);
      if (chunk) {
        ordered.push({ chunk, score: cosine.get(cid) ?? 0.0 });
      }
    }
    return this.dedup(ordered, rcfg.top_k);
  }

  private static reciprocalRankFusion(rankings: string[][], k: number): string[] {
    const scores = new Map<string, number>();
    for (const ranking of rankings) {
      ranking.forEach((cid, rank) => {
        scores.set(cid, (scores.get(cid) ?? 0.0) + 1.0 / (k + rank + 1));
      });
    }
    return [...scores.keys()].sort((a, b) => (scores.get(b) as number) - (scores.get(a) as number));
  }

  /**
   * Drop near-duplicate passages, stopping once `limit` unique chunks are kept.
   * Early-stopping bounds this to O(limit^2) jaccard comparisons — mirrors `_dedup`.
   */
  private dedup(ordered: RetrievedChunk[], limit: number): RetrievedChunk[] {
    const threshold = this.config.dedup_threshold;
    const kept: RetrievedChunk[] = [];
    const keptTokens: Set<string>[] = [];
    for (const rc of ordered) {
      const tokens = tokenSet(rc.chunk.text);
      if (keptTokens.some((kt) => jaccardSets(tokens, kt) >= threshold)) {
        continue;
      }
      kept.push(rc);
      keptTokens.push(tokens);
      if (kept.length >= limit) {
        break;
      }
    }
    return kept;
  }

  /**
   * True iff a retrieved chunk clears `min_score` AND shares a content term — mirrors
   * `has_grounding`.
   */
  hasGrounding(query: string, retrieved: readonly RetrievedChunk[]): boolean {
    const minScore = this.config.min_score;
    const qTokens = tokenSet(query);
    return retrieved.some((rc) => {
      if (rc.score < minScore) {
        return false;
      }
      const chunkTokens = tokenSet(rc.chunk.text);
      return [...qTokens].some((t) => chunkTokens.has(t));
    });
  }
}
