/**
 * A flat cosine store over pre-normalised dense vectors — a mirror of `store.py`'s
 * `VectorStore`, minus the write path (the browser only ever loads the index the Python
 * `sprout ingest` + `scripts/export_web_bundle.py` pair produced; it never writes one).
 *
 * Format v2 (FIX-07) carries the corpus's BM25 postings alongside chunks/vectors, so the
 * browser never re-tokenises the corpus either — `Retriever` loads them via
 * `BM25Index.fromState`.
 */

import type { BM25State } from "./lexical.js";
import type { Chunk, RetrievedChunk } from "./models.js";

interface IndexJson {
  format_version: number;
  chunks: Chunk[];
  vectors: number[][];
  bm25?: BM25State | null;
}

const FORMAT_VERSION = 2;

export class VectorStore {
  private readonly chunks: Chunk[];
  private readonly vectors: number[][];
  private readonly indexOf: Map<string, number>;
  /** Persisted BM25 postings from `sprout ingest` (v2), if the bundle carries them. */
  readonly bm25State: BM25State | null;

  private constructor(chunks: Chunk[], vectors: number[][], bm25State: BM25State | null) {
    this.chunks = chunks;
    this.vectors = vectors;
    this.bm25State = bm25State;
    this.indexOf = new Map(chunks.map((c, i) => [c.chunk_id, i]));
  }

  get length(): number {
    return this.chunks.length;
  }

  allChunks(): Chunk[] {
    return [...this.chunks];
  }

  /**
   * Top-k chunks by cosine similarity (dot product on pre-normalised vectors).
   *
   * `candidateIds`, when given, bounds the scan to those chunks instead of the whole
   * store — mirrors `store.py::search`'s `candidate_ids` (FIX-07). Ordering matches
   * Python's `heapq.nlargest` key `(score, -index)`: score descending, index ascending.
   */
  search(
    queryVector: readonly number[],
    topK: number,
    candidateIds?: ReadonlySet<string>,
  ): RetrievedChunk[] {
    let indices: number[];
    if (candidateIds === undefined) {
      indices = [...this.vectors.keys()];
    } else {
      indices = [];
      for (const cid of candidateIds) {
        const i = this.indexOf.get(cid);
        if (i !== undefined) {
          indices.push(i);
        }
      }
    }
    const scored: [number, number][] = [];
    for (const i of indices) {
      const vec = this.vectors[i] as number[];
      let dot = 0.0;
      const len = Math.min(queryVector.length, vec.length);
      for (let j = 0; j < len; j++) {
        dot += (queryVector[j] as number) * (vec[j] as number);
      }
      scored.push([dot, i]);
    }
    scored.sort((a, b) => (b[0] - a[0] !== 0 ? b[0] - a[0] : a[1] - b[1]));
    return scored.slice(0, topK).map(([score, i]) => ({
      chunk: this.chunks[i] as Chunk,
      score: Math.max(0.0, score),
    }));
  }

  static fromIndexJson(raw: unknown): VectorStore {
    const data = raw as IndexJson;
    if (data.format_version !== FORMAT_VERSION) {
      throw new Error(
        `unsupported index format: ${String(data.format_version)} — regenerate the bundle ` +
          `with \`make web-static-bundle\` (Python \`sprout ingest\` writes format ${FORMAT_VERSION})`,
      );
    }
    if (data.chunks.length !== data.vectors.length) {
      throw new Error("index.json: chunks/vectors length mismatch");
    }
    return new VectorStore(data.chunks, data.vectors, data.bm25 ?? null);
  }
}
