"""Phase 1 CI smoke suite: derive_smoke_cases / run_smoke over corpus-derived questions.

Distinct from the hand-authored Phase 2 eval suites (see tests/test_eval_suites.py) — these
tests cover the mechanically-derived smoke net: one templated question per (species, topic)
pair actually present in the store, with no hand-picked corpus content of its own. Fixtures
(``config``, ``tiny_chunks``) come from ``conftest.py``.
"""

from __future__ import annotations

from sprout.answer import Assistant
from sprout.config import Config
from sprout.ingest import build_index
from sprout.models import Answer, AnswerSentence, Chunk, Citation
from sprout.providers import build_generator
from sprout.providers.deterministic import HashingEmbedding
from sprout.smoke import (
    SmokeCase,
    SmokeResult,
    _check_case,
    _reasons_for,
    derive_smoke_cases,
    run_smoke,
    to_markdown,
)
from sprout.store import VectorStore


def _wire(config: Config, chunks: list[Chunk]) -> tuple[Assistant, VectorStore]:
    embedder = HashingEmbedding(dim=config.retrieval.embedding_dim)
    store = VectorStore()
    for chunk in chunks:
        store.add(chunk, embedder.embed(chunk.text))
    assistant = Assistant(config, store, embedder, build_generator(config))
    return assistant, store


def test_derive_smoke_cases_covers_every_en_species_topic_pair(
    config: Config, tiny_chunks: list[Chunk]
) -> None:
    _, store = _wire(config, tiny_chunks)
    cases = derive_smoke_cases(store, language="en")
    pairs = {(c.species, c.topic) for c in cases}
    assert pairs == {
        ("monstera", "watering"),
        ("monstera", "light"),
        ("pothos", "toxicity"),
        ("spider-plant", "toxicity"),
    }
    # Spanish-language chunks in the fixture are excluded from the (English) default.
    assert all(c.language == "en" for c in cases)
    # Deterministic, stably-sorted case ordering — no run-to-run flakiness in CI diffs.
    assert [c.case_id for c in cases] == sorted(c.case_id for c in cases)


def test_derive_smoke_cases_es_language_selects_spanish_chunks(
    config: Config, tiny_chunks: list[Chunk]
) -> None:
    _, store = _wire(config, tiny_chunks)
    cases = derive_smoke_cases(store, language="es")
    assert {(c.species, c.topic) for c in cases} == {
        ("monstera", "watering"),
        ("pothos", "toxicity"),
    }


def test_derive_smoke_cases_uses_known_topic_templates(
    config: Config, tiny_chunks: list[Chunk]
) -> None:
    _, store = _wire(config, tiny_chunks)
    by_case_id = {c.case_id: c for c in derive_smoke_cases(store, language="en")}
    assert by_case_id["monstera:watering:en"].question == "How often should I water my monstera?"
    assert by_case_id["pothos:toxicity:en"].question == "Is my pothos toxic to my cat?"


def test_derive_smoke_cases_falls_back_for_an_unmodelled_topic(
    config: Config, tiny_chunks: list[Chunk]
) -> None:
    weird = Chunk(
        chunk_id="mon-pruning",
        doc_id="monstera",
        title="Monstera care",
        source="monstera.md",
        text="Prune leggy stems in spring.",
        language="en",
        topic="pruning",
        source_name="Synthetic Plant-Care Notes",
        url="https://example.invalid/monstera.md",
        license="CC0-1.0",
        fetch_date="2026-05-01",
    )
    _, store = _wire(config, [*tiny_chunks, weird])
    by_topic = {c.topic: c for c in derive_smoke_cases(store, language="en")}
    assert by_topic["pruning"].question == "What does the source say about pruning for my monstera?"


