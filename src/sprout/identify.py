"""Photo plant-ID -> grounded care lookup, with grounding preserved by construction.

A plant photograph is identified by a pluggable vision identifier that returns a
**species name and a visual-match score** — a *selector*, never a horticultural fact.
The resolved species is then routed back through the unchanged grounded care-RAG
(``Assistant.answer``), so every rendered claim is still retrieval-mandatory, cited,
and run through the never-certify-safe guard. The visual identification is surfaced
separately and labelled "a visual match, not a cited fact"; it never enters
``Answer.sentences`` and is never presented as grounded.

This mirrors the Family-Greenhouse contract already documented in the README: an
external signal may *select and personalise*, but only the cited corpus is a source of
fact. If the identifier is offline/unavailable, returns nothing, scores below
``min_confidence``, or names a species the corpus does not cover, the path degrades to a
graceful "type the plant's name" fallback rather than guessing.

The offline default identifier performs no network call and no on-device inference; it
always falls back. The ``plantnet`` provider (``providers/plantnet.py``) calls the
allowlisted Pl@ntNet API with a key read from the environment. The response parser and
the species-resolution logic live here so they are unit-tested offline; the thin HTTP
shell is the only excluded-from-coverage piece.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from . import locales
from .answer import Assistant
from .config import Config
from .models import Answer
from .text import strip_accents, token_set, tokenize


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PlantCandidate(_Frozen):
    """One visual-identification candidate from the identifier."""

    scientific_name: str
    common_names: tuple[str, ...] = ()
    score: float  # the identifier's confidence in [0, 1]


class Identification(_Frozen):
    """The raw result of identifying a photo: scored candidates, newest first by score."""

    provider: str
    candidates: tuple[PlantCandidate, ...] = ()

    @property
    def best(self) -> PlantCandidate | None:
        return self.candidates[0] if self.candidates else None


class ResolvedSpecies(_Frozen):
    """A candidate resolved to a corpus species slug we can ground an answer in."""

    slug: str
    display_name: str
    candidate: PlantCandidate


class IdentifiedAnswer(_Frozen):
    """What the photo path returns: the (labelled) identification plus a grounded answer.

    When ``identified`` is false, ``answer`` is ``None`` and ``message`` carries the
    localized "type the plant's name" fallback. When true, ``answer`` is an ordinary
    guard-checked :class:`Answer` and ``label`` is the visual-match disclosure.
    """

    identified: bool
    identification: Identification | None = None
    species_slug: str | None = None
    display_name: str | None = None
    label: str | None = None
    answer: Answer | None = None
    message: str | None = None


@runtime_checkable
class PlantIdentifier(Protocol):
    """Maps image bytes to a scored :class:`Identification` (a selector, not a fact)."""

    def identify(self, image: bytes) -> Identification: ...


class OfflineIdentifier:
    """The offline default: no network, no model — always returns zero candidates.

    This keeps "offline by default" honest (a real vision model is a network/seam
    concern) while still exercising the whole photo path, which degrades to the
    type-the-name fallback. Swap in ``provider: plantnet`` for live identification.
    """

    provider = "offline"

    def identify(self, image: bytes) -> Identification:
        return Identification(provider=self.provider)


def parse_plantnet(
    payload: dict[str, Any], *, top_k: int, provider: str = "plantnet"
) -> Identification:
    """Parse a Pl@ntNet ``/v2/identify`` JSON payload into an :class:`Identification`.

    Defensive by design: any missing/oddly-typed field is skipped rather than raised, so
    a malformed response yields an empty (fallback-triggering) identification, never a
    crash or a fabricated species.
    """
    candidates: list[PlantCandidate] = []
    for result in payload.get("results", [])[:top_k]:
        if not isinstance(result, dict):
            continue
        species = result.get("species")
        if not isinstance(species, dict):
            continue
        name = species.get("scientificNameWithoutAuthor") or species.get("scientificName")
        if not isinstance(name, str) or not name.strip():
            continue
        commons = species.get("commonNames", [])
        common_names = tuple(c for c in commons if isinstance(c, str) and c.strip())
        try:
            score = float(result.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        candidates.append(
            PlantCandidate(scientific_name=name.strip(), common_names=common_names, score=score)
        )
    candidates.sort(key=lambda c: -c.score)
    return Identification(provider=provider, candidates=tuple(candidates))


# R8/E8 (docs/RESEARCH-ROADMAP.md): "show your work" instead of a bare fallback message
# when nothing resolves confidently enough to ground an answer. Three is a display
# choice, not a config knob — this never feeds retrieval or scoring, only a caller's
# rendering of the *existing* Identification the resolver already declined to use.
DEFAULT_CANDIDATE_DISPLAY_LIMIT = 3


def format_candidates(
    identification: Identification, *, limit: int = DEFAULT_CANDIDATE_DISPLAY_LIMIT
) -> list[str]:
    """Render up to ``limit`` scored candidates as ``"Name (0.42)"`` strings, best first.

    Pure formatting over data the identifier already returned — never a new source of
    fact, and never presented as one: callers pair this with a "not a cited fact, not
    confident enough to use" framing (see :func:`photo_candidates_intro_for`), the same
    disclosure the *resolved* path already carries via ``PromptsConfig.photo_identified``.
    """
    ranked = sorted(identification.candidates, key=lambda c: -c.score)
    return [f"{c.scientific_name} ({c.score:.2f})" for c in ranked[:limit]]


# Loaded directly from the locale bundle rather than routed through Config/PromptsConfig
# (src/sprout/config.py): this string is never eval-visible input — it labels a rejected
# guess in the identify CLI/API output, not anything that reaches Assistant.answer or a
# retrieval/guard/confidence path — so it deliberately stays off config.py's tunable
# surface (docs/ROADMAP.md Phase 3, src/sprout/eval/tuning_scope.py).
_CANDIDATES_INTRO_BY_LANG: dict[str, str] = locales.by_lang(
    "prompts", "photo_candidates_intro", locales.available_languages()
)


def photo_candidates_intro_for(language: str) -> str:
    """Localized lead-in for a rejected-candidates list ("closest visual matches...")."""
    return _CANDIDATES_INTRO_BY_LANG.get(language, _CANDIDATES_INTRO_BY_LANG["en"])


def _fold(text: str) -> str:
    return strip_accents(text).lower().strip()


def _display_name(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-"))


# Slug tokens too generic to identify a species on their own (kept in sync with the
# retriever's species filter, deliberately small and explicit).
_GENERIC = frozenset(
    {"plant", "plants", "tree", "fig", "palm", "fern", "ivy", "lily", "vine", "leaf"}
)


def _candidate_matches_slug(candidate: PlantCandidate, slug: str, config: Config) -> bool:
    """True if any of the candidate's names resolves to ``slug``.

    Resolution order: exact folded scientific binomial in the scientific-alias map; then
    the distinctive slug token appearing in a common name; then the existing common/Spanish
    species-alias glossary. All comparisons are accent-folded, matching the rest of the
    pipeline.
    """
    sci = _fold(candidate.scientific_name)
    if config.identification.scientific_aliases.get(sci) == slug:
        return True

    distinctive = {t for t in slug.split("-") if t and t not in _GENERIC}
    name_tokens: set[str] = set()
    for name in candidate.common_names:
        name_tokens |= {strip_accents(t) for t in tokenize(name)}
    if distinctive & name_tokens:
        return True

    for alias, alias_slug in config.retrieval.species_aliases.items():
        if alias_slug != slug:
            continue
        alias_tokens = token_set(alias)
        if alias_tokens and alias_tokens <= token_set(" ".join(candidate.common_names)):
            return True
    return False


def resolve_species(
    identification: Identification, available_slugs: set[str], config: Config
) -> ResolvedSpecies | None:
    """Resolve the best confident candidate to a corpus species slug, or ``None``.

    Candidates are considered in score order; the first one that clears
    ``min_confidence`` *and* maps to a slug present in the corpus wins. A candidate below
    threshold, or one naming a species the corpus does not cover, does not resolve — the
    caller then falls back rather than answering about a plant it cannot ground.
    """
    min_conf = config.identification.min_confidence
    for candidate in sorted(identification.candidates, key=lambda c: -c.score):
        if candidate.score < min_conf:
            continue
        for slug in sorted(available_slugs):
            if _candidate_matches_slug(candidate, slug, config):
                return ResolvedSpecies(
                    slug=slug, display_name=_display_name(slug), candidate=candidate
                )
    return None


def build_identifier(config: Config) -> PlantIdentifier:
    """Config string -> concrete identifier, lazily importing the network provider."""
    provider = config.identification.provider
    if provider == "offline":
        return OfflineIdentifier()
    if provider == "plantnet":  # pragma: no cover - network seam, exercised via injection
        from .provider_lifecycle import CachedHttpClient
        from .providers.plantnet import PlantNetIdentifier

        return PlantNetIdentifier(
            endpoint=config.identification.endpoint,
            top_k=config.identification.top_k,
            timeout_s=config.identification.timeout_s,
            client=CachedHttpClient(config.identification.timeout_s),
        )
    raise ValueError(f"unknown identification provider: {provider}")  # pragma: no cover


class PhotoCareService:
    """Identify a plant photo, then route the species into the grounded care-RAG."""

    def __init__(self, assistant: Assistant, identifier: PlantIdentifier, config: Config) -> None:
        self._assistant = assistant
        self._identifier = identifier
        self._config = config
        self._slugs = assistant.species_slugs()

    def identify_and_answer(
        self, image: bytes, *, question: str | None = None, language: str | None = None
    ) -> IdentifiedAnswer:
        lang = self._assistant.resolve_language(question or "", language)
        max_bytes = self._config.identification.max_image_bytes
        if not image or len(image) > max_bytes:
            return self._fallback(lang, identification=None)

        identification = self._identifier.identify(image)
        resolved = resolve_species(identification, self._slugs, self._config)
        if resolved is None:
            return self._fallback(lang, identification=identification)

        query = self._build_query(resolved.display_name.lower(), question, lang)
        answer = self._assistant.answer(query, language or lang)
        return IdentifiedAnswer(
            identified=True,
            identification=identification,
            species_slug=resolved.slug,
            display_name=resolved.display_name,
            label=self._config.prompts.photo_identified_for(lang, resolved.display_name),
            answer=answer,
        )

    def _build_query(self, name: str, question: str | None, lang: str) -> str:
        if question and question.strip():
            return f"{name}: {question.strip()}"
        return self._config.prompts.photo_care_question_for(lang, name)

    def _fallback(self, lang: str, *, identification: Identification | None) -> IdentifiedAnswer:
        return IdentifiedAnswer(
            identified=False,
            identification=identification,
            message=self._config.prompts.photo_fallback_for(lang),
        )
