/**
 * Pure-TypeScript BM25 (Okapi) lexical index — a mirror of `src/sprout/lexical.py`.
 *
 * Zero dependencies, fully deterministic, tokenises with the same `contentTokens` as the
 * dense embedder and the extractive generator (see `text.ts`).
 */

import { contentTokens } from "./text.js";

export class BM25Index {
  readonly k1: number;
  readonly b: number;

  private readonly docs: string[][];
  private readonly freqs: Map<string, number>[];
  private readonly lengths: number[];
  private readonly n: number;
  private readonly avgLen: number;
  private readonly idf: Map<string, number>;

  constructor(documents: readonly string[], k1 = 1.5, b = 0.75) {
    this.k1 = k1;
    this.b = b;
    this.docs = documents.map((d) => contentTokens(d));
    this.freqs = this.docs.map((toks) => {
      const freq = new Map<string, number>();
      for (const tok of toks) {
        freq.set(tok, (freq.get(tok) ?? 0) + 1);
      }
      return freq;
    });
    this.lengths = this.docs.map((toks) => toks.length);
    this.n = this.docs.length;
    const totalLen = this.lengths.reduce((a, b2) => a + b2, 0);
    this.avgLen = this.n ? totalLen / this.n : 0.0;

    const df = new Map<string, number>();
    for (const freq of this.freqs) {
      for (const term of freq.keys()) {
        df.set(term, (df.get(term) ?? 0) + 1);
      }
    }
    this.idf = new Map();
    for (const [term, d] of df) {
      this.idf.set(term, Math.log(1 + (this.n - d + 0.5) / (d + 0.5)));
    }
  }

  /** BM25 score of `query` against every document, in document order. */
  scores(query: string): number[] {
    const qTerms = contentTokens(query);
    const out = new Array<number>(this.n).fill(0.0);
    if (qTerms.length === 0 || this.avgLen === 0.0) {
      return out;
    }
    for (let i = 0; i < this.n; i++) {
      const freq = this.freqs[i] as Map<string, number>;
      const length = this.lengths[i] as number;
      const denomNorm = this.k1 * (1 - this.b + this.b * (length / this.avgLen));
      let score = 0.0;
      for (const term of qTerms) {
        const tf = freq.get(term) ?? 0;
        if (tf === 0) {
          continue;
        }
        const idf = this.idf.get(term) ?? 0.0;
        score += (idf * (tf * (this.k1 + 1))) / (tf + denomNorm);
      }
      out[i] = score;
    }
    return out;
  }

  /** Document indices ordered best-first, dropping zero-score documents. */
  ranking(query: string): number[] {
    const scores = this.scores(query);
    const scored: [number, number][] = [];
    scores.forEach((s, i) => {
      if (s > 0.0) {
        scored.push([i, s]);
      }
    });
    scored.sort((a, b2) => (b2[1] - a[1] !== 0 ? b2[1] - a[1] : a[0] - b2[0]));
    return scored.map(([i]) => i);
  }
}
