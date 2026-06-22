"""In-memory cosine vector store, JSON-persistable — the default index.

No database: the whole index is a list of (chunk, vector) pairs that serialises to one
JSON file and rebuilds from ``make ingest``. Vectors are stored pre-normalised, so cosine
similarity is a dot product. The store also exposes ``all_chunks`` so the hybrid retriever
can run BM25 over the same passages. There is no mutable server state to lose; recovery is
"re-ingest".
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Chunk, RetrievedChunk

_FORMAT_VERSION = 1


class VectorStore:
    """A flat cosine store over pre-normalised dense vectors."""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunk: Chunk, vector: list[float]) -> None:
        self._chunks.append(chunk)
        self._vectors.append(vector)

    def all_chunks(self) -> list[Chunk]:
        return list(self._chunks)

    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
        """Top-k chunks by cosine similarity (dot product on normalised vectors)."""
        scored: list[tuple[float, int]] = []
        for i, vec in enumerate(self._vectors):
            dot = sum(a * b for a, b in zip(query_vector, vec, strict=False))
            scored.append((dot, i))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            RetrievedChunk(chunk=self._chunks[i], score=max(0.0, score))
            for score, i in scored[:top_k]
        ]

    # --- persistence -------------------------------------------------------------
    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": _FORMAT_VERSION,
            "chunks": [c.model_dump() for c in self._chunks],
            "vectors": self._vectors,
        }

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
            raise ValueError(f"unsupported index format: {raw.get('format_version')!r}")
        store = cls()
        for chunk_dict, vector in zip(raw["chunks"], raw["vectors"], strict=True):
            store.add(Chunk.model_validate(chunk_dict), [float(x) for x in vector])
        return store
