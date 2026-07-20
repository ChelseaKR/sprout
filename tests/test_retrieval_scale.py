"""FIX-07 acceptance gate: retrieval cost stays bounded as the corpus grows.

``docs/ideation/02-large-scale-fixes.md`` calls for the latency test to be run at a
synthetically inflated corpus so it tests the *curve*, not just one point. This module
builds two synthetic corpora — a small one and one ~20x larger, spread across many more
species — and checks the properties FIX-07 actually changes:

- A **species-scoped query** (the common case: most real questions name a plant) is
  bounded by the named species' chunk-id group, not the corpus size — asserted on the
  wall-clock growth ratio, since dense search and BM25 scoring are both restricted to
  that small group regardless of how many other species exist.
- **BM25 is never rebuilt per query**, regardless of corpus size — asserted by counting
  ``BM25Index.__init__`` calls during retrieval.
- An **unfiltered query** no longer asks ``VectorStore.search`` to rank and fully sort
  the *entire* store (``top_k=len(store)``); the request is capped, bounding the
  downstream RRF/cosine-lookup work. This is a behavioural assertion, not a timing one,
  and deliberately does not claim flat *wall-clock* latency for the fully-unfiltered
  case: computing a dot product against every vector remains an O(corpus) cost of the
  pure-Python reference path with no species filter to narrow it, and an ANN/numpy fast
  path (mentioned as a future option in the ideation doc) would be the way to bound that
  further — out of scope here.

The wall-clock assertions compare a *growth ratio*, not an absolute wall-clock budget
(that is ``test_latency.py``'s job over the small fixture corpus) — a generous multiplier
keeps this robust to slow/loaded CI hardware while still catching a regression to the old
per-query "rebuild BM25 over every candidate" behaviour, which grew roughly linearly with
corpus size.
"""

from __future__ import annotations

import string
import time
from collections.abc import Iterable
from pathlib import Path

import pytest

from sprout.answer import Assistant
from sprout.config import Config
from sprout.lexical import BM25Index
from sprout.models import Chunk, RetrievedChunk
from sprout.providers import build_generator
from sprout.providers.deterministic import HashingEmbedding
from sprout.retrieve import Retriever
from sprout.store import VectorStore

_CHUNKS_PER_SPECIES = 3
_SMALL_SPECIES = 20
_LARGE_SPECIES = 400  # 20x the corpus, spread over 20x the species


_LETTERS = string.ascii_lowercase


def _slug_word(i: int) -> str:
    """A fully-alphabetic, distinct-per-index slug.

    The species filter (``Retriever._slug_tokens``) tokenises on letter/digit
    boundaries, so a shared alphabetic prefix followed by digits (e.g. "species0003")
    would spuriously tokenise into a shared "species" word plus a distinct number,
    making every synthetic species "named" by any query mentioning another one. Coding
    the index entirely in letters keeps each slug a single, wholly distinct token.
    """
    a, rem = divmod(i, 26 * 26)
    b, c = divmod(rem, 26)
    return f"synthplant{_LETTERS[a]}{_LETTERS[b]}{_LETTERS[c]}"


