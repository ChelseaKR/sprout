/**
 * Selects the most query-relevant sentences verbatim from retrieved chunks — a mirror of
 * `providers/deterministic.py`'s `ExtractiveGenerator`.
 */

import type { RetrievedChunk } from "./models.js";
import { splitSentences, tokenSet } from "./text.js";

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
    const scored: [number, number, string, string][] = [];
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
        scored.push([score, rank, sentence.trim(), rc.chunk.chunk_id]);
      }
    });
    scored.sort((a, b) => (b[0] - a[0] !== 0 ? b[0] - a[0] : a[1] - b[1]));
    const out: [string, string][] = [];
    const seen = new Set<string>();
    for (const [, , sentence, chunkId] of scored) {
      const key = sentence.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      out.push([sentence, chunkId]);
      if (out.length >= maxSentences) {
        break;
      }
    }
    return out;
  }

  /** Offline generation is free. */
  estimatedCostUsd(): number {
    return 0.0;
  }
}
