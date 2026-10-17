"""Issue #168: retrieval is scoped to the answer language, so a Spanish answer quotes only
Spanish passages.

The extractive generator copies sentences verbatim from whatever retrieval hands it. A
Spanish question naming a Latin binomial ("Monstera deliciosa") shares those tokens with
the English passage, so a language-blind candidate set let an English sentence render
into a Spanish answer.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sprout.answer import Assistant
from sprout.config import Config, load_config
from sprout.ingest import build_index
from sprout.models import Chunk

_ROOT = Path(__file__).resolve().parent.parent


def make_chunk(
    chunk_id: str, source: str, title: str, text: str, topic: str, language: str = "en"
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=source.split(".")[0],
        title=title,
        source=source,
        text=text,
        language=language,
        topic=topic,
        source_name="Synthetic Plant-Care Notes",
        url=f"https://example.invalid/{source}",
        license="CC0-1.0",
        fetch_date="2026-05-01",
    )


BINOMIAL_CHUNKS: list[Chunk] = [
    make_chunk(
        "mon-light-en",
        "monstera.md",
        "Monstera care",
        "The Monstera (Monstera deliciosa) grows best in bright indirect light "
        "for roughly 6 to 8 hours a day.",
        topic="light",
    ),
    make_chunk(
        "mon-water-en",
        "monstera.md",
        "Monstera care",
        "Water the Monstera (Monstera deliciosa) when the top 2 inches of soil are dry.",
        topic="watering",
    ),
    make_chunk(
        "mon-water-es",
        "monstera.es.md",
        "Cuidado de la Monstera",
        "Riega la Monstera (Monstera deliciosa) cuando los 5 centimetros superiores "
        "del sustrato esten secos.",
        topic="riego",
        language="es",
    ),
]

SPANISH_QUESTION = "¿Con qué frecuencia debo regar mi Monstera deliciosa?"


def _with_language_filter(config: Config, enabled: bool) -> Config:
    retrieval = config.retrieval.model_copy(update={"language_filter": enabled})
    return config.model_copy(update={"retrieval": retrieval})


def test_language_filter_is_on_by_default() -> None:
    assert Config().retrieval.language_filter is True


def test_spanish_retrieval_returns_only_spanish_passages(
    config: Config, assistant_factory: Callable[..., Assistant]
) -> None:
    on = assistant_factory(config, BINOMIAL_CHUNKS)
    retrieved = on._retriever.retrieve(SPANISH_QUESTION, language="es")
    assert retrieved
    assert {rc.chunk.language for rc in retrieved} == {"es"}


def test_the_filter_is_what_keeps_english_out(
    config: Config, assistant_factory: Callable[..., Assistant]
) -> None:
    """Without the filter the same question retrieves the English passages — the bug."""
    off = assistant_factory(_with_language_filter(config, False), BINOMIAL_CHUNKS)
    retrieved = off._retriever.retrieve(SPANISH_QUESTION, language="es")
    assert "en" in {rc.chunk.language for rc in retrieved}


def test_no_language_means_no_scoping(
    config: Config, assistant_factory: Callable[..., Assistant]
) -> None:
    a = assistant_factory(config, BINOMIAL_CHUNKS)
    assert {rc.chunk.language for rc in a._retriever.retrieve(SPANISH_QUESTION)} == {"en", "es"}


def test_a_spanish_answer_cites_only_spanish_sources(
    config: Config, assistant_factory: Callable[..., Assistant]
) -> None:
    ans = assistant_factory(config, BINOMIAL_CHUNKS).answer(SPANISH_QUESTION, "es")
    assert not ans.refused
    assert ans.citations
    assert all(".es.md" in c.label for c in ans.citations)


def test_an_english_answer_cites_only_english_sources(
    config: Config, assistant_factory: Callable[..., Assistant]
) -> None:
    ans = assistant_factory(config, BINOMIAL_CHUNKS).answer(
        "How often should I water my Monstera deliciosa?", "en"
    )
    assert not ans.refused
    assert ans.citations
    assert all(".es.md" not in c.label for c in ans.citations)


def test_a_species_with_no_passage_in_the_answer_language_is_refused_not_translated(
    config: Config, assistant_factory: Callable[..., Assistant]
) -> None:
    english_only = [c for c in BINOMIAL_CHUNKS if c.language == "en"]
    ans = assistant_factory(config, english_only).answer(SPANISH_QUESTION, "es")
    assert ans.refused
    assert ans.language == "es"
    assert not ans.sentences


@pytest.fixture(scope="module")
def bundled_assistant() -> Assistant:
    cfg = load_config(_ROOT / "config" / "sprout.yaml")
    return Assistant.from_store(cfg, build_index(cfg))


@pytest.mark.integration
@pytest.mark.parametrize(
    "question",
    [
        # The two bundled-corpus reproductions of #168: multilingual-monstera-water-es and
        # safety-023 each rendered an English monstera.md sentence into a Spanish answer.
        SPANISH_QUESTION,
        "Es la Monstera deliciosa toxica para los gatos?",
    ],
)
def test_bundled_corpus_spanish_answers_quote_only_spanish_passages(
    bundled_assistant: Assistant, question: str
) -> None:
    ans = bundled_assistant.answer(question, "es")
    assert not ans.refused
    assert ans.citations
    assert all(".es.md" in c.label for c in ans.citations), [c.label for c in ans.citations]
