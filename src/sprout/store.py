"""In-memory cosine vector store, JSON-persistable — the default index.

No database: the whole index is a list of (chunk, vector) pairs that serialises to one
JSON file and rebuilds from ``make ingest``. Vectors are stored pre-normalised, so cosine
similarity is a dot product. The store also carries the corpus's **BM25 postings**, built
once (at ingest, or lazily on first use) rather than re-tokenised on every query — see
``build_bm25``/``bm25`` and FIX-07 in ``docs/ideation/02-large-scale-fixes.md``. There is
no mutable server state to lose; recovery is "re-ingest".
"""

from __future__ import annotations

import heapq
import json
from collections.abc import Iterable
from pathlib import Path

from .lexical import BM25Index
from .models import Chunk, RetrievedChunk

# v2 adds persisted BM25 postings (``bm25``) alongside chunks/vectors. v1 files have no
# postings key and must be re-ingested — loading one raises with a pointer to ``sprout
# ingest`` rather than a bare version mismatch.
_FORMAT_VERSION = 2


class VectorStore:
    """A flat cosine store over pre-normalised dense vectors, plus BM25 postings."""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []
        self._index_of: dict[str, int] = {}
        self._bm25: BM25Index | None = None

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunk: Chunk, vector: list[float]) -> None:
        self._index_of[chunk.chunk_id] = len(self._chunks)
        self._chunks.append(chunk)
        self._vectors.append(vector)
        # Adding a chunk invalidates any previously built BM25 postings (they no longer
        # cover the full document set); the caller must rebuild via ``build_bm25``.
        self._bm25 = None

    def all_chunks(self) -> list[Chunk]:
        return list(self._chunks)

    def build_bm25(self, *, k1: float = 1.5, b: float = 0.75) -> BM25Index:
        """Build BM25 postings over every stored chunk, in store order.

        Intended to run **once**, at ingest time, so ``index.json`` carries the postings
        and no query ever pays for re-tokenising the corpus. Idempotent — safe to call
        again (e.g. after a lazy fallback) since it only reads already-stored chunk text.
        """
        self._bm25 = BM25Index([c.text for c in self._chunks], k1=k1, b=b)
        return self._bm25

    @property
    def bm25(self) -> BM25Index | None:
        """The persisted/built BM25 index, or ``None`` if never built for this store."""
        return self._bm25

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        *,
        candidate_ids: Iterable[str] | None = None,
    ) -> list[RetrievedChunk]:
        """Top-k chunks by cosine similarity (dot product on normalised vectors).

        ``candidate_ids``, when given, bounds the scan to those chunks instead of the
        whole store — the species/topic filter in ``Retriever`` uses this so a scoped
        query costs proportional to the named species' chunk count, not the corpus size.
        Selection uses a bounded ``heapq.nlargest`` (O(n log top_k)) rather than a full
        sort, so even an unfiltered query does not pay for ordering the entire store.

        Fails closed on an embedding-dimension mismatch: switching
        ``retrieval.embedding_provider`` (e.g. hashing 512-d -> static 64-d, EXP-03)
        without re-running ``sprout ingest`` would otherwise silently truncate every dot
        product to the shorter vector and quietly wreck ranking quality.
        """
        if self._vectors and len(query_vector) != len(self._vectors[0]):
            raise ValueError(
                f"query embedding dimension {len(query_vector)} does not match the index's "
                f"{len(self._vectors[0])} — the index was built with a different embedding "
                "provider/dimension; run `sprout ingest` to rebuild it."
            )
        if candidate_ids is None:
            indices: Iterable[int] = range(len(self._vectors))
        else:
            indices = (self._index_of[cid] for cid in candidate_ids if cid in self._index_of)
        scored = [
            (sum(a * b for a, b in zip(query_vector, self._vectors[i], strict=False)), i)
            for i in indices
        ]
        top = heapq.nlargest(top_k, scored, key=lambda pair: (pair[0], -pair[1]))
        return [RetrievedChunk(chunk=self._chunks[i], score=max(0.0, score)) for score, i in top]

    # --- persistence -------------------------------------------------------------
    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "format_version": _FORMAT_VERSION,
            "chunks": [c.model_dump() for c in self._chunks],
            "vectors": self._vectors,
        }
        if self._bm25 is not None:
            data["bm25"] = self._bm25.to_state()
        return data

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> VectorStore:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"index not found: {p}. Run `sprout ingest` first.")
        raw = json.loads(p.read_text(encoding="utf-8"))
        if raw.get("format_version") != _FORMAT_VERSION:
            raise ValueError(
                f"unsupported index format: {raw.get('format_version')!r} "
                f"(expected {_FORMAT_VERSION}); run `sprout ingest` to rebuild {p}"
            )
        store = cls()
        for chunk_dict, vector in zip(raw["chunks"], raw["vectors"], strict=True):
            store.add(Chunk.model_validate(chunk_dict), [float(x) for x in vector])
        bm25_state = raw.get("bm25")
        if bm25_state is not None:
            store._bm25 = BM25Index.from_state(bm25_state)
        return store
