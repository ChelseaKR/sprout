"""The Assistant: prompt assembly -> retrieve -> generate -> guard -> answer.

This module encodes the pipeline contract as control flow:

1. Retrieval is mandatory and first. If no retrieved chunk clears ``min_score`` the
   assistant refuses — it never asks the generator to fill the gap.
2. The generator may only return sentences tagged to retrieved chunks.
3. The citation guard independently re-verifies every sentence; whatever survives *is*
   the answer. If nothing survives, that is a refusal.
4. The never-certify-safe guard drops any surviving sentence that asserts safety.
5. Confidence is computed from retrieval evidence; below the abstain threshold the
   assistant refuses rather than guesses.

For toxicity/safety questions, the refusal *and* the answer carry a routing directive to
a vet / poison-control line, and the assistant never certifies a plant safe.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .answer_trace import AnswerTrace
from .confidence import is_low_confidence, score_confidence, should_abstain
from .config import Config
from .guards import (
    citation_guard,
    detect_injection,
    is_safety_query,
    redact_pii,
    safety_filter,
)
from .lang import detect_language
from .models import Answer, AnswerSentence, RetrievedChunk
from .providers import build_embedding, build_generator
from .providers.base import EmbeddingProvider, GenerationProvider
from .retrieve import Retriever
from .store import VectorStore


class Assistant:
    """Grounded, guarded, calibrated plant-care assistant over a populated store."""

    def __init__(
        self,
        config: Config,
        store: VectorStore,
        embedder: EmbeddingProvider,
        generator: GenerationProvider,
    ) -> None:
        self._config = config
        self._store = store
        self._generator = generator
        self._retriever = Retriever(config, store, embedder)

    @classmethod
    def from_store(cls, config: Config, store: VectorStore) -> Assistant:
        return cls(config, store, build_embedding(config), build_generator(config))

    @classmethod
    def from_config(cls, config: Config) -> Assistant:
        """Load the persisted index from ``config.store.path`` and build the assistant."""
        return cls.from_store(config, VectorStore.load(config.store.path))

    def _resolve_language(self, query: str, language: str | None) -> str:
        supported = self._config.languages.supported
        if language is not None and language in supported:
            return language
        detected = detect_language(query, default=self._config.corpus.default_language)
        return detected if detected in supported else self._config.corpus.default_language

    def answer(self, query: str, language: str | None = None) -> Answer:
        answer, _, _ = self._answer_with_details(query, language)
        return answer

    def _answer_with_details(
        self, query: str, language: str | None = None
    ) -> tuple[Answer, list[RetrievedChunk], list[tuple[str, str]]]:
        """Run the pipeline once and retain the retrieval/generation debug details."""
        lang = self._resolve_language(query, language)
        safety = is_safety_query(query, lang, self._config.guards)
        retrieved = self._retriever.retrieve(query)

        # Hard species gate: a toxicity/safety question that clearly names a plant not
        # in the corpus (via the off-corpus gazetteer) is refused before the grounding
        # check runs, so a spurious low-score match can never masquerade as coverage.
        if safety and self._retriever.names_uncovered_species(query):
            return (
                self._refuse(
                    query,
                    lang,
                    safety,
                    reason="species_not_covered",
                    abstained=False,
                    retrieved=retrieved,
                ),
                retrieved,
                [],
            )

        if not self._retriever.has_grounding(query, retrieved):
            return (
                self._refuse(
                    query,
                    lang,
                    safety,
                    reason="out_of_scope",
                    abstained=False,
                    retrieved=retrieved,
                ),
                retrieved,
                [],
            )

        model_query = redact_pii(query) if self._config.generation.redact_query_pii else query
        cost_reason = self._generation_cost_refusal(model_query, retrieved)
        if cost_reason is not None:
            return (
                self._refuse(
                    query,
                    lang,
                    safety,
                    reason=cost_reason,
                    abstained=False,
                    retrieved=retrieved,
                ),
                retrieved,
                [],
            )
        candidates = self._generator.generate(
            model_query, retrieved, self._config.generation.max_sentences
        )
        sentences = citation_guard(candidates, retrieved, self._config.generation.support_overlap)
        sentences = safety_filter(sentences, lang, self._config.guards)

        if not sentences:
            return (
                self._refuse(
                    query,
                    lang,
                    safety,
                    reason="no_supported_sentences",
                    abstained=False,
                    retrieved=retrieved,
                ),
                retrieved,
                candidates,
            )

        confidence = score_confidence(retrieved, len(sentences))
        if should_abstain(confidence, self._config.confidence):
            return (
                self._refuse(
                    query,
                    lang,
                    safety,
                    reason="low_confidence",
                    abstained=True,
                    confidence=confidence,
                    retrieved=retrieved,
                ),
                retrieved,
                candidates,
            )

        return (
            self._render(query, lang, safety, sentences, retrieved, confidence),
            retrieved,
            candidates,
        )

    def _generation_cost_refusal(self, query: str, retrieved: list[RetrievedChunk]) -> str | None:
        """Fail closed before generation when cost cannot be bounded."""
        try:
            estimate = self._generator.estimated_cost_usd(query, retrieved)
        except Exception:
            return "generation_cost_unavailable"
        if estimate is None or not math.isfinite(estimate) or estimate < 0:
            return "generation_model_unpriced"
        if estimate > self._config.generation.max_cost_usd:
            return "generation_cost_limit_exceeded"
        return None

    def _render(
        self,
        query: str,
        lang: str,
        safety: bool,
        sentences: list[AnswerSentence],
        retrieved: list[RetrievedChunk],
        confidence: float,
    ) -> Answer:
        citations = [s.citation for s in sentences]
        as_of = max((c.fetch_date for c in citations), default=None)
        # Route to a vet / poison-control line whenever the question was classified a
        # safety query OR any rendered sentence cites a toxicity passage — so the routing
        # is a property of the content shown, not only of the input keywords.
        topic_by_id = {rc.chunk.chunk_id: rc.chunk.topic for rc in retrieved}
        toxicity_cited = any(topic_by_id.get(s.chunk_id) == "toxicity" for s in sentences)
        route = safety or toxicity_cited
        return Answer(
            question=query,
            language=lang,
            sentences=tuple(sentences),
            retrieved=tuple(retrieved),
            refused=False,
            is_safety_query=route,
            safety_notice=self._config.prompts.safety_directive_for(lang) if route else None,
            confidence=round(confidence, 4),
            low_confidence=is_low_confidence(confidence, self._config.confidence),
            abstained=False,
            disclosure=self._config.prompts.disclosure_for(lang),
            as_of=as_of,
        )

    def _refuse(
        self,
        query: str,
        lang: str,
        safety: bool,
        *,
        reason: str,
        abstained: bool,
        confidence: float = 0.0,
        retrieved: Sequence[RetrievedChunk] = (),
    ) -> Answer:
        # Route to a vet / poison-control line whenever the question was classified a
        # safety query OR the retrieved evidence itself cites a toxicity passage — so a
        # refusal still routes even when the input keywords alone did not trip `safety`.
        toxicity_cited = any(rc.chunk.topic == "toxicity" for rc in retrieved)
        route = safety or toxicity_cited
        return Answer(
            question=query,
            language=lang,
            refused=True,
            refusal_reason=reason,
            refusal_text=self._config.prompts.refusal_for(lang),
            is_safety_query=route,
            safety_notice=self._config.prompts.safety_directive_for(lang) if route else None,
            confidence=round(confidence, 4),
            low_confidence=True,
            abstained=abstained,
            disclosure=self._config.prompts.disclosure_for(lang),
        )

    def resolve_language(self, query: str, language: str | None = None) -> str:
        """Public language resolution (used by the photo-ID path)."""
        return self._resolve_language(query, language)

    def species_slugs(self) -> set[str]:
        """Canonical species slugs present in the loaded corpus (for photo-ID routing)."""
        from .retrieve import species_slug

        return {species_slug(chunk.source) for chunk in self._store.all_chunks()}

    def trace(self, query: str, language: str | None = None) -> AnswerTrace:
        """Return the full retrieval+generation trace for debugging (``--debug``)."""
        answer, retrieved, candidates = self._answer_with_details(query, language)
        return AnswerTrace(
            query=query,
            language=answer.language,
            is_safety_query=is_safety_query(query, answer.language, self._config.guards),
            injection_categories=tuple(detect_injection(query)),
            retrieved=tuple(retrieved),
            raw_candidates=tuple(candidates),
            answer=answer,
        )
