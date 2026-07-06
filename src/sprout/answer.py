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
        lang = self._resolve_language(query, language)
        safety = is_safety_query(query, lang, self._config.guards)
        retrieved = self._retriever.retrieve(query)

        if not self._retriever.has_grounding(query, retrieved):
            return self._refuse(query, lang, safety, reason="out_of_scope", abstained=False)

        model_query = redact_pii(query) if self._config.generation.redact_query_pii else query
        candidates = self._generator.generate(
            model_query, retrieved, self._config.generation.max_sentences
        )
        sentences = citation_guard(candidates, retrieved, self._config.generation.support_overlap)
        sentences = safety_filter(sentences, lang, self._config.guards)

        if not sentences:
            return self._refuse(
                query, lang, safety, reason="no_supported_sentences", abstained=False
            )

        confidence = score_confidence(retrieved, len(sentences))
        if should_abstain(confidence, self._config.confidence):
            return self._refuse(
                query, lang, safety, reason="low_confidence", abstained=True, confidence=confidence
            )

        return self._render(query, lang, safety, sentences, retrieved, confidence)

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
    ) -> Answer:
        return Answer(
            question=query,
            language=lang,
            refused=True,
            refusal_reason=reason,
            refusal_text=self._config.prompts.refusal_for(lang),
            is_safety_query=safety,
            safety_notice=self._config.prompts.safety_directive_for(lang) if safety else None,
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
        lang = self._resolve_language(query, language)
        retrieved = self._retriever.retrieve(query)
        candidates = self._generator.generate(
            query, retrieved, self._config.generation.max_sentences
        )
        answer = self.answer(query, language)
        return AnswerTrace(
            query=query,
            language=lang,
            is_safety_query=is_safety_query(query, lang, self._config.guards),
            injection_categories=tuple(detect_injection(query)),
            retrieved=tuple(retrieved),
            raw_candidates=tuple(candidates),
            answer=answer,
        )
