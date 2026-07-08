"""Hybrid retrieval (dense + BM25 via RRF), species filter, threshold gate.

Retrieval is mandatory and runs first; nothing downstream sees a passage that did not
clear it. Two ranking paths (cosine over hashing embeddings, Okapi BM25) are fused by
Reciprocal Rank Fusion so one path's miss is caught by the other. A conservative
species filter restricts candidates to the named plant when the question clearly names
one — so "is pothos toxic to cats?" cannot accidentally ground in a Monstera passage.
The returned chunks always carry their *cosine* score, so ``min_score`` keeps its
meaning under hybrid and is the single gate that decides answer-vs-refuse.

Two scale properties matter as the corpus grows past a few hundred chunks (FIX-07,
``docs/ideation/02-large-scale-fixes.md``): the BM25 index is built **once** per
``Retriever`` (from the store's persisted postings when available, or lazily on first
use otherwise) instead of being retokenised on every query; and the dense vector scan is
bounded — to the named species' chunk-id set when the query scopes to one, or to a
generous fixed fan-out otherwise — instead of always sorting the entire store.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .lexical import BM25Index
from .models import Chunk, RetrievedChunk
from .providers.base import EmbeddingProvider
from .store import VectorStore
from .text import token_set

# When the species filter does not narrow the corpus (no plant named, or filter off),
# bound the dense scan instead of ranking the whole store: request the larger of a
# generous multiple of top_k or a fixed floor, capped at the store size. This keeps
# unfiltered-query cost roughly flat past the floor while still giving the BM25 fusion
# path plenty of dense candidates to agree or disagree with.
_DENSE_FANOUT = 20
_DENSE_MIN_CANDIDATES = 200


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

# Off-corpus gazetteer: common houseplant names the corpus has no cited passage for.
# Every entry here is deliberately chosen so it cannot resolve via ``_named_species``
# (it shares no slug token, once generic terms are excluded, and no ``species_aliases``
# key with any corpus species). Used only to hard-refuse a safety/toxicity question
# that clearly names one of these plants, rather than let a spurious low-score match
# masquerade as coverage. Not exhaustive — a deny-list of common toxic houseplants.
UNCOVERED_SPECIES_GAZETTEER: frozenset[str] = frozenset(
    {
        # English
        "dieffenbachia",
        "dumb cane",
        "sago palm",
        "azalea",
        "oleander",
        "lily of the valley",
        "amaryllis",
        "caladium",
        "croton",
        "kalanchoe",
        "cyclamen",
        "foxglove",
        "elephant ear",
        "asparagus fern",
        # Spanish
        "diefenbaquia",
        "palma sago",
        "adelfa",
        "lirio de los valles",
        "amarilis",
        "caladio",
        # "croton" and "kalanchoe" are identical in English and Spanish (see above).
        "ciclamen",
        "dedalera",
        "oreja de elefante",
        "esparraguera",
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
        self._by_chunk_id: dict[str, Chunk] = {c.chunk_id: c for c in self._chunks}

        # Pre-group chunk ids by species slug, and precompute each slug's distinctive
        # token set, once per Retriever — so `_candidates` never re-scans/re-tokenises
        # the whole corpus on a per-query basis.
        self._chunk_ids_by_slug: dict[str, list[str]] = {}
        self._distinctive_by_slug: dict[str, frozenset[str]] = {}
        for chunk in self._chunks:
            slug = _canonical_slug(chunk.source)
            self._chunk_ids_by_slug.setdefault(slug, []).append(chunk.chunk_id)
            if slug not in self._distinctive_by_slug:
                self._distinctive_by_slug[slug] = token_set(
                    " ".join(t for t in _slug_tokens(chunk.source) if t not in _GENERIC)
                )

        # BM25 over the *full* corpus, built once. Prefer the store's persisted postings
        # (populated at ingest via `store.build_bm25`); fall back to building it here for
        # stores assembled directly (tests, or a pre-FIX-07 index.json) — still just once
        # per Retriever, never rebuilt per query.
        rcfg = config.retrieval
        self._bm25: BM25Index = store.bm25 or store.build_bm25(k1=rcfg.bm25_k1, b=rcfg.bm25_b)

    def _named_species(self, query: str) -> set[str]:
        """Canonical species slugs the query names, via slug tokens or the alias glossary."""
        q_tokens = token_set(query)
        named = {
            slug
            for slug, distinctive in self._distinctive_by_slug.items()
            if distinctive and distinctive & q_tokens
        }
        for alias, slug in self._config.retrieval.species_aliases.items():
            alias_tokens = token_set(alias)
            if alias_tokens and alias_tokens <= q_tokens:
                named.add(slug)
        return named

    def names_uncovered_species(self, query: str) -> bool:
        """True when the query clearly names a gazetteer plant absent from the corpus.

        Requires (a) a gazetteer entry's tokens to be a subset of the query's content
        tokens, AND (b) ``_named_species`` resolves to nothing — so a query that also
        names a *covered* species (e.g. comparing pothos with dieffenbachia) is left to
        the normal grounded path instead of being hard-refused.
        """
        if self._named_species(query):
            return False
        q_tokens = token_set(query)
        return any(
            token_set(name) and token_set(name) <= q_tokens for name in UNCOVERED_SPECIES_GAZETTEER
        )

    def _candidates(self, query: str) -> list[Chunk]:
        if not self._config.retrieval.topic_filter:
            return list(self._chunks)
        named = self._named_species(query)
        if not named:
            return list(self._chunks)
        ids = [cid for slug in named for cid in self._chunk_ids_by_slug.get(slug, [])]
        return [self._by_chunk_id[cid] for cid in ids]

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        rcfg = self._config.retrieval
        candidates = self._candidates(query)
        if not candidates:
            return []
        candidate_ids = {c.chunk_id for c in candidates}
        topic_scoped = len(candidates) < len(self._chunks)

        qvec = self._embedder.embed(query)
        if topic_scoped:
            # Bounded to exactly the named species' chunks — the common case at scale.
            dense = self._store.search(qvec, top_k=len(candidates), candidate_ids=candidate_ids)
        else:
            bound = min(len(self._store), max(rcfg.top_k * _DENSE_FANOUT, _DENSE_MIN_CANDIDATES))
            dense = self._store.search(qvec, top_k=bound)
        cosine: dict[str, float] = {rc.chunk.chunk_id: rc.score for rc in dense}
        dense_ranking = [rc.chunk.chunk_id for rc in dense if rc.chunk.chunk_id in candidate_ids]

        rankings = [dense_ranking]
        if rcfg.hybrid:
            bm25_ranking = [
                self._chunks[i].chunk_id
                for i in self._bm25.ranking(query)
                if self._chunks[i].chunk_id in candidate_ids
            ]
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
