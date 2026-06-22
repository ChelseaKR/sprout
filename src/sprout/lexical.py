"""Pure-Python BM25 (Okapi) lexical index — the lexical half of hybrid retrieval.

Zero dependencies, fully deterministic. It tokenises with the *same* ``content_tokens``
as the dense embedder and the extractive generator, so a passage that ranks well
lexically is described by the same vocabulary the generator will quote and the judge
will check. BM25 catches exact-term matches (species names, "10 days") that a bag-of-
hashes dense vector can blur, so the two retrieval paths are genuinely complementary.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from .text import content_tokens


class BM25Index:
    """Classic Okapi BM25 over a fixed set of documents (one per chunk)."""

    def __init__(self, documents: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: list[list[str]] = [content_tokens(d) for d in documents]
        self._freqs: list[Counter[str]] = [Counter(toks) for toks in self._docs]
        self._lengths: list[int] = [len(toks) for toks in self._docs]
        n = len(self._docs)
        self._n = n
        self._avg_len = (sum(self._lengths) / n) if n else 0.0
        # Document frequency per term.
        df: Counter[str] = Counter()
        for freq in self._freqs:
            df.update(freq.keys())
        # Okapi idf with the +1 smoothing that keeps it non-negative.
        self._idf: dict[str, float] = {
            term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()
        }

    def scores(self, query: str) -> list[float]:
        """BM25 score of ``query`` against every document, in document order."""
        q_terms = content_tokens(query)
        out = [0.0] * self._n
        if not q_terms or self._avg_len == 0.0:
            return out
        for i in range(self._n):
            freq = self._freqs[i]
            length = self._lengths[i]
            denom_norm = self.k1 * (1 - self.b + self.b * (length / self._avg_len))
            score = 0.0
            for term in q_terms:
                tf = freq.get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf.get(term, 0.0)
                score += idf * (tf * (self.k1 + 1)) / (tf + denom_norm)
            out[i] = score
        return out

    def ranking(self, query: str) -> list[int]:
        """Document indices ordered best-first, dropping zero-score documents."""
        scored = [(i, s) for i, s in enumerate(self.scores(query)) if s > 0.0]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [i for i, _ in scored]
