"""The vet / poison-control escort must follow the content, not the wording.

Issue #107. Both the assistant and its TypeScript port decide whether to attach the
poison-control routing by asking what the answer actually *cites*, not only whether the
question tripped the keyword classifier -- deliberately, so a toxicity fact cannot render
without its escort when the question was phrased around symptoms rather than around the
word "toxic".

That check compared a chunk's topic against the literal ``"toxicity"``. A chunk's topic
is the slugified Markdown heading, and 8 of the 16 Spanish corpus documents head their
section ``## Toxicidad``, 7 of them ASPCA-listed as toxic to pets. For those, the content
check could never fire, so the escort survived only where the keyword classifier also
happened to fire. Reproduced against the committed corpus on 2026-08-28: a Spanish
question about oral irritation and drooling rendered Monstera's toxicity paragraph with
``is_safety_query=False`` and no routing at all.

These tests pin both directions -- the Spanish heading routes, and an ordinary care
answer still does not -- so the fix cannot pass by routing everything.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sprout.answer import Assistant
from sprout.chunk import SAFETY_TOPIC_SLUGS, is_safety_topic
from sprout.config import Config
from sprout.models import Chunk


def make_chunk(
    chunk_id: str, source: str, title: str, text: str, topic: str, language: str = "en"
) -> Chunk:
    """A synthetic chunk. Local rather than imported from ``conftest`` because pytest
    does not put the test package on the import path for a non-package test tree."""
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


_ES_TOXICITY_TEXT = (
    "La referencia citada incluye la Monstera (Monstera deliciosa) como toxica para "
    "gatos y perros; la ingestion puede causar irritacion bucal, ardor intenso de la "
    "boca y los labios, salivacion excesiva, vomitos y dificultad para tragar."
)

#: A Spanish document whose toxicity section is headed ``## Toxicidad``, exactly as
#: dracaena, english-ivy, fiddle-leaf-fig, monstera, peace-lily, rubber-plant and
#: snake-plant do in the committed corpus.
_CHUNKS = [
    make_chunk(
        "mon-tox-es",
        "monstera.es.md",
        "Cuidado de la Monstera",
        _ES_TOXICITY_TEXT,
        topic="toxicidad",
        language="es",
    ),
    make_chunk(
        "mon-water-es",
        "monstera.es.md",
        "Cuidado de la Monstera",
        "Las hojas amarillas de la Monstera suelen indicar exceso de riego. "
        "Deja secar los primeros 5 centimetros de tierra antes de regar.",
        topic="riego",
        language="es",
    ),
]


@pytest.fixture
def es_assistant(config: Config, assistant_factory: Callable[..., Assistant]) -> Assistant:
    return assistant_factory(config, list(_CHUNKS))


def test_a_spanish_toxicity_chunk_routes_without_a_lexicon_keyword(
    es_assistant: Assistant,
) -> None:
    """The reproduction from issue #107, phrased around symptoms rather than toxicity."""
    answer = es_assistant.answer(
        "Por que mi Monstera causa irritacion bucal y salivacion excesiva?",
        language="es",
    )
    assert not answer.refused
    assert any(s.citation.chunk_id == "mon-tox-es" for s in answer.sentences), (
        "the test needs the toxicity chunk to be the cited one"
    )
    assert answer.is_safety_query, (
        "a rendered toxicity fact must carry the vet / poison-control escort even when "
        "the question contained no keyword the classifier recognises"
    )
    assert answer.safety_notice, "routing was claimed but no notice was attached"


def test_an_ordinary_spanish_care_answer_still_does_not_route(
    config: Config, assistant_factory: Callable[..., Assistant]
) -> None:
    """The other direction, so the test above cannot pass by routing every answer.

    A corpus holding only care prose: nothing here is toxicity content, so nothing
    should attach a poison-control card. A router that routed on language, or on the
    presence of any Spanish chunk, would fail this.
    """
    assistant = assistant_factory(config, [_CHUNKS[1]])
    answer = assistant.answer("Por que se ponen amarillas las hojas de mi Monstera?", language="es")
    assert not answer.refused
    assert not answer.is_safety_query
    assert answer.safety_notice is None


def test_the_english_heading_still_routes(
    config: Config, assistant_factory: Callable[..., Assistant]
) -> None:
    """The behaviour that already worked must keep working."""
    assistant = assistant_factory(
        config,
        [
            make_chunk(
                "pothos-tox",
                "pothos.md",
                "Pothos care",
                "The cited source lists Pothos as toxic to cats and dogs; ingestion can "
                "cause oral irritation, intense burning of the mouth and drooling.",
                topic="toxicity",
            )
        ],
    )
    answer = assistant.answer("Why does my Pothos cause drooling and mouth burning?")
    assert not answer.refused
    assert answer.is_safety_query
    assert answer.safety_notice


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("toxicity", True),
        ("toxicidad", True),
        ("safety", True),
        ("seguridad", True),
        ("watering", False),
        ("riego", False),
        ("", False),
        (None, False),
    ],
)
def test_is_safety_topic_reads_both_languages(topic: str | None, expected: bool) -> None:
    assert is_safety_topic(topic) is expected


def test_the_slug_set_is_not_empty() -> None:
    # An empty set would make every parametrized False case above pass and every True
    # case fail, so the emptiness is worth asserting on its own.
    assert len(SAFETY_TOPIC_SLUGS) >= 4
