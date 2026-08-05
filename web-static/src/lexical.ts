/**
 * Pure-TypeScript BM25 (Okapi) lexical index — a mirror of `src/sprout/lexical.py`.
 *
 * Zero dependencies, fully deterministic, tokenises with the same `contentTokens` as the
 * dense embedder and the extractive generator (see `text.ts`).
 *
 * Mirrors FIX-07's inverted-postings layout (`term -> {doc_index: term_freq}`): the index
 * is built (or loaded from the postings `sprout ingest` persisted in `index.json`) once
 * per corpus, and scoring walks only the postings list of each query term. Contribution
 * accumulation is query-term-outermost, exactly like Python's `_sparse_scores`, so the
 * two implementations agree bit-for-bit, not just in rank.
 */

import { contentTokens } from "./text.js";

/** Shape of the postings `store.py`'s `BM25Index.to_state()` persists in `index.json`. */
export interface BM25State {
  k1: number;
  b: number;
  n: number;
  avg_len: number;
  idf: Record<string, number>;
  lengths: number[];
  postings: Record<string, Record<string, number>>;
}

export class BM25Index {
  readonly k1: number;
  readonly b: number;

  private readonly lengths: number[];
  private readonly n: number;
  private readonly avgLen: number;
  private readonly idf: Map<string, number>;
  // term -> (doc index -> term frequency), insertion-ordered by ascending doc index.
  private readonly postings: Map<string, Map<number, number>>;

  private constructor(
    k1: number,
    b: number,
    n: number,
    avgLen: number,
    lengths: number[],
    idf: Map<string, number>,
    postings: Map<string, Map<number, number>>,
  ) {
    this.k1 = k1;
    this.b = b;
    this.n = n;
    this.avgLen = avgLen;
    this.lengths = lengths;
    this.idf = idf;
    this.postings = postings;
  }

  static build(documents: readonly string[], k1 = 1.5, b = 0.75): BM25Index {
    const tokenized = documents.map((d) => contentTokens(d));
    const lengths = tokenized.map((toks) => toks.length);
    const n = tokenized.length;
    const totalLen = lengths.reduce((a, b2) => a + b2, 0);
    const avgLen = n ? totalLen / n : 0.0;

    const postings = new Map<string, Map<number, number>>();
    const df = new Map<string, number>();
    for (let i = 0; i < tokenized.length; i++) {
      const freq = new Map<string, number>();
      for (const tok of tokenized[i] as string[]) {
        freq.set(tok, (freq.get(tok) ?? 0) + 1);
      }
      for (const [term, tf] of freq) {
        let docs = postings.get(term);
        if (docs === undefined) {
          docs = new Map<number, number>();
          postings.set(term, docs);
        }
        docs.set(i, tf);
        df.set(term, (df.get(term) ?? 0) + 1);
      }
    }
    const idf = new Map<string, number>();
    for (const [term, d] of df) {
      idf.set(term, Math.log(1 + (n - d + 0.5) / (d + 0.5)));
    }
    return new BM25Index(k1, b, n, avgLen, lengths, idf, postings);
  }

  /** Reconstruct an index from the postings `sprout ingest` persisted (`to_state` mirror). */
  static fromState(state: BM25State): BM25Index {
    const idf = new Map<string, number>();
    for (const [term, v] of Object.entries(state.idf)) {
      idf.set(term, v);
    }
    const postings = new Map<string, Map<number, number>>();
    for (const [term, docs] of Object.entries(state.postings)) {
      const parsed = new Map<number, number>();
      for (const [i, tf] of Object.entries(docs)) {
        parsed.set(Number(i), tf);
      }
      postings.set(term, parsed);
    }
    return new BM25Index(
      state.k1,
      state.b,
      state.n,
      state.avg_len,
      [...state.lengths],
      idf,
      postings,
    );
  }

  /**
   * BM25 score of `query` for every document it shares a term with (sparse). Query terms
   * iterate outermost so multi-term contributions accumulate in the same order as the
   * Python `_sparse_scores` — bit-for-bit agreement, not just rank agreement.
   */
  private sparseScores(query: string): Map<number, number> {
    const qTerms = contentTokens(query);
    const out = new Map<number, number>();
    if (qTerms.length === 0 || this.avgLen === 0.0) {
      return out;
    }
    for (const term of qTerms) {
      const docs = this.postings.get(term);
      if (docs === undefined || docs.size === 0) {
        continue;
      }
      const idf = this.idf.get(term) ?? 0.0;
      for (const [i, tf] of docs) {
        const length = this.lengths[i] as number;
        const denomNorm = this.k1 * (1 - this.b + this.b * (length / this.avgLen));
        out.set(i, (out.get(i) ?? 0.0) + (idf * (tf * (this.k1 + 1))) / (tf + denomNorm));
      }
    }
    return out;
  }

  /** BM25 score of `query` against every document, in document order. */
  scores(query: string): number[] {
    const out = new Array<number>(this.n).fill(0.0);
    for (const [i, score] of this.sparseScores(query)) {
      out[i] = score;
    }
    return out;
  }

  /** Document indices ordered best-first, dropping zero-score documents. */
  ranking(query: string): number[] {
    const scored: [number, number][] = [];
    for (const [i, s] of this.sparseScores(query)) {
      if (s > 0.0) {
        scored.push([i, s]);
      }
    }
    scored.sort((a, b2) => (b2[1] - a[1] !== 0 ? b2[1] - a[1] : a[0] - b2[0]));
    return scored.map(([i]) => i);
  }
}
