/**
 * Signed token-hashing bag-of-tokens embedder — a mirror of `providers/deterministic.py`'s
 * `HashingEmbedding`.
 *
 * Each content token is hashed with SHA-256 (`sha256.ts`); the first 4 bytes pick a
 * dimension and the next byte's low bit picks a sign, exactly as the Python side does.
 * The same text always yields a byte-identical vector in both implementations, which is
 * exactly what the conformance test (`test/conformance.test.ts`) checks transitively
 * through retrieval and the final answer.
 */

import { sha256 } from "./sha256.js";
import { contentTokens } from "./text.js";

export class HashingEmbedding {
  readonly dim: number;

  constructor(dim = 512) {
    if (dim <= 0) {
      throw new Error("embedding dim must be positive");
    }
    this.dim = dim;
  }

  embed(text: string): number[] {
    const vec = new Array<number>(this.dim).fill(0.0);
    for (const tok of contentTokens(text)) {
      const digest = sha256(tok);
      // Big-endian uint32 of the first 4 bytes, mod `dim` — mirrors
      // `int.from_bytes(digest[:4], "big") % self._dim`.
      const idx =
        (((digest[0] as number) << 24) |
          ((digest[1] as number) << 16) |
          ((digest[2] as number) << 8) |
          (digest[3] as number)) >>>
        0;
      const dimIdx = idx % this.dim;
      const sign = ((digest[4] as number) & 1) === 1 ? 1.0 : -1.0;
      vec[dimIdx] = (vec[dimIdx] as number) + sign;
    }
    let norm = 0.0;
    for (const v of vec) {
      norm += v * v;
    }
    norm = Math.sqrt(norm);
    if (norm === 0.0) {
      return vec;
    }
    return vec.map((v) => v / norm);
  }
}
