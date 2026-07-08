"""EXP-03: a third, fully offline, deterministic *semantic* ``EmbeddingProvider``.

``HashingEmbedding`` (``deterministic.py``) is a retrieval baseline: it hashes tokens to
dimensions, so two different words are always orthogonal — "yellowing" and "hojas
amarillas" share no dimension even though they mean the same thing. ``StaticEmbedding``
closes part of that gap while keeping every property the offline default is chosen for:
no network, no cloud account, and byte-identical output for identical input.

It does this with a small, curated, precomputed lookup table (``data/embeddings/
static_vectors.json``, built by ``scripts/generate_static_vectors.py`` from
``clusters.yaml``) that maps plant-care vocabulary tokens — English and Spanish synonyms
and paraphrases of the same care concept — to nearby vectors. A token not in the table
(most of the corpus's non-domain prose, plant names, numbers, etc.) falls back to the same
signed token-hashing projection ``HashingEmbedding`` uses, so coverage is total: nothing is
ever dropped or zeroed out just because it is outside the curated vocabulary.

See ADR-0013 for the measured eval delta against the hashing baseline; this provider is
opt-in (``retrieval.embedding_provider: static``), not the offline default.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from ..text import content_tokens

_TABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "embeddings" / "static_vectors.json"


class _VectorTable:
    """The parsed, immutable static lookup table."""

    __slots__ = ("dim", "vectors")

    def __init__(self, dim: int, vectors: dict[str, list[float]]) -> None:
        self.dim = dim
        self.vectors = vectors


@lru_cache(maxsize=8)
def _load_table(path: str) -> _VectorTable:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return _VectorTable(dim=int(raw["dim"]), vectors=raw["vectors"])


class StaticEmbedding:
    """Curated static-vector lookup with a hashing fallback for out-of-vocabulary tokens.

    The table's dimensionality is fixed by the shipped data file (64 by default) and is
    intentionally *not* driven by ``retrieval.embedding_dim`` — that setting exists to size
    the hashing/Titan projections, not a curated vocabulary table whose size is a content
    decision, not a config knob.
    """

    def __init__(self, table_path: str | Path | None = None) -> None:
        self._table = _load_table(str(table_path or _TABLE_PATH))

    @property
    def dim(self) -> int:
        return self._table.dim

    def _fallback(self, token: str) -> list[float]:
        """The same deterministic signed-hash projection ``HashingEmbedding`` uses.

        Kept local (not imported) so this module has no dependency on the hashing
        provider's implementation staying stable — the two are independent providers
        that happen to share a fallback trick for out-of-vocabulary coverage.
        """
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % self._table.dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec = [0.0] * self._table.dim
        vec[idx] = sign
        return vec

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._table.dim
        for tok in content_tokens(text):
            known = self._table.vectors.get(tok)
            contribution = known if known is not None else self._fallback(tok)
            for i, v in enumerate(contribution):
                vec[i] += v
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]