def _synthetic_corpus(n_species: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    topics = ["watering", "light", "toxicity"]
    for s in range(n_species):
        slug = _slug_word(s)
        for t in range(_CHUNKS_PER_SPECIES):
            topic = topics[t % len(topics)]
            chunks.append(
                Chunk(
                    chunk_id=f"{slug}-{topic}-{t}",
                    doc_id=slug,
                    title=f"{slug} care",
                    source=f"{slug}.md",
                    text=(
                        f"{slug} houseplant care notes on {topic}. Keep the soil evenly "
                        f"moist and provide bright indirect light near a window. The "
                        f"cited source discusses {topic} for {slug} in detail, including "
                        f"seasonal adjustments and common mistakes owners make."
                    ),
                    language="en",
                    topic=topic,
                    source_name="Synthetic Plant-Care Notes",
                    url=f"https://example.invalid/{slug}",
                    license="CC0-1.0",
                    fetch_date="2026-05-01",
                )
            )
    return chunks


def _build_retriever(config: Config, chunks: list[Chunk]) -> tuple[Retriever, HashingEmbedding]:
    emb = HashingEmbedding(dim=config.retrieval.embedding_dim)
    store = VectorStore()
    for c in chunks:
        store.add(c, emb.embed(c.text))
    store.build_bm25(k1=config.retrieval.bm25_k1, b=config.retrieval.bm25_b)
    return Retriever(config, store, emb), emb


def _median_query_time(retriever: Retriever, queries: list[str], rounds: int = 5) -> float:
    samples: list[float] = []
    for _ in range(rounds):
        for q in queries:
            start = time.perf_counter()
            retriever.retrieve(q)
            samples.append(time.perf_counter() - start)
    samples.sort()
    return samples[len(samples) // 2]


@pytest.mark.integration
def test_species_scoped_query_latency_is_sublinear_in_corpus_size(config: Config) -> None:
    small, _ = _build_retriever(config, _synthetic_corpus(_SMALL_SPECIES))
    large, _ = _build_retriever(config, _synthetic_corpus(_LARGE_SPECIES))
    size_ratio = (_LARGE_SPECIES * _CHUNKS_PER_SPECIES) / (_SMALL_SPECIES * _CHUNKS_PER_SPECIES)

    a5, a10 = _slug_word(5), _slug_word(10)
    queries = [f"is {a5} toxic to my cat", f"why is {a10} yellowing"]
    small_t = _median_query_time(small, queries)
    b250, b300 = _slug_word(250), _slug_word(300)
    large_t = _median_query_time(large, [f"is {b250} toxic to my cat", f"{b300} light"])

    assert size_ratio == pytest.approx(20.0)
    # A per-query rebuild/full-scan would grow roughly with size_ratio (20x); the
    # species-id-bounded path should stay far below that.
    growth = large_t / max(small_t, 1e-6)
    assert growth < size_ratio / 2, (
        f"species-scoped query latency grew {growth:.1f}x for a {size_ratio:.0f}x corpus "
        "— retrieval no longer looks bounded by the species chunk-id group"
    )


def test_unfiltered_query_bounds_dense_top_k_not_full_store(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """An unfiltered query no longer requests ``top_k=len(store)`` off a growing store.

    This is a behavioural assertion, not a timing one, and deliberately narrower than
    "unfiltered retrieval is flat": computing a dot product against every vector is an
    inherent O(corpus) cost of the pure-Python reference path with no species filter to
    narrow it (an ANN/numpy fast path would be the next step, out of scope here — see
    docs/ideation/02-large-scale-fixes.md). What FIX-07 removes is the *unbounded* part:
    previously every unfiltered query asked ``VectorStore.search`` to rank and fully sort
    the entire store (``top_k=len(self._store)``); now the request is capped, which
    bounds the downstream RRF fusion and cosine-lookup work to ``top_k`` regardless of
    how large the store grows.
    """
    cfg = Config.model_validate({"retrieval": {"topic_filter": False}})
    large, _ = _build_retriever(cfg, _synthetic_corpus(_LARGE_SPECIES))
    store_size = len(large._store)
    assert store_size > 1000  # sanity: this store is meaningfully larger than top_k

    seen_top_k: list[int] = []
    real_search = VectorStore.search

    def capturing_search(
        self: VectorStore,
        query_vector: list[float],
        top_k: int,
        *,
        candidate_ids: Iterable[str] | None = None,
    ) -> list[RetrievedChunk]:
        seen_top_k.append(top_k)
        return real_search(self, query_vector, top_k, candidate_ids=candidate_ids)

    monkeypatch.setattr(VectorStore, "search", capturing_search)
    large.retrieve("how often should I water my houseplant")

    assert seen_top_k, "unfiltered retrieve() should call VectorStore.search"
    assert all(k < store_size for k in seen_top_k), (
        f"top_k={seen_top_k} reached the full store size ({store_size}) — the dense scan "
        "is unbounded again"
    )


def test_bm25_not_rebuilt_per_query_at_scale(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    retriever, _ = _build_retriever(config, _synthetic_corpus(_LARGE_SPECIES))

    calls = {"n": 0}
    real_init = BM25Index.__init__

    def counting_init(self: BM25Index, *args: object, **kwargs: object) -> None:
        calls["n"] += 1
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(BM25Index, "__init__", counting_init)
    q1, q2 = _slug_word(1), _slug_word(2)
    for q in [f"is {q1} toxic", f"{q2} watering", "generic out of scope question"]:
        retriever.retrieve(q)
    assert calls["n"] == 0


def test_ingested_store_persists_bm25_postings_at_scale(tmp_path: Path, config: Config) -> None:
    emb = HashingEmbedding(dim=config.retrieval.embedding_dim)
    store = VectorStore()
    for c in _synthetic_corpus(_SMALL_SPECIES):
        store.add(c, emb.embed(c.text))
    store.build_bm25(k1=config.retrieval.bm25_k1, b=config.retrieval.bm25_b)

    p = tmp_path / "index.json"
    store.save(p)
    reloaded = VectorStore.load(p)
    assert reloaded.bm25 is not None
    a = Assistant(config, reloaded, emb, build_generator(config))
    slug = _slug_word(3)
    retrieved = a._retriever.retrieve(f"is {slug} toxic to my cat")
    assert retrieved
    assert all(rc.chunk.source == f"{slug}.md" for rc in retrieved)
