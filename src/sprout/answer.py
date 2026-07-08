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

from collections.abc import Sequence

from .answer_trace import AnswerTrace
from .confidence import best_and_margin, is_low_confidence, score_confidence, should_abstain
from .config import Config
from .disagreement import numeric_cadence_conflicts
from .guards import (
    citation_guard,
    detect_exposure_type,
    detect_injection,
    is_safety_query,
    redact_pii,
    safety_filter,
)
from .lang import detect_language
from .models import Answer, AnswerSentence, ConfidenceEvidence, RetrievedChunk
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

    def _retrieve_and_render(
        self, query: str, lang: str
    ) -> tuple[list[RetrievedChunk], list[AnswerSentence], bool]:
        """Retrieval + generation + guards, stopping short of the confidence gate.

        Returns ``(retrieved, sentences, grounded)``. Shared by :meth:`answer` (which
        applies the confidence/abstain gate on top) and :meth:`confidence_signal` (which
        needs the same evidence *without* the gate: using the currently configured
        threshold to decide what counts as training signal for a new one would be
        circular).
        """
        retrieved = self._retriever.retrieve(query)
        if not self._retriever.has_grounding(query, retrieved):
            return retrieved, [], False

        model_query = redact_pii(query) if self._config.generation.redact_query_pii else query
        candidates = self._generator.generate(
            model_query, retrieved, self._config.generation.max_sentences
        )
        sentences = citation_guard(candidates, retrieved, self._config.generation.support_overlap)
        sentences = safety_filter(sentences, lang, self._config.guards)
        return retrieved, sentences, True

    def answer(self, query: str, language: str | None = None) -> Answer:
        lang = self._resolve_language(query, language)
        safety = is_safety_query(query, lang, self._config.guards)
        # FIX-13: classify the audience (child/animal/both/unspecified) alongside the
        # existing safety classification, so a rendered or refused safety answer can
        # route to the right escalation card(s) once a clinician-reviewed human card
        # exists. See Config.prompts.safety_directive_for.
        exposure_type = detect_exposure_type(query, lang, self._config.guards) if safety else None
        retrieved, sentences, grounded = self._retrieve_and_render(query, lang)

        # Hard species gate: a toxicity/safety question that clearly names a plant not
        # in the corpus (via the off-corpus gazetteer) is refused before the grounding
        # outcome is consulted, so a spurious low-score match can never masquerade as
        # coverage. Any generated sentences for such a query are discarded unrendered.
        if safety and self._retriever.names_uncovered_species(query):
            return self._refuse(
                query,
                lang,
                safety,
                exposure_type,
                reason="species_not_covered",
                abstained=False,
                retrieved=retrieved,
            )

        if not grounded:
            return self._refuse(
                query,
                lang,
                safety,
                exposure_type,
                reason="out_of_scope",
                abstained=False,
                retrieved=retrieved,
            )

        if not sentences:
            return self._refuse(
                query,
                lang,
                safety,
                exposure_type,
                reason="no_supported_sentences",
                abstained=False,
                retrieved=retrieved,
            )

        confidence = score_confidence(retrieved, len(sentences), self._config.confidence)
        if should_abstain(confidence, self._config.confidence):
            return self._refuse(
                query,
                lang,
                safety,
                exposure_type,
                reason="low_confidence",
                abstained=True,
                confidence=confidence,
                retrieved=retrieved,
            )

        return self._render(query, lang, safety, exposure_type, sentences, retrieved, confidence)

    def confidence_signal(self, query: str, language: str | None = None) -> ConfidenceEvidence:
        """Retrieval evidence for one question, without applying the confidence gate.

        Used by ``sprout fit-confidence`` to collect (best, margin) -> outcome pairs over
        a train split. See :class:`~sprout.models.ConfidenceEvidence`.
        """
        lang = self._resolve_language(query, language)
        retrieved, sentences, grounded = self._retrieve_and_render(query, lang)
        best, margin = best_and_margin(retrieved)
        return ConfidenceEvidence(
            query=query,
            best=best,
            margin=margin,
            grounded=grounded,
            text=" ".join(s.text for s in sentences),
        )

    def _render(
        self,
        query: str,
        lang: str,
        safety: bool,
        exposure_type: str | None,
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
        # A toxicity-cited (but not keyword-classified) query never had its exposure type
        # detected above; classify it now so the card still routes correctly.
        route_exposure = (
            exposure_type
            if safety
            else (detect_exposure_type(query, lang, self._config.guards) if route else None)
        )
        # EXP-02: a pairwise numeric-cadence probe over every retrieved sibling chunk
        # (not only the ones quoted) — when two sources give a different cadence for the
        # same care action, surface both citations instead of only the one that ranked
        # first. The probe only ever compares chunks sharing a topic, so a toxicity-topic
        # conflict is always also caught by ``toxicity_cited`` above and still routes
        # conservatively to the safety path.
        disagreements = numeric_cadence_conflicts(sentences, retrieved)
        disagreement_notices = tuple(
            self._config.prompts.disagreement_notice_for(
                lang, d.mention_a, d.citation_a.label, d.mention_b, d.citation_b.label
            )
            for d in disagreements
        )
        return Answer(
            question=query,
            language=lang,
            sentences=tuple(sentences),
            retrieved=tuple(retrieved),
            refused=False,
            is_safety_query=route,
            exposure_type=route_exposure,
            safety_notice=(
                self._config.prompts.safety_directive_for(lang, route_exposure) if route else None
            ),
            confidence=round(confidence, 4),
            low_confidence=is_low_confidence(confidence, self._config.confidence),
            abstained=False,
            disclosure=self._config.prompts.disclosure_for(lang),
            as_of=as_of,
            disagreements=disagreements,
            disagreement_notices=disagreement_notices,
        )

    def _refuse(
        self,
        query: str,
        lang: str,
        safety: bool,
        exposure_type: str | None,
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
        # A toxicity-cited (but not keyword-classified) refusal never had its exposure
        # type detected in answer(); classify it now so the card still routes correctly.
        route_exposure = (
            exposure_type
            if safety
            else (detect_exposure_type(query, lang, self._config.guards) if route else None)
        )
        return Answer(
            question=query,
            language=lang,
            refused=True,
            refusal_reason=reason,
            refusal_text=self._config.prompts.refusal_for(lang),
            is_safety_query=route,
            exposure_type=route_exposure,
            safety_notice=(
                self._config.prompts.safety_directive_for(lang, route_exposure) if route else None
            ),
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
