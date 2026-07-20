"""Config-over-code: one YAML controls models, thresholds, languages, and corpus.

``config/sprout.yaml`` is the only file an adopter edits to point Sprout at a
different corpus, switch the offline generator for Claude-on-Bedrock, or add a
language. Every model forbids unknown keys (``extra='forbid'``) so a misspelled
threshold fails at load time rather than silently taking a default. Secrets
(API keys, regions) are read from environment variables, never stored here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import locales

# The languages the built-in ``*_by_lang`` defaults are drawn from. Independent of
# whatever a loaded config sets ``languages.supported`` to (same as the previous
# hard-coded en/es dict literals this module used to carry) — a custom config that
# widens ``languages.supported`` is expected to also supply its own prompts/guards, and
# the completeness gate on :class:`Config` enforces that.
_DEFAULT_LANGUAGES = ("en", "es")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FreshnessConfig(_Model):
    """Thresholds for the offline citation-freshness check."""

    max_age_days: int = Field(default=365, ge=1, le=3650)
    toxicity_max_age_days: int = Field(default=180, ge=1, le=3650)


class CorpusConfig(_Model):
    path: str = "corpus/processed"
    glob: str = "**/*.md"
    manifest: str = "corpus/manifest.yaml"
    default_language: str = "en"
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)


class ChunkConfig(_Model):
    max_words: int = Field(default=120, ge=20, le=400)
    overlap_words: int = Field(default=24, ge=0, le=100)


class RetrievalConfig(_Model):
    top_k: int = Field(default=6, ge=1, le=50)
    min_score: float = Field(default=0.12, ge=0.0, le=1.0)
    embedding_dim: int = Field(default=512, ge=64, le=4096)
    embedding_provider: Literal["deterministic", "bedrock"] = "deterministic"
    hybrid: bool = True
    bm25_k1: float = Field(default=1.5, ge=0.0)
    bm25_b: float = Field(default=0.75, ge=0.0, le=1.0)
    rrf_k: int = Field(default=60, ge=1)
    dedup_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    topic_filter: bool = True
    # Maps a common/alternate name (e.g. a Spanish name) to a corpus species slug, so the
    # species filter scopes "¿es tóxico el potos?" to the pothos passages. Matched on
    # accent-folded, stemmed tokens.
    species_aliases: dict[str, str] = Field(default_factory=dict)


class GenerationConfig(_Model):
    provider: Literal["deterministic", "bedrock", "anthropic"] = "deterministic"
    max_sentences: int = Field(default=3, ge=1, le=10)
    relevance_floor: float = Field(default=0.22, ge=0.0, le=1.0)
    support_overlap: float = Field(default=0.66, ge=0.0, le=1.0)
    model: str | None = None
    region: str = "us-west-2"
    max_retries: int = Field(default=2, ge=0, le=10)
    max_cost_usd: float = Field(default=0.05, ge=0.0)
    redact_query_pii: bool = False


class ConfidenceFit(_Model):
    """A fitted, provenance-stamped logistic, written by ``sprout fit-confidence``
    (ADR-0016). Answers "fitted on what, when, against which retrieval config" so a
    committed fit is auditable rather than a bare set of numbers.

    Fitted on a **train split** (``eval/train/``) of generated calibration questions,
    never on ``eval/suites/`` -- the anti-tuning-to-test discipline the calibration eval
    depends on to be a meaningful, un-gamed check.
    """

    midpoint: float = Field(ge=0.0, le=1.0)
    steepness: float = Field(ge=0.1, le=100.0)
    margin_bonus: float = Field(ge=0.0, le=1.0)
    train_dataset_hash: str
    train_path: str
    retrieval_config_hash: str
    n_items: int = Field(ge=1)
    fitted_at: str  # ISO-8601 date


class ConfidenceConfig(_Model):
    """Two thresholds over a computed [0,1] confidence drive abstention/handoff.

    Values per ADR-0012 (supersedes ADR-0005; reconciled 2026-07-05 — see that ADR for
    the ECE evidence that these, not ADR-0005's 0.45/0.62, are the calibrated values).
    """

    abstain_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    low_confidence_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    reliability_bins: int = Field(default=10, ge=2, le=50)
    # Absent until `sprout fit-confidence` has been run at least once; see ConfidenceFit
    # and confidence.py's module docstring for the ADR-0012 fallback used until then.
    fit: ConfidenceFit | None = None


class GuardsConfig(_Model):
    """Output/scope guards. The never-certify-'safe' deny-list is per-language.

    Defaults are read from the per-language bundles under ``src/sprout/locales/``
    (FIX-09) rather than carried as inline dict literals here — see that package's
    docstring for the completeness gate that keeps every supported language's bundle
    in the same shape as the reference language's.
    """

    forbidden_safe_phrases: dict[str, list[str]] = Field(
        default_factory=lambda: locales.by_lang(
            "guards", "forbidden_safe_phrases", _DEFAULT_LANGUAGES
        )
    )
    toxicity_keywords: dict[str, list[str]] = Field(
        default_factory=lambda: locales.by_lang("guards", "toxicity_keywords", _DEFAULT_LANGUAGES)
    )
    route_terms: dict[str, list[str]] = Field(
        default_factory=lambda: locales.by_lang("guards", "route_terms", _DEFAULT_LANGUAGES)
    )
    # Exposure-type routing (FIX-13): audience terms that name a human (vs. animal)
    # exposure, so the classifier can tell "my toddler ate a leaf" from "my cat ate a
    # leaf". Unlike ``toxicity_keywords`` these match whole tokens only (see
    # ``guards._matches_any``) -- substring matching misroutes the audience ("cat" in
    # "identification", "son" in "poison") -- so every inflected form is listed
    # explicitly. ``tokenize`` accent-folds (strip_accents); accented ES forms are
    # listed alongside their folded equivalents for auditability, the folded form is
    # the one that matches.
    child_exposure_keywords: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "en": [
                "child",
                "children",
                "baby",
                "babies",
                "toddler",
                "toddlers",
                "kid",
                "kids",
                "kiddo",
                "infant",
                "infants",
                "son",
                "sons",
                "daughter",
                "daughters",
                "grandchild",
                "grandchildren",
                "grandson",
                "grandsons",
                "granddaughter",
                "granddaughters",
            ],
            "es": [
                "niño",
                "nino",
                "niños",
                "ninos",
                "niña",
                "nina",
                "niñas",
                "ninas",
                "bebé",
                "bebe",
                "bebés",
                "bebes",
                "infante",
                "infantes",
                "hijo",
                "hijos",
                "hija",
                "hijas",
                "nieto",
                "nietos",
                "nieta",
                "nietas",
            ],
        }
    )
    animal_exposure_keywords: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "en": [
                "cat",
                "cats",
                "dog",
                "dogs",
                "pet",
                "pets",
                "kitten",
                "kittens",
                "kitty",
                "puppy",
                "puppies",
            ],
            "es": [
                "gato",
                "gatos",
                "gata",
                "gatas",
                "gatito",
                "gatitos",
                "perro",
                "perros",
                "perra",
                "perras",
                "perrito",
                "perritos",
                "cachorro",
                "cachorros",
                "mascota",
                "mascotas",
            ],
        }
    )


class IdentificationConfig(_Model):
    """Photo plant-ID seam. The identifier returns a *species name* (a selector), never a
    horticultural fact: the resolved species is routed back through the grounded care-RAG,
    so every rendered claim is still cited. ``offline`` (no network, no model) always
    falls back to "type the plant's name"; ``plantnet`` calls the allowlisted Pl@ntNet API
    with its key read from ``PLANTNET_API_KEY`` (env only, never config)."""

    provider: Literal["offline", "plantnet"] = "offline"
    min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    top_k: int = Field(default=5, ge=1, le=20)
    # The single allowlisted vision endpoint. No other network egress is introduced.
    endpoint: str = "https://my-api.plantnet.org/v2/identify/all"
    timeout_s: float = Field(default=30.0, ge=1.0, le=120.0)
    max_image_bytes: int = Field(default=8_000_000, ge=1, le=64_000_000)
    # Folded scientific binomial -> corpus species slug. Maps a vision result to the
    # passages that already exist in the cited corpus; unknown species fall back.
    scientific_aliases: dict[str, str] = Field(
        default_factory=lambda: {
            "aloe vera": "aloe",
            "aloe barbadensis": "aloe",
            "nephrolepis exaltata": "boston-fern",
            "goeppertia": "calathea",
            "calathea": "calathea",
            "dracaena fragrans": "dracaena",
            "dracaena": "dracaena",
            "hedera helix": "english-ivy",
            "ficus lyrata": "fiddle-leaf-fig",
            "crassula ovata": "jade-plant",
            "monstera deliciosa": "monstera",
            "phalaenopsis": "orchid",
            "spathiphyllum": "peace-lily",
            "spathiphyllum wallisii": "peace-lily",
            "philodendron": "philodendron",
            "philodendron hederaceum": "philodendron",
            "epipremnum aureum": "pothos",
            "ficus elastica": "rubber-plant",
            "dracaena trifasciata": "snake-plant",
            "sansevieria trifasciata": "snake-plant",
            "chlorophytum comosum": "spider-plant",
            "zamioculcas zamiifolia": "zz-plant",
        }
    )


class RemindersConfig(_Model):
    """Local-first watering/fertilizing reminders. Stored in one JSON file on the user's
    own machine (no database, no network) and opt-in: nothing is written until a reminder
    is created. Reminder content is never logged (PII-free observability is preserved)."""

    path: str = "var/reminders.json"
    max_reminders: int = Field(default=200, ge=1, le=10000)
    default_intervals: dict[str, int] = Field(
        default_factory=lambda: {
            "water": 7,
            "fertilize": 30,
            "repot": 365,
            "mist": 3,
            "rotate": 14,
        }
    )


class LanguageConfig(_Model):
    supported: list[str] = Field(default_factory=lambda: ["en", "es"])

    @property
    def reference(self) -> str:
        """The reference language all others must preserve facts of (first in list)."""
        return self.supported[0]


class PromptConfig(_Model):
    system: str = (
        "You are a houseplant-care assistant. Answer ONLY using the numbered sources "
        "provided. Quote them faithfully and never certify any plant 'safe'."
    )
    # Every *_by_lang default below is read from src/sprout/locales/<lang>/bundle.yaml
    # (FIX-09) rather than carried as an inline dict literal — see that package's
    # docstring for the load-time completeness gate.
    refusal_by_lang: dict[str, str] = Field(
        default_factory=lambda: locales.by_lang("prompts", "refusal", _DEFAULT_LANGUAGES)
    )
    disclosure_by_lang: dict[str, str] = Field(
        default_factory=lambda: locales.by_lang("prompts", "disclosure", _DEFAULT_LANGUAGES)
    )
    # Urgency-forward routing (research item E2): lead with the time-critical action,
    # never with reassurance, and still never certify a plant safe.
    safety_route_by_lang: dict[str, str] = Field(
        default_factory=lambda: locales.by_lang("prompts", "safety_route", _DEFAULT_LANGUAGES)
    )
    # "Not listed as toxic" is not a clean bill of health (research item R7 / evidence
    # EV3): any plant material can cause GI upset, and individual animals vary. This is a
    # framing caveat about the limits of a *source's silence*, not a claim about any
    # specific plant — it is attributed to "a source", so it reads as reporting, not a
    # certification, and the never-certify-safe guard leaves it intact.
    nontoxic_caveat_by_lang: dict[str, str] = Field(
        default_factory=lambda: locales.by_lang("prompts", "nontoxic_caveat", _DEFAULT_LANGUAGES)
    )
    # Standardized escalation card (research item E9): named public poison-control
    # authorities plus the three facts the clinician needs. Numbers and pages are the
    # well-established public contacts (ASPCA APCC, Pet Poison Helpline); the official
    # pages are linked so they remain the source of truth if a number ever changes.
    escalation_card_by_lang: dict[str, str] = Field(
        default_factory=lambda: locales.by_lang("prompts", "escalation_card", _DEFAULT_LANGUAGES)
    )

    # Human-poison-control card variant (FIX-13). The shipped E9 card above names only
    # the two animal lines (ASPCA APCC, Pet Poison Helpline); ``GuardsConfig`` already
    # detects child/human ingestion terms (child/children/baby/toddler, EN;
    # niño/niña/bebé, ES) via ``child_exposure_keywords``, but until this variant existed
    # a child-ingestion question got only the animal card back -- confusing at best, a
    # delay at worst. Shown *alongside*, never instead of, the existing urgent-call
    # framing and escalation card; ambiguous (child + animal both named) queries get both
    # cards.
    #
    # HARD GATE, unchanged from the ideation item (docs/ideation/02-large-scale-fixes.md
    # FIX-13): the numbers, the phrasing, and the decision to show them at all belong to
    # a poison-control clinician / medical toxicologist, not to this codebase. This card
    # is wired up end to end (detection -> selection -> render) but
    # ``human_card_reviewed`` defaults to False, so it never reaches a user until that
    # flag is flipped to True by hand after a dated sign-off is committed under
    # docs/audits/ (see docs/audits/human-poison-control-card-review.md, currently a
    # pending stub, not a real review). Non-US numbers are out of scope until a locale
    # story exists for this card, same as the animal card.
    human_card_reviewed: bool = False
    human_escalation_card_by_lang: dict[str, str] = Field(
        default_factory=lambda: {
            "en": (
                "If a child may have eaten part of this plant: Poison Control, "
                "1-800-222-1222 (https://www.poison.org/), free and available 24/7, or "
                "use webPOISONCONTROL (https://triage.webpoisoncontrol.org/) for online "
                "guidance. What to tell them: the plant (species if known), how much was "
                "eaten, and when."
            ),
            "es": (
                "Si un niño pudo haber comido parte de esta planta: Control de "
                "Envenenamientos, 1-800-222-1222 (https://www.poison.org/), gratuito y "
                "disponible las 24 horas, o usa webPOISONCONTROL "
                "(https://triage.webpoisoncontrol.org/) para orientación en línea. Qué "
                "informar: la planta (especie si la conoces), cuánto comió y cuándo."
            ),
        }
    )

    photo_fallback_by_lang: dict[str, str] = Field(
        default_factory=lambda: locales.by_lang("prompts", "photo_fallback", _DEFAULT_LANGUAGES)
    )
    photo_care_question_by_lang: dict[str, str] = Field(
        default_factory=lambda: locales.by_lang(
            "prompts", "photo_care_question", _DEFAULT_LANGUAGES
        )
    )
    photo_identified_by_lang: dict[str, str] = Field(
        default_factory=lambda: locales.by_lang("prompts", "photo_identified", _DEFAULT_LANGUAGES)
    )

    def refusal_for(self, language: str) -> str:
        return self.refusal_by_lang.get(language, self.refusal_by_lang["en"])

    def photo_fallback_for(self, language: str) -> str:
        return self.photo_fallback_by_lang.get(language, self.photo_fallback_by_lang["en"])

    def photo_care_question_for(self, language: str, name: str) -> str:
        template = self.photo_care_question_by_lang.get(
            language, self.photo_care_question_by_lang["en"]
        )
        return template.format(name=name)

    def photo_identified_for(self, language: str, name: str) -> str:
        template = self.photo_identified_by_lang.get(language, self.photo_identified_by_lang["en"])
        return template.format(name=name)

    def disclosure_for(self, language: str) -> str:
        return self.disclosure_by_lang.get(language, self.disclosure_by_lang["en"])

    def safety_route_for(self, language: str) -> str:
        return self.safety_route_by_lang.get(language, self.safety_route_by_lang["en"])

    def nontoxic_caveat_for(self, language: str) -> str:
        return self.nontoxic_caveat_by_lang.get(language, self.nontoxic_caveat_by_lang["en"])

    def escalation_card_for(self, language: str) -> str:
        return self.escalation_card_by_lang.get(language, self.escalation_card_by_lang["en"])

    def human_escalation_card_for(self, language: str) -> str:
        return self.human_escalation_card_by_lang.get(
            language, self.human_escalation_card_by_lang["en"]
        )

    def safety_directive_for(self, language: str, exposure_type: str | None = None) -> str:
        """The full safety message shown on every toxicity answer/refusal.

        Three research-backed parts, in urgency order: the time-critical routing line
        (E2), the "not listed as toxic is not safe" caveat (R7), and the standardized
        vet/poison-control escalation card (E9). It never certifies a plant safe, and
        because the caveat is source-attributed the never-certify-safe guard keeps it
        intact.

        ``exposure_type`` (FIX-13, from ``guards.detect_exposure_type``) is one of
        "child", "animal", "both", "unspecified", or None. When it names a child/human
        audience ("child" or "both") *and* ``human_card_reviewed`` is True, the
        human-poison-control card is appended alongside -- never instead of -- the
        animal card above. Until a clinician sign-off flips that flag, this branch is
        inert by construction and behavior is unchanged from before FIX-13.
        """
        parts = [
            self.safety_route_for(language),
            self.nontoxic_caveat_for(language),
            self.escalation_card_for(language),
        ]
        if self.human_card_reviewed and exposure_type in {"child", "both"}:
            parts.append(self.human_escalation_card_for(language))
        return " ".join(parts)


class ServerConfig(_Model):
    """App-level hardening for ``serve`` (ASVS L2 delta — ``docs/audits/asvs-l2-delta.md``).

    These guards hold even without a reverse proxy in front of the app: the offline CLI path
    never loads this middleware stack (``sprout.cli`` never imports ``sprout.server``), so
    none of it touches the zero-dependency offline mode.
    """

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    max_question_chars: int = Field(default=500, ge=1, le=4000)
    session_memory: int = Field(default=4, ge=0, le=50)
    # Body-size cap independent of any proxy config. Sized above the largest legitimate
    # payload — an 8 MB photo, base64-inflated ~1.33x, plus JSON/field overhead — with margin.
    max_body_bytes: int = Field(default=12_000_000, ge=1_000, le=100_000_000)
    # Per-client-IP token bucket, applied to every request.
    rate_limit_requests: int = Field(default=60, ge=1, le=100_000)
    rate_limit_window_s: float = Field(default=60.0, ge=1.0, le=3600.0)
    # A stricter bucket layered on top for the heavy, unauthenticated photo endpoint.
    identify_rate_limit_requests: int = Field(default=10, ge=1, le=100_000)
    identify_rate_limit_window_s: float = Field(default=60.0, ge=1.0, le=3600.0)
    # Bounded worker concurrency for /api/identify so a burst of large photos can't exhaust
    # the threadpool the rest of the API shares.
    identify_max_concurrency: int = Field(default=4, ge=1, le=256)


class ObservabilityConfig(_Model):
    log_format: Literal["text", "json"] = "text"
    tier: Literal["A", "B", "C"] = "C"
    service_name: str = "sprout"


class StoreConfig(_Model):
    path: str = "var/index.json"


class Config(_Model):
    corpus: CorpusConfig = Field(default_factory=CorpusConfig)
    chunk: ChunkConfig = Field(default_factory=ChunkConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    guards: GuardsConfig = Field(default_factory=GuardsConfig)
    identification: IdentificationConfig = Field(default_factory=IdentificationConfig)
    reminders: RemindersConfig = Field(default_factory=RemindersConfig)
    languages: LanguageConfig = Field(default_factory=LanguageConfig)
    prompts: PromptConfig = Field(default_factory=PromptConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)

    @model_validator(mode="after")
    def _check_locale_bundle_completeness(self) -> Config:
        """FIX-09's load-time completeness gate: every language in
        ``languages.supported`` must have a locale bundle carrying every key the
        reference language's bundle (``locales.REFERENCE_LANGUAGE``, conventionally
        the first-listed language) defines. Fails config load, not render — see
        ``src/sprout/locales/__init__.py``.
        """
        locales.validate_completeness(self.languages.supported)
        return self


def load_config(path: str | Path) -> Config:
    """Load and validate a YAML config. Missing file or non-mapping root raises."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {p}")
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping, got {type(raw).__name__}")
    return Config.model_validate(raw)
