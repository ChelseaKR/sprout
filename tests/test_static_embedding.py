"""Coverage for the static-vector semantic embedding provider (EXP-03, ADR-0013)."""

from __future__ import annotations

import math

from sprout.providers.static_embedding import StaticEmbedding


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_dim_matches_shipped_table() -> None:
    emb = StaticEmbedding()
    assert emb.dim == 64


def test_embed_is_deterministic() -> None:
    emb = StaticEmbedding()
    a = emb.embed("How often should I water my Monstera?")
    b = emb.embed("How often should I water my Monstera?")
    assert a == b


def test_embed_is_l2_normalised() -> None:
    emb = StaticEmbedding()
    vec = emb.embed("My Pothos leaves are yellowing and drooping.")
    norm = math.sqrt(sum(v * v for v in vec))
    assert math.isclose(norm, 1.0, abs_tol=1e-9)


def test_empty_text_returns_zero_vector() -> None:
    emb = StaticEmbedding()
    # "the" and "a" are stop-words -> no content tokens survive.
    assert emb.embed("the a") == [0.0] * emb.dim


def test_english_spanish_synonyms_land_close_together() -> None:
    emb = StaticEmbedding()
    en = emb.embed("Water it well.")
    es = emb.embed("Riego abundante.")
    unrelated = emb.embed("Is this toxic to my dog?")
    same_concept = _cosine(en, es)
    cross_concept = _cosine(en, unrelated)
    assert same_concept > cross_concept
    assert same_concept > 0.3


def test_paraphrase_of_yellowing_is_closer_than_unrelated_text() -> None:
    emb = StaticEmbedding()
    corpus_phrasing = emb.embed("chlorosis")
    paraphrase = emb.embed("my plant's leaves are going yellow")
    unrelated = emb.embed("humidifier misting schedule")
    assert _cosine(corpus_phrasing, paraphrase) > _cosine(corpus_phrasing, unrelated)


def test_out_of_vocabulary_tokens_still_get_a_stable_vector() -> None:
    emb = StaticEmbedding()
    # "zzyzx" is not in any cluster and not a real word — exercises the hashing fallback.
    a = emb.embed("zzyzx nonsense token")
    b = emb.embed("zzyzx nonsense token")
    assert a == b
    assert any(v != 0.0 for v in a)


def test_custom_table_path(tmp_path: object) -> None:
    import json
    from pathlib import Path

    p = Path(str(tmp_path)) / "tiny.json"
    table = {"dim": 4, "vectors": {"agua": [1.0, 0.0, 0.0, 0.0]}}
    p.write_text(json.dumps(table), encoding="utf-8")
    emb = StaticEmbedding(table_path=p)
    assert emb.dim == 4
    assert emb.embed("agua") == [1.0, 0.0, 0.0, 0.0]
