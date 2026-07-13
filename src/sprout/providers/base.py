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
    """

    def generate(
        self, query: str, context: list[RetrievedChunk], max_sentences: int
    ) -> list[tuple[str, str]]: ...

    def estimated_cost_usd(self, query: str, context: list[RetrievedChunk]) -> float | None:
        """Conservative preflight estimate, or ``None`` when the model is unpriced.

        Callers must fail closed on ``None``; an unknown model is never treated as free.
        """
        ...
