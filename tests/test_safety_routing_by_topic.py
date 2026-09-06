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
from pathlib import Path

import pytest

from sprout.answer import Assistant
from sprout.chunk import SAFETY_TOPIC_SLUGS, is_safety_topic
from sprout.config import Config
from sprout.models import Chunk
from sprout.review import ReviewQueue


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


def test_the_trace_and_the_review_record_report_the_routing_that_happened(
    es_assistant: Assistant,
    assistant_factory: Callable[..., Assistant],
    tmp_path: Path,
) -> None:
    """The debug trace said ``safety=False`` about an answer carrying a poison-control card.

    ``Assistant.trace`` filled ``is_safety_query`` from the input-keyword classifier while
    the answer beside it had routed on the topic of the content it cited. Re-running issue
    #107's own reproduction after the routing fix still printed ``safety=False`` under
    ``--debug``, which reads as "unfixed" and is the opposite of what the answer did.
    ``ReviewQueue.capture`` copied the same field, so a flagged item whose answer had
    printed the vet / poison-control routing was filed for a human reviewer as
    ``is_safety_query: false``.

    The trace now reports the decision and, separately, whether the keyword classifier
    was what caused it.
    """
    query = "Por que mi Monstera causa irritacion bucal y salivacion excesiva?"
    trace = es_assistant.trace(query, language="es")

    assert trace.answer.is_safety_query, "the routing fix itself must still hold"
    assert trace.is_safety_query == trace.answer.is_safety_query, (
        "the trace must report the routing the answer took, not the classifier's half"
    )
    assert not trace.safety_query_by_keyword, (
        "this question deliberately contains no keyword the classifier recognises; if it "
        "did, the test would no longer exercise the content-routed path"
    )

    # The review queue only captures flagged answers, so re-run the same question through
    # an assistant whose low-confidence threshold flags everything. Nothing else changes:
    # the routing and the classifier verdict are the ones asserted above.
    flagging = assistant_factory(
        Config.model_validate({"confidence": {"low_confidence_threshold": 0.99}}),
        list(_CHUNKS),
    )
    flagged = flagging.trace(query, language="es")
    assert flagged.answer.low_confidence and flagged.answer.is_safety_query
    queue = ReviewQueue(tmp_path / "review.json")
    item = queue.capture(flagged)
    assert item is not None, "the reproduction must be flagged for review to be recorded"
    assert item.is_safety_query is flagged.answer.is_safety_query, (
        "a review item whose answer routed to poison control must not be filed as "
        "is_safety_query: false"
    )


def test_a_keyword_classified_question_reports_the_keyword_as_the_cause(
    es_assistant: Assistant,
) -> None:
    """The other half: when the classifier does fire, the trace says so.

    Without this, setting ``safety_query_by_keyword`` to a constant ``False`` would pass
    the test above and lose the diagnostic the field exists to carry.
    """
    trace = es_assistant.trace("Es toxica la Monstera para mi gato?", language="es")
    assert trace.is_safety_query
    assert trace.safety_query_by_keyword


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
