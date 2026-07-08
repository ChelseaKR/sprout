"""Pure-Python BM25 (Okapi) lexical index — the lexical half of hybrid retrieval.

Zero dependencies, fully deterministic. It tokenises with the *same* ``content_tokens``
as the dense embedder and the extractive generator, so a passage that ranks well
lexically is described by the same vocabulary the generator will quote and the judge
will check. BM25 catches exact-term matches (species names, "10 days") that a bag-of-
hashes dense vector can blur, so the two retrieval paths are genuinely complementary.

Internally this is a **term-major inverted index** (``term -> {doc_index: term_freq}``),
not a per-document scan table: scoring a query only ever touches documents that contain
at least one query term, via ``self._postings[term]``, rather than iterating every
document in the corpus. That is what makes it possible to persist the fitted index at
ingest time (``to_state``/``from_state``, FIX-07) and still have per-query cost track the
number of matching documents rather than the size of the corpus.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

from .text import content_tokens


class BM25Index:
    """Classic Okapi BM25 over a fixed set of documents (one per chunk)."""

    def __init__(self, documents: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        tokenized = [content_tokens(d) for d in documents]
        self._lengths: list[int] = [len(toks) for toks in tokenized]
        n = len(tokenized)
        self._n = n
        self._avg_len = (sum(self._lengths) / n) if n else 0.0

        # Inverted index: term -> {doc_index: term_freq}. Built once per corpus; scoring
        # walks only the postings list of each query term, never every document.
        postings: dict[str, dict[int, int]] = {}
        df: Counter[str] = Counter()
        for i, toks in enumerate(tokenized):
            freq = Counter(toks)
            for term, tf in freq.items():
                postings.setdefault(term, {})[i] = tf
            df.update(freq.keys())
        self._postings = postings
        # Okapi idf with the +1 smoothing that keeps it non-negative.
        self._idf: dict[str, float] = {
            term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()
        }

    def _sparse_scores(self, query: str) -> dict[int, float]:
        """BM25 score of ``query`` for every document it shares a term with (sparse).

        Iterates query terms outermost so that, for any document matched by more than
        one query term, contributions accumulate in the same order ``scores`` would
        produce them in — the two representations agree bit-for-bit, not just in rank.
        """
        q_terms = content_tokens(query)
        out: dict[int, float] = {}
        if not q_terms or self._avg_len == 0.0:
            return out
        for term in q_terms:
            docs = self._postings.get(term)
            if not docs:
                continue
            idf = self._idf.get(term, 0.0)
            for i, tf in docs.items():
                denom_norm = self.k1 * (1 - self.b + self.b * (self._lengths[i] / self._avg_len))
                out[i] = out.get(i, 0.0) + idf * (tf * (self.k1 + 1)) / (tf + denom_norm)
        return out

    def scores(self, query: str) -> list[float]:
        """BM25 score of ``query`` against every document, in document order."""
        out = [0.0] * self._n
        for i, score in self._sparse_scores(query).items():
            out[i] = score
        return out

    def ranking(self, query: str) -> list[int]:
        """Document indices ordered best-first, dropping zero-score documents.

        Cost is proportional to the number of documents sharing a query term (the union
        of their postings lists), not the corpus size — see the module docstring.
        """
        scored = [(i, s) for i, s in self._sparse_scores(query).items() if s > 0.0]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [i for i, _ in scored]

    # --- persistence -------------------------------------------------------------
    # The postings (inverted term -> {doc: tf}, idf, lengths, avg length) are exactly
    # what ``scores``/``ranking`` need; persisting them lets ``from_state`` reconstruct
    # an index without re-tokenising every document, which is the per-query cost this
    # class exists to avoid once the corpus is indexed at ingest time (FIX-07).
    def to_state(self) -> dict[str, object]:
        """Serialise the fitted postings — everything needed to score without retokenising."""
        return {
            "k1": self.k1,
            "b": self.b,
            "n": self._n,
            "avg_len": self._avg_len,
            "idf": dict(self._idf),
            "lengths": list(self._lengths),
            "postings": {
                term: {str(i): tf for i, tf in docs.items()}
                for term, docs in self._postings.items()
            },
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> BM25Index:
        """Reconstruct an index from ``to_state`` output — no document retokenisation."""
        self = cls.__new__(cls)
        self.k1 = float(state["k1"])
        self.b = float(state["b"])
        self._n = int(state["n"])
        self._avg_len = float(state["avg_len"])
        self._idf = {str(term): float(v) for term, v in state["idf"].items()}
        self._lengths = [int(x) for x in state["lengths"]]
        self._postings = {
            str(term): {int(i): int(tf) for i, tf in docs.items()}
            for term, docs in state["postings"].items()
        }
        return self
