"""Core domain models — frozen, typed, and provider-agnostic.

These are the only types that cross module boundaries (ingest -> retrieve ->
answer -> guard -> server). Every model forbids extra fields and is immutable, so
a typo fails loudly at construction and no stage can mutate another stage's data.

Sprout extends the usual RAG citation with ``license`` and ``fetch_date`` (every
passage is dated and licensed, surfaced as "based on references as of <date>"), and
tags every answer sentence with a ``provenance`` so the post-generation guard can
enforce the corpus-vs-household rule the Family Greenhouse integration depends on.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Provenance = Literal["corpus", "household"]


class _Frozen(BaseModel):
    """Immutable base that rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Document(_Frozen):
    """A whole source document, before chunking, with its dated provenance."""

    doc_id: str
    source: str  # path relative to the corpus root; the stable citation key
    title: str
    language: str
    text: str
    source_name: str  # human-facing publisher/title from the manifest
    url: str
    license: str
    fetch_date: str  # ISO-8601 date the snapshot was taken
    topic: str = "general"


class Chunk(_Frozen):
    """A retrievable passage carrying everything a citation needs."""

    chunk_id: str
    doc_id: str
    title: str
    source: str
    text: str
    language: str
    topic: str
    source_name: str
    url: str
    license: str
    fetch_date: str

    @property
    def citation_label(self) -> str:
        """Human-facing citation string, e.g. 'Monstera care — monstera.md (as of 2026-05-01)'."""
        return f"{self.title} — {self.source} (as of {self.fetch_date})"


class RetrievedChunk(_Frozen):
    """A chunk paired with its retrieval score (always the cosine score, even under hybrid)."""

    chunk: Chunk
    score: float


class Citation(_Frozen):
    """A resolved citation: the passage a rendered sentence is grounded in."""

    chunk_id: str
    doc_id: str
    title: str
    source: str
    quote: str
    license: str
    fetch_date: str
    url: str

    @property
    def label(self) -> str:
        return f"{self.title} — {self.source} (as of {self.fetch_date})"


class AnswerSentence(_Frozen):
    """One rendered sentence: verbatim text, its citation, and its provenance tag."""

    text: str
    chunk_id: str
    citation: Citation
    provenance: Provenance = "corpus"


class ConfidenceEvidence(_Frozen):
    """Retrieval evidence for one question, captured *without* applying the confidence
    gate — the (best cosine score, margin over runner-up) pair `confidence.py` maps to a
    [0, 1] score, plus whether a grounded, guard-surviving answer actually resulted.

    Collected by :meth:`sprout.answer.Assistant.confidence_signal` for `sprout
    fit-confidence`, which needs this evidence independent of whatever threshold is
    *currently* configured — using the live threshold to decide what counts as training
    signal for a new one would be circular.
    """

    query: str
    best: float
    margin: float
    grounded: bool
    text: str


class SourceDisagreement(_Frozen):
    """Two retrieved passages that state a conflicting numeric care cadence for the
    same action ("water every 7 days" vs "water every 14 days").

    The pairwise contradiction probe in ``disagreement.py`` never averages and never
    silently picks a winner between the two candidate chunks — both mentions and both
    citations are always carried together so the answer can disclose the conflict
    instead of rendering whichever chunk happened to rank first (EXP-02,
    ``docs/ideation/03-expansions.md``).
    """

    action: str
    mention_a: str
    citation_a: Citation
    mention_b: str
    citation_b: Citation


class Answer(_Frozen):
    """The final, guard-checked answer object returned to callers and the UI.

    ``season`` and ``light`` (EXP-05) echo back exactly what the caller passed to
    ``Assistant.answer`` on *this one request* — the same selector-not-fact contract
    ADR-0010 established for photo-ID, generalized to season/placement qualifiers. They
    only ever influenced *which* already-cited sentence in ``sentences`` was chosen;
    they are never themselves a citation, never appear as a fact, and are never
    persisted anywhere (no field on this model is written to disk by the engine).
    ``context_note`` is the localized, user-facing echo of the two, or ``None`` if
    neither was supplied.
    """

    question: str
    language: str
    sentences: tuple[AnswerSentence, ...] = Field(default_factory=tuple)
    retrieved: tuple[RetrievedChunk, ...] = Field(default_factory=tuple)
    refused: bool = False
    refusal_reason: str | None = None
    refusal_text: str | None = None
    is_safety_query: bool = False
    # FIX-13: "child", "animal", "both", or "unspecified" -- the exposure audience the
    # safety classifier detected, used to select which escalation card(s) render. None
    # when the answer/refusal was not a safety query at all.
    exposure_type: str | None = None
    safety_notice: str | None = None
    confidence: float = 0.0
    low_confidence: bool = False
    abstained: bool = False
    disclosure: str = ""
    as_of: str | None = None
    disagreements: tuple[SourceDisagreement, ...] = Field(default_factory=tuple)
    disagreement_notices: tuple[str, ...] = Field(default_factory=tuple)
    # Verbalized, screen-reader-first confidence band (EXP-06): calibrated language
    # derived from the reliability diagram, shown alongside — never instead of —
    # ``confidence``. ``confidence_band`` is the stable machine key (aria/CSS hooks,
    # eval assertions); ``confidence_band_label`` is the localized string a screen
    # reader announces.
    confidence_band: str = "insufficient_evidence"
    confidence_band_label: str = ""
    season: str | None = None
    light: str | None = None
    context_note: str | None = None

    @property
    def text(self) -> str:
        """The concatenated answer prose (citation-verified sentences only)."""
        return " ".join(s.text for s in self.sentences)

    @property
    def display_text(self) -> str:
        """What the user sees: cited sentences plus any (uncited) safety directive.

        The safety notice is a routing directive ("contact your vet"), not a
        horticultural claim, so it is exempt from the citation rule — but it is part
        of the rendered answer and is what the safety eval suite checks for routing.
        """
        parts = [self.refusal_text or ""] if self.refused else [s.text for s in self.sentences]
        if self.safety_notice:
            parts.append(self.safety_notice)
        parts.extend(self.disagreement_notices)
        return " ".join(p for p in parts if p).strip()

    @property
    def citations(self) -> tuple[Citation, ...]:
        """Unique citations in first-appearance order."""
        seen: set[str] = set()
        out: list[Citation] = []
        for s in self.sentences:
            if s.chunk_id not in seen:
                seen.add(s.chunk_id)
                out.append(s.citation)
        return tuple(out)

    @property
    def citation_coverage(self) -> float:
        """Fraction of rendered sentences carrying a citation — 1.0 by construction.

        The citation guard drops any sentence it cannot resolve to a retrieved
        chunk, so every sentence that survives into ``sentences`` has a citation.
        A refusal (no sentences) reports 0.0.
        """
        if not self.sentences:
            return 0.0
        return sum(1 for s in self.sentences if s.citation is not None) / len(self.sentences)
