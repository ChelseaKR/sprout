"""Hybrid retrieval (dense + BM25 via RRF), species filter, threshold gate.

Retrieval is mandatory and runs first; nothing downstream sees a passage that did not
clear it. Two ranking paths (cosine over hashing embeddings, Okapi BM25) are fused by
Reciprocal Rank Fusion so one path's miss is caught by the other. A conservative
species filter restricts candidates to the named plant when the question clearly names
one — so "is pothos toxic to cats?" cannot accidentally ground in a Monstera passage.
The returned chunks always carry their *cosine* score, so ``min_score`` keeps its
meaning under hybrid and is the single gate that decides answer-vs-refuse.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .lexical import BM25Index
from .models import Chunk, RetrievedChunk
from .providers.base import EmbeddingProvider
from .store import VectorStore
from .text import token_set


def _jaccard_sets(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# Slug tokens too generic to identify a species on their own.
_GENERIC = frozenset(
    {
        "plant",
        "plants",
        "tree",
        "trees",
        "fig",
        "palm",
        "fern",
        "ivy",
        "lily",
        "vine",
        "leaf",
        "leaves",
        "care",
        "house",
        "houseplant",
        "indoor",
    }
)


def _canonical_slug(source: str) -> str:
    """Language-invariant species key: 'pothos.es.md' and 'pothos.md' -> 'pothos'."""
    return Path(source).stem.split(".")[0]


def species_slug(source: str) -> str:
    """Public alias of the language-invariant species key (used by the photo-ID path)."""
    return _canonical_slug(source)


def _slug_tokens(source: str) -> list[str]:
    return [t for t in _canonical_slug(source).replace("_", "-").split("-") if t]


class Retriever:
    """Threshold-gated hybrid retriever over a populated :class:`VectorStore`."""

    def __init__(self, config: Config, store: VectorStore, embedder: EmbeddingProvider) -> None:
        self._config = config
        self._store = store
        self._embedder = embedder
        self._chunks = store.all_chunks()

    def _named_species(self, query: str) -> set[str]:
        """Canonical species slugs the query names, via slug tokens or the alias glossary."""
        q_tokens = token_set(query)
        named: set[str] = set()
        for chunk in self._chunks:
            distinctive = token_set(
                " ".join(t for t in _slug_tokens(chunk.source) if t not in _GENERIC)
            )
            if distinctive and distinctive & q_tokens:
                named.add(_canonical_slug(chunk.source))
        for alias, slug in self._config.retrieval.species_aliases.items():
            alias_tokens = token_set(alias)
            if alias_tokens and alias_tokens <= q_tokens:
                named.add(slug)
        return named

    def _candidates(self, query: str) -> list[Chunk]:
        if not self._config.retrieval.topic_filter:
            return list(self._chunks)
        named = self._named_species(query)
        if not named:
            return list(self._chunks)
        return [c for c in self._chunks if _canonical_slug(c.source) in named]

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        rcfg = self._config.retrieval
        candidates = self._candidates(query)
        if not candidates:
            return []

        qvec = self._embedder.embed(query)
        dense = self._store.search(qvec, top_k=len(self._store))
        cosine: dict[str, float] = {rc.chunk.chunk_id: rc.score for rc in dense}
        candidate_ids = {c.chunk_id for c in candidates}
        dense_ranking = [rc.chunk.chunk_id for rc in dense if rc.chunk.chunk_id in candidate_ids]

        rankings = [dense_ranking]
        if rcfg.hybrid:
            bm25 = BM25Index([c.text for c in candidates], k1=rcfg.bm25_k1, b=rcfg.bm25_b)
            bm25_ranking = [candidates[i].chunk_id for i in bm25.ranking(query)]
            rankings.append(bm25_ranking)

        fused = self._reciprocal_rank_fusion(rankings, rcfg.rrf_k)
        by_id = {c.chunk_id: c for c in candidates}
        ordered = [
            RetrievedChunk(chunk=by_id[cid], score=cosine.get(cid, 0.0))
            for cid in fused
            if cid in by_id
        ]
        return self._dedup(ordered, rcfg.top_k)

    @staticmethod
    def _reciprocal_rank_fusion(rankings: list[list[str]], k: int) -> list[str]:
        scores: dict[str, float] = {}
        for ranking in rankings:
            for rank, cid in enumerate(ranking):
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores, key=lambda cid: -scores[cid])

    def _dedup(self, ordered: list[RetrievedChunk], limit: int) -> list[RetrievedChunk]:
        """Drop near-duplicate passages, stopping once ``limit`` unique chunks are kept.

        Early-stopping bounds this to O(limit^2) jaccard comparisons regardless of how
        many candidates the (un-filtered) query produced — without it, an out-of-scope
        query over the whole corpus would dedup the entire candidate set.
        """
        threshold = self._config.retrieval.dedup_threshold
        kept: list[RetrievedChunk] = []
        kept_tokens: list[frozenset[str]] = []
        for rc in ordered:
            tokens = token_set(rc.chunk.text)
            if any(_jaccard_sets(tokens, kt) >= threshold for kt in kept_tokens):
                continue
            kept.append(rc)
            kept_tokens.append(tokens)
            if len(kept) >= limit:
                break
        return kept

    def has_grounding(self, query: str, retrieved: list[RetrievedChunk]) -> bool:
        """True iff a retrieved chunk clears ``min_score`` AND shares a content term.

        The shared-term requirement matters for the offline hashing embedder, where a
        wholly unrelated query can score a small spurious cosine via hash collisions;
        requiring at least one shared content token keeps out-of-scope refusal crisp.
        """
        min_score = self._config.retrieval.min_score
        q_tokens = token_set(query)
        return any(
            rc.score >= min_score and bool(q_tokens & token_set(rc.chunk.text)) for rc in retrieved
        )
