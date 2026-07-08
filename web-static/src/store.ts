/**
 * A flat cosine store over pre-normalised dense vectors — a mirror of `store.py`'s
 * `VectorStore`, minus the write path (the browser only ever loads the index the Python
 * `sprout ingest` + `scripts/export_web_bundle.py` pair produced; it never writes one).
 */

import type { Chunk, RetrievedChunk } from "./models.js";

interface IndexJson {
  format_version: number;
  chunks: Chunk[];
  vectors: number[][];
}

const FORMAT_VERSION = 1;

export class VectorStore {
  private readonly chunks: Chunk[];
  private readonly vectors: number[][];

  private constructor(chunks: Chunk[], vectors: number[][]) {
    this.chunks = chunks;
    this.vectors = vectors;
  }

  get length(): number {
    return this.chunks.length;
  }

  allChunks(): Chunk[] {
    return [...this.chunks];
  }

  /** Top-k chunks by cosine similarity (dot product on pre-normalised vectors). */
  search(queryVector: readonly number[], topK: number): RetrievedChunk[] {
    const scored: [number, number][] = [];
    for (let i = 0; i < this.vectors.length; i++) {
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
      throw new Error(`unsupported index format: ${String(data.format_version)}`);
    }
    if (data.chunks.length !== data.vectors.length) {
      throw new Error("index.json: chunks/vectors length mismatch");
    }
    return new VectorStore(data.chunks, data.vectors);
  }
}
