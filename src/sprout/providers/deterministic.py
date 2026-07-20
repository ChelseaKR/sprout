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
from ..text import content_tokens, extract_facets, split_sentences, token_set


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
    """Selects query-relevant sentences verbatim from retrieved chunks.

    Selection is facet-coverage aware: the query is split into clauses (``text.
    extract_facets``) and, after ranking every candidate sentence by query overlap as
    before, sentences are picked greedily to maximise *marginal* facet coverage first
    and raw score second. A single-clause query ("How often should I water my pothos?")
    degrades to plain top-score selection — unchanged from before this was added. A
    multi-clause query ("How often should I water, and does that change in winter?")
    stops the ranker from returning three near-duplicate watering sentences and missing
    the seasonal clause: once the watering clause is covered, only a sentence that also
    covers the winter clause can outrank another watering repeat.
    """

    def __init__(self, relevance_floor: float = 0.34) -> None:
        self._floor = relevance_floor

    def generate(
        self, query: str, context: list[RetrievedChunk], max_sentences: int
    ) -> list[tuple[str, str]]:
        q_tokens = token_set(query)
        if not q_tokens:
            return []
        facets = extract_facets(query)
        candidates = self._score_candidates(q_tokens, facets, context)
        return self._select_diverse(candidates, max_sentences)

    def _score_candidates(
        self,
        q_tokens: frozenset[str],
        facets: list[frozenset[str]],
        context: list[RetrievedChunk],
    ) -> list[tuple[float, str, str, frozenset[int]]]:
        """Rank every sentence by query overlap and tag which facets it covers.

        Returns ``(score, sentence, chunk_id, facet_indices_covered)``, sorted by
        score descending, deduplicated on exact sentence text (highest score wins).
        """
        scored: list[tuple[float, int, str, str, frozenset[int]]] = []
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
                covers = frozenset(
                    i
                    for i, facet in enumerate(facets)
                    if len(facet & s_tokens) / len(facet) >= self._floor
                )
                scored.append((score, rank, sentence.strip(), rc.chunk.chunk_id, covers))
        scored.sort(key=lambda t: (-t[0], t[1]))

        deduped: list[tuple[float, str, str, frozenset[int]]] = []
        seen: set[str] = set()
        for score, _, sentence, chunk_id, covers in scored:
            key = sentence.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append((score, sentence, chunk_id, covers))
        return deduped

    @staticmethod
    def _select_diverse(
        candidates: list[tuple[float, str, str, frozenset[int]]], max_sentences: int
    ) -> list[tuple[str, str]]:
        """Greedily pick sentences maximising marginal facet coverage, then score.

        With a single facet (or none), every candidate's marginal coverage is
        identical on the first pick and zero thereafter, so this reduces to plain
        top-score selection — the pre-facet-coverage behaviour is unchanged.
        """
        out: list[tuple[str, str]] = []
        covered_facets: set[int] = set()
        remaining = list(candidates)
        while remaining and len(out) < max_sentences:
            best_idx = max(
                range(len(remaining)),
                key=lambda i: (len(remaining[i][3] - covered_facets), remaining[i][0]),
            )
            _, sentence, chunk_id, covers = remaining.pop(best_idx)
            out.append((sentence, chunk_id))
            covered_facets |= covers
        return out

    def estimated_cost_usd(self, query: str, context: list[RetrievedChunk]) -> float:
        """Offline generation is free."""
        return 0.0