def test_run_smoke_passes_on_a_healthy_wired_corpus(
    config: Config, tiny_chunks: list[Chunk]
) -> None:
    assistant, store = _wire(config, tiny_chunks)
    result = run_smoke(assistant, store, config, language="en")
    assert result.cases
    assert result.passed, [(r.case.case_id, r.reasons) for r in result.failures]

    # "The cited source does not list Spider plant as toxic..." is a source-attributed
    # negative claim, not a safety certification — it must not be flagged.
    spider = next(r for r in result.cases if r.case.species == "spider-plant")
    assert spider.passed


def test_check_case_flags_a_species_leak_across_the_topic_filter(
    config: Config, tiny_chunks: list[Chunk]
) -> None:
    assistant, _store = _wire(config, tiny_chunks)
    # A case that claims a species not actually in the corpus: retrieval grounds
    # elsewhere (or refuses), and either way the case must not silently pass.
    bogus = SmokeCase(
        species="does-not-exist",
        topic="watering",
        question="How often should I water my monstera?",
    )
    result = _check_case(assistant, config, bogus)
    assert not result.passed
    assert any("species leak" in r for r in result.reasons)


def test_reasons_for_flags_a_safety_certification_on_a_toxicity_case(config: Config) -> None:
    """Defense-in-depth: even if a certifying sentence slipped past ``safety_filter``
    upstream, the smoke suite's own never-certify-safe check must still catch it."""
    citation = Citation(
        chunk_id="pothos-tox",
        doc_id="pothos",
        title="Pothos toxicity",
        source="pothos.md",
        quote="Pothos is not toxic to cats.",
        license="CC0-1.0",
        fetch_date="2026-05-01",
        url="https://example.invalid/pothos.md",
    )
    unsafe_answer = Answer(
        question="Is my pothos toxic to my cat?",
        language="en",
        sentences=(
            AnswerSentence(
                text="Pothos is not toxic to cats.", chunk_id="pothos-tox", citation=citation
            ),
        ),
        confidence=0.9,
    )
    case = SmokeCase(species="pothos", topic="toxicity", question="Is my pothos toxic to my cat?")
    reasons = _reasons_for(config, case, unsafe_answer)
    assert any("certification" in r for r in reasons)


def test_check_case_flags_a_refusal_on_a_supposedly_in_corpus_question(
    config: Config, tiny_chunks: list[Chunk]
) -> None:
    assistant, _store = _wire(config, tiny_chunks)
    case = SmokeCase(
        species="monstera", topic="watering", question="how do I fix a flat bicycle tire?"
    )
    result = _check_case(assistant, config, case)
    assert not result.passed
    assert any("refused" in r for r in result.reasons)


def test_to_markdown_summarises_pass_fail_counts(config: Config, tiny_chunks: list[Chunk]) -> None:
    assistant, store = _wire(config, tiny_chunks)
    result = run_smoke(assistant, store, config, language="en")
    md = to_markdown(result)
    assert "Sprout smoke suite" in md
    assert f"{len(result.cases)} cases, {len(result.failures)} failed." in md
    for r in result.cases:
        assert r.case.case_id in md


def test_to_markdown_lists_failures_with_reasons(config: Config, tiny_chunks: list[Chunk]) -> None:
    assistant, store = _wire(config, tiny_chunks)
    good = run_smoke(assistant, store, config, language="en")
    bogus = SmokeCase(species="does-not-exist", topic="watering", question="water my monstera?")
    failing = _check_case(assistant, config, bogus)
    combined = SmokeResult(cases=(*good.cases, failing))

    md = to_markdown(combined)
    assert not combined.passed
    assert "## Failures" in md
    assert failing.case.case_id in md
    for reason in failing.reasons:
        assert reason in md


def test_run_smoke_over_the_real_bundled_corpus() -> None:
    """End-to-end over the actual 16-species shipped corpus, not a synthetic fixture."""
    cfg = Config()
    store = build_index(cfg)
    assistant = Assistant.from_store(cfg, store)
    result = run_smoke(assistant, store, cfg, language="en")
    # 16 species, each with at least watering/light/toxicity sections.
    assert len(result.cases) >= 16 * 3
    assert result.passed, [(r.case.case_id, r.reasons) for r in result.failures]
