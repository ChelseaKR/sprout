"""The provider seam: two small Protocols the engine depends on.

Everything model-touching hides behind ``EmbeddingProvider`` and ``GenerationProvider``.
The offline deterministic stack and the Claude-on-Bedrock stack are interchangeable
implementations; callers never import a concrete provider. The generator contract is
deliberately narrow — it may only return ``(sentence, chunk_id)`` pairs drawn from the
supplied context, and the citation guard rejects anything not actually supported, so a
misbehaving provider degrades to a refusal rather than an ungrounded answer.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import RetrievedChunk


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Maps text to a fixed-length, L2-normalised dense vector."""

    @property
    def dim(self) -> int: ...

    def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class GenerationProvider(Protocol):
    """Produces candidate answer sentences, each attributed to a retrieved chunk.

    Implementations MUST only emit content supported by ``context``. The return value
    is a list of ``(sentence_text, chunk_id)`` tuples; the pipeline's citation guard
    independently re-verifies each one and drops the rest.

    ``boost_terms`` is the (optional) season/light context-qualifier selector (EXP-05):
    lexical tokens from the user's own words, used only to nudge *which* already-cited
    sentence is chosen among otherwise-tied candidates. It is a selector, never a fact —
    implementations MUST NOT let it admit a sentence that is not already supported by
    ``context``, and MUST NOT surface it as generated content.
    """

    def generate(
        self,
        query: str,
        context: list[RetrievedChunk],
        max_sentences: int,
        boost_terms: frozenset[str] = frozenset(),
    ) -> list[tuple[str, str]]: ...

    def estimated_cost_usd(self, query: str, context: list[RetrievedChunk]) -> float: ...


def context_hint(boost_terms: frozenset[str]) -> str:
    """A one-line prompt addendum for the cloud generators (EXP-05).

    Spells out, for the model, that the season/light selector is user-stated context to
    weigh when choosing among the cited sources — never a fact to assert or quote as if
    it came from a source.
    """
    if not boost_terms:
        return ""
    words = ", ".join(sorted(boost_terms))
    return (
        "\n\nUSER-STATED CONTEXT (not a source, not a fact — use only to choose which "
        f"cited source best answers the question): {words}."
    )
