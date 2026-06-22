"""The offline default stack: a hashing embedder and an extractive generator.

Both are pure, deterministic, dependency-free, and run with no network — the "offline
by default" hard rule. The embedder is a retrieval *baseline*, not a semantic model
(swap in Titan/Bedrock for production recall). The generator is the load-bearing piece:
it only ever returns sentences copied verbatim from retrieved chunks, each tagged with
its chunk id, so groundedness and citation coverage are 100% *by construction* — there
is no text path by which it can fabricate.
"""

from __future__ import annotations

import hashlib

from ..models import RetrievedChunk
from ..text import content_tokens, split_sentences, token_set


class HashingEmbedding:
    """Signed token-hashing bag-of-tokens projection, L2-normalised.

    Each content token is hashed with SHA-256; the first 4 bytes pick a dimension and
    the next bit picks a sign. SHA-256 (not SHA-1) is used purely as a stable
    token->dimension map — a non-cryptographic use that also keeps SAST quiet. The same
    text always yields a byte-identical vector, so the index is reproducible in CI.
    """

    def __init__(self, dim: int = 512) -> None:
        if dim <= 0:
            raise ValueError("embedding dim must be positive")
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for tok in content_tokens(text):
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


class ExtractiveGenerator:
    """Selects the most query-relevant sentences verbatim from retrieved chunks."""

    def __init__(self, relevance_floor: float = 0.34) -> None:
        self._floor = relevance_floor

    def generate(
        self, query: str, context: list[RetrievedChunk], max_sentences: int
    ) -> list[tuple[str, str]]:
        q_tokens = token_set(query)
        if not q_tokens:
            return []
        scored: list[tuple[float, int, str, str]] = []
        for rank, rc in enumerate(context):
            for sentence in split_sentences(rc.chunk.text):
                s_tokens = token_set(sentence)
                if not s_tokens:
                    continue
                overlap = len(q_tokens & s_tokens) / len(q_tokens)
                if overlap < self._floor:
                    continue
                # Prefer query overlap; nudge by retrieval score; break ties by order.
                score = overlap + rc.score * 0.25 - rank * 1e-3
                scored.append((score, rank, sentence.strip(), rc.chunk.chunk_id))
        scored.sort(key=lambda t: (-t[0], t[1]))
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for _, _, sentence, chunk_id in scored:
            key = sentence.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((sentence, chunk_id))
            if len(out) >= max_sentences:
                break
        return out

    def estimated_cost_usd(self, query: str, context: list[RetrievedChunk]) -> float:
        """Offline generation is free."""
        return 0.0
