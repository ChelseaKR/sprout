/**
 * Selects query-relevant sentences verbatim from retrieved chunks — a mirror of
 * `providers/deterministic.py`'s `ExtractiveGenerator`.
 *
 * Selection is facet-coverage aware (EXP-01): the query is split into clauses
 * (`extractFacets`) and, after ranking every candidate sentence by query overlap,
 * sentences are picked greedily to maximise *marginal* facet coverage first and raw
 * score second. Single-clause queries reduce to plain top-score selection.
 */

import type { RetrievedChunk } from "./models.js";
import { extractFacets, splitSentences, tokenSet } from "./text.js";

interface Candidate {
  score: number;
  sentence: string;
  chunkId: string;
  covers: Set<number>;
}

export class ExtractiveGenerator {
  private readonly floor: number;

  constructor(relevanceFloor = 0.34) {
    this.floor = relevanceFloor;
  }

  generate(
    query: string,
    context: readonly RetrievedChunk[],
    maxSentences: number,
  ): [string, string][] {
    const qTokens = tokenSet(query);
    if (qTokens.size === 0) {
      return [];
    }
    const facets = extractFacets(query);
    const candidates = this.scoreCandidates(qTokens, facets, context);
    return ExtractiveGenerator.selectDiverse(candidates, maxSentences);
  }

  /**
   * Rank every sentence by query overlap and tag which facets it covers — mirrors
   * `_score_candidates` (sorted by score desc / retrieval order, deduplicated on exact
   * sentence text, highest score wins).
   */
  private scoreCandidates(
    qTokens: ReadonlySet<string>,
    facets: readonly Set<string>[],
    context: readonly RetrievedChunk[],
  ): Candidate[] {
    const scored: [number, number, string, string, Set<number>][] = [];
    context.forEach((rc, rank) => {
      for (const sentence of splitSentences(rc.chunk.text)) {
        const sTokens = tokenSet(sentence);
        if (sTokens.size === 0) {
          continue;
        }
        let overlapCount = 0;
        for (const t of qTokens) {
          if (sTokens.has(t)) {
            overlapCount += 1;
          }
        }
        const overlap = overlapCount / qTokens.size;
        if (overlap < this.floor) {
          continue;
        }
        // Prefer query overlap; nudge by retrieval score; break ties by order.
        const score = overlap + rc.score * 0.25 - rank * 1e-3;
        const covers = new Set<number>();
        facets.forEach((facet, i) => {
          let hit = 0;
          for (const t of facet) {
            if (sTokens.has(t)) {
              hit += 1;
            }
          }
          if (hit / facet.size >= this.floor) {
            covers.add(i);
          }
        });
        scored.push([score, rank, sentence.trim(), rc.chunk.chunk_id, covers]);
      }
    });
    scored.sort((a, b) => (b[0] - a[0] !== 0 ? b[0] - a[0] : a[1] - b[1]));

    const deduped: Candidate[] = [];
    const seen = new Set<string>();
    for (const [score, , sentence, chunkId, covers] of scored) {
      const key = sentence.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      deduped.push({ score, sentence, chunkId, covers });
    }
    return deduped;
  }

  /**
   * Greedily pick sentences maximising marginal facet coverage, then score — mirrors
   * `_select_diverse` (Python `max` keeps the *first* maximal candidate on ties).
   */
  private static selectDiverse(candidates: Candidate[], maxSentences: number): [string, string][] {
    const out: [string, string][] = [];
    const coveredFacets = new Set<number>();
    const remaining = [...candidates];
    while (remaining.length > 0 && out.length < maxSentences) {
      let bestIdx = 0;
      let bestMarginal = -1;
      let bestScore = -Infinity;
      remaining.forEach((cand, i) => {
        let marginal = 0;
        for (const f of cand.covers) {
          if (!coveredFacets.has(f)) {
            marginal += 1;
          }
        }
        if (marginal > bestMarginal || (marginal === bestMarginal && cand.score > bestScore)) {
          bestIdx = i;
          bestMarginal = marginal;
          bestScore = cand.score;
        }
      });
      const [picked] = remaining.splice(bestIdx, 1);
      const cand = picked as Candidate;
      out.push([cand.sentence, cand.chunkId]);
      for (const f of cand.covers) {
        coveredFacets.add(f);
      }
    }
    return out;
  }

  /** Offline generation is free. */
  estimatedCostUsd(): number {
    return 0.0;
  }
}
