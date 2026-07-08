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

``season``/``light`` (EXP-05) are an optional, per-request selector — the same
context-selects/corpus-asserts contract ADR-0010 built for photo-ID, generalized to the
season/placement qualifiers a user can just state ("winter", "north window"). They are
taken exactly as given, never inferred from locale or the system clock, used only to
nudge which already-cited sentence the generator picks, and echoed back on the ``Answer``
— never persisted, never treated as a citation.

An optional ``history`` (:class:`~sprout.models.Turn`, EXP-07) may resolve which species a
follow-up is about when the query itself names none. It is consulted in exactly one place —
as a fallback input to ``Retriever``'s candidate filter — and nowhere else in this pipeline:
it never reaches ``model_query``, the generator, or the citation guard, so history can narrow
*which* corpus passages are searched but can never add, remove, or override a cited fact.
"""

from __future__ import annotations

from collections.abc import Sequence

from .answer_trace import AnswerTrace
from .confidence import (
    best_and_margin,
    confidence_band,
    is_low_confidence,
    score_confidence,
    should_abstain,
)
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
from .models import Answer, AnswerSentence, ConfidenceEvidence, RetrievedChunk, Turn
from .providers import build_embedding, build_entailment_verifier, build_generator
from .providers.base import EmbeddingProvider, GenerationProvider
from .retrieve import Retriever
from .store import VectorStore
from .text import token_set
from .verifiers import EntailmentVerifier


class Assistant:
    """Grounded, guarded, calibrated plant-care assistant over a populated store."""

    def __init__(
        self,
        config: Config,
        store: VectorStore,
        embedder: EmbeddingProvider,
        generator: GenerationProvider,
        entailment_verifier: EntailmentVerifier | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._generator = generator
        # EXP-04: only set when `generation.support_verifier: nli` is configured, which
        # config validation already restricts to the cloud (non-deterministic) path — see
        # `providers.build_entailment_verifier`.
        self._entailment_verifier = entailment_verifier
        self._retriever = Retriever(config, store, embedder)

    @classmethod
    def from_store(cls, config: Config, store: VectorStore) -> Assistant:
        return cls(
            config,
            store,
            build_embedding(config),
            build_generator(config),
            build_entailment_verifier(config),
        )

    @classmethod
    def from_config(cls, config: Config) -> Assistant:
        """Load the persisted index from ``config.store.path`` and build the assistant."""
        return cls.from_store(config, VectorStore.load(config.store.path))

    def _resolve_language(
        self, query: str, language: str | None, history: Turn | None = None
    ) -> str:
        supported = self._config.languages.supported
        if language is not None and language in supported:
            return language
        fallback = (
            history.language
            if history is not None and history.language in supported
            else self._config.corpus.default_language
        )
        detected = detect_language(query, default=fallback)
        return detected if detected in supported else fallback

    def _retrieve_and_render(
        self,
        query: str,
        lang: str,
        *,
        season: str | None = None,
        light: str | None = None,
        history_species: str | None = None,
    ) -> tuple[list[RetrievedChunk], list[AnswerSentence], bool]:
        """Retrieval + generation + guards, stopping short of the confidence gate.

        Returns ``(retrieved, sentences, grounded)``. Shared by :meth:`answer` (which
        applies the confidence/abstain gate on top) and :meth:`confidence_signal` (which
        needs the same evidence *without* the gate: using the currently configured
        threshold to decide what counts as training signal for a new one would be
        circular).
        """
        retrieved = self._retriever.retrieve(query, history_species=history_species)
        if not self._retriever.has_grounding(query, retrieved):
            return retrieved, [], False

        model_query = redact_pii(query) if self._config.generation.redact_query_pii else query
        boost_terms = self._context_boost_terms(season, light)
        candidates = self._generator.generate(
            model_query, retrieved, self._config.generation.max_sentences, boost_terms
        )
        sentences = citation_guard(
            candidates,
            retrieved,
            self._config.generation.support_overlap,
            self._entailment_verifier,
        )
        sentences = safety_filter(sentences, lang, self._config.guards)
        return retrieved, sentences, True

    def answer(
        self,
        query: str,
        language: str | None = None,
        history: Turn | None = None,
        *,
        season: str | None = None,
        light: str | None = None,
    ) -> Answer:
        """Answer ``query``, optionally resolving species from a prior turn's selector.

        ``history`` (EXP-07) is a fallback only: if the query itself names a species, that
        species wins outright and ``history`` is not consulted at all.
        """
        lang = self._resolve_language(query, language, history)
        safety = is_safety_query(query, lang, self._config.guards)
        # FIX-13: classify the audience (child/animal/both/unspecified) alongside the
        # existing safety classification, so a rendered or refused safety answer can
        # route to the right escalation card(s) once a clinician-reviewed human card
        # exists. See Config.prompts.safety_directive_for.
        exposure_type = detect_exposure_type(query, lang, self._config.guards) if safety else None
        history_species = history.species_slug if history is not None else None
        retrieved, sentences, grounded = self._retrieve_and_render(
            query, lang, season=season, light=light, history_species=history_species
        )

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
                season=season,
                light=light,
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
                season=season,
                light=light,
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
                season=season,
                light=light,
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
                season=season,
                light=light,
            )

        return self._render(
            query,
            lang,
            safety,
            exposure_type,
            sentences,
            retrieved,
            confidence,
            season=season,
            light=light,
        )

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

    @staticmethod
    def _context_boost_terms(season: str | None, light: str | None) -> frozenset[str]:
        """Selector-only lexical boost tokens for the season/light qualifiers (EXP-05).

        Tokenized the same way as every other retrieval-facing text (``text.token_set``)
        so the words are compared on equal footing with the corpus's own prose — no new
        corpus metadata, no controlled vocabulary to maintain. An unrecognized word simply
        contributes no boost; it can never *filter out* a governing passage.
        """
        return token_set(season or "") | token_set(light or "")

    def _context_items(self, season: str | None, light: str | None) -> list[str]:
        return [v for v in (season, light) if v]

    def _render(
        self,
        query: str,
        lang: str,
        safety: bool,
        exposure_type: str | None,
        sentences: list[AnswerSentence],
        retrieved: list[RetrievedChunk],
        confidence: float,
        *,
        season: str | None = None,
        light: str | None = None,
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
        band = confidence_band(confidence, self._config.confidence)
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
            confidence_band=band,
            confidence_band_label=self._config.prompts.confidence_band_label_for(band, lang),
            season=season,
            light=light,
            context_note=self._config.prompts.context_note_for(
                lang, self._context_items(season, light)
            ),
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
        season: str | None = None,
        light: str | None = None,
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
        band = confidence_band(confidence, self._config.confidence)
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
            confidence_band=band,
            confidence_band_label=self._config.prompts.confidence_band_label_for(band, lang),
            season=season,
            light=light,
            context_note=self._config.prompts.context_note_for(
                lang, self._context_items(season, light)
            ),
        )

    def resolve_language(self, query: str, language: str | None = None) -> str:
        """Public language resolution (used by the photo-ID path)."""
        return self._resolve_language(query, language)

    def species_slugs(self) -> set[str]:
        """Canonical species slugs present in the loaded corpus (for photo-ID routing)."""
        from .retrieve import species_slug

        return {species_slug(chunk.source) for chunk in self._store.all_chunks()}

    def trace(
        self,
        query: str,
        language: str | None = None,
        *,
        season: str | None = None,
        light: str | None = None,
    ) -> AnswerTrace:
        """Return the full retrieval+generation trace for debugging (``--debug``)."""
        lang = self._resolve_language(query, language)
        retrieved = self._retriever.retrieve(query)
        boost_terms = self._context_boost_terms(season, light)
        candidates = self._generator.generate(
            query, retrieved, self._config.generation.max_sentences, boost_terms
        )
        answer = self.answer(query, language, season=season, light=light)
        return AnswerTrace(
            query=query,
            language=lang,
            is_safety_query=is_safety_query(query, lang, self._config.guards),
            injection_categories=tuple(detect_injection(query)),
            retrieved=tuple(retrieved),
            raw_candidates=tuple(candidates),
            answer=answer,
        )
