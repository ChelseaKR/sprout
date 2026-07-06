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
from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorpusConfig(_Model):
    path: str = "corpus/processed"
    glob: str = "**/*.md"
    manifest: str = "corpus/manifest.yaml"
    default_language: str = "en"


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


class ConfidenceConfig(_Model):
    """Two thresholds over a computed [0,1] confidence drive abstention/handoff.

    Values per ADR-0012 (supersedes ADR-0005; reconciled 2026-07-05 — see that ADR for
    the ECE evidence that these, not ADR-0005's 0.45/0.62, are the calibrated values).
    """

    abstain_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    low_confidence_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    reliability_bins: int = Field(default=10, ge=2, le=50)


class GuardsConfig(_Model):
    """Output/scope guards. The never-certify-'safe' deny-list is per-language."""

    forbidden_safe_phrases: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "en": [
                "is safe",
                "are safe",
                "safe for",
                "safe to",
                "pet safe",
                "pet friendly",
                "considered safe",
                "completely safe",
                "perfectly safe",
                "non-toxic",
                "nontoxic",
                "perfectly fine",
                "totally fine",
                "harmless",
                "no danger",
                "won't hurt",
            ],
            "es": [
                "es seguro",
                "es segura",
                "son seguras",
                "seguro para",
                "segura para",
                "apto para",
                "apta para",
                "no es tóxica",
                "no es toxica",
                "no es tóxico",
                "no es toxico",
                "no tóxica",
                "inofensiva",
                "inofensivo",
                "sin peligro",
            ],
        }
    )
    toxicity_keywords: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "en": [
                "toxic",
                "poison",
                "poisonous",
                "safe",
                "ingest",
                "eat",
                "eaten",
                "swallow",
                "cat",
                "cats",
                "dog",
                "dogs",
                "pet",
                "pets",
                "kitten",
                "puppy",
                "child",
                "children",
                "baby",
                "toddler",
                "chew",
            ],
            "es": [
                "tóxica",
                "toxica",
                "tóxico",
                "toxico",
                "veneno",
                "venenosa",
                "seguro",
                "segura",
                "comer",
                "comió",
                "ingerir",
                "gato",
                "gatos",
                "perro",
                "perros",
                "mascota",
                "mascotas",
                "niño",
                "niña",
                "bebé",
            ],
        }
    )
    route_terms: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "en": ["poison control", "veterinarian", "vet"],
            "es": ["control de envenenamiento", "veterinario"],
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
    refusal_by_lang: dict[str, str] = Field(
        default_factory=lambda: {
            "en": (
                "I don't have a cited reference that covers this, so I can't answer "
                "from the corpus. For plant-specific guidance, check a reputable source "
                "such as your local extension service or the ASPCA toxic-plant list."
            ),
            "es": (
                "No tengo una referencia citada que cubra esto, así que no puedo "
                "responder desde el corpus. Para orientación específica, consulta una "
                "fuente confiable como tu servicio de extensión local o la lista de "
                "plantas tóxicas de la ASPCA."
            ),
        }
    )
    disclosure_by_lang: dict[str, str] = Field(
        default_factory=lambda: {
            "en": "Answers are drawn only from a dated, cited plant-care corpus. This is not veterinary advice.",  # noqa: E501
            "es": "Las respuestas provienen solo de un corpus de cuidado de plantas fechado y citado. Esto no es asesoramiento veterinario.",  # noqa: E501
        }
    )
    # Urgency-forward routing (research item E2): lead with the time-critical action,
    # never with reassurance, and still never certify a plant safe.
    safety_route_by_lang: dict[str, str] = Field(
        default_factory=lambda: {
            "en": (
                "If a pet or child may have eaten part of this plant, treat it as urgent: "
                "contact your veterinarian or a poison-control line now — don't wait for "
                "symptoms to appear. I can't certify any plant safe."
            ),
            "es": (
                "Si una mascota o un niño pudo haber comido parte de esta planta, trátalo "
                "como urgente: comunícate ahora con tu veterinario o una línea de control "
                "de envenenamiento; no esperes a que aparezcan síntomas. No puedo "
                "certificar ninguna planta como segura."
            ),
        }
    )
    # "Not listed as toxic" is not a clean bill of health (research item R7 / evidence
    # EV3): any plant material can cause GI upset, and individual animals vary. This is a
    # framing caveat about the limits of a *source's silence*, not a claim about any
    # specific plant — it is attributed to "a source", so it reads as reporting, not a
    # certification, and the never-certify-safe guard leaves it intact.
    nontoxic_caveat_by_lang: dict[str, str] = Field(
        default_factory=lambda: {
            "en": (
                "Even a plant a source does not list as toxic can still cause vomiting or "
                "mouth and stomach irritation if eaten, and reactions vary by pet and "
                "person — a source's silence is not a guarantee against harm."
            ),
            "es": (
                "Incluso una planta que una fuente no incluye como tóxica puede causar "
                "vómitos o irritación de la boca y el estómago si se ingiere, y cada "
                "mascota o niño reacciona distinto: el silencio de una fuente no garantiza "
                "que no haya daño."
            ),
        }
    )
    # Standardized escalation card (research item E9): named public poison-control
    # authorities plus the three facts the clinician needs. Numbers and pages are the
    # well-established public contacts (ASPCA APCC, Pet Poison Helpline); the official
    # pages are linked so they remain the source of truth if a number ever changes.
    escalation_card_by_lang: dict[str, str] = Field(
        default_factory=lambda: {
            "en": (
                "Who to call now: ASPCA Animal Poison Control Center, 888-426-4435 "
                "(https://www.aspca.org/pet-care/animal-poison-control), or Pet Poison "
                "Helpline, 855-764-7661 (https://www.petpoisonhelpline.com/). What to "
                "tell them: the plant (species if known), how much was eaten, and when."
            ),
            "es": (
                "A quién llamar ahora: ASPCA Animal Poison Control Center, 888-426-4435 "
                "(https://www.aspca.org/pet-care/animal-poison-control), o Pet Poison "
                "Helpline, 855-764-7661 (https://www.petpoisonhelpline.com/). Qué "
                "informar: la planta (especie si la conoces), cuánto comió y cuándo."
            ),
        }
    )

    photo_fallback_by_lang: dict[str, str] = Field(
        default_factory=lambda: {
            "en": (
                "I couldn't confidently identify a plant in that photo. Please type the "
                "plant's name and I'll answer from the cited corpus."
            ),
            "es": (
                "No pude identificar con confianza una planta en esa foto. Escribe el "
                "nombre de la planta y responderé desde el corpus citado."
            ),
        }
    )
    photo_care_question_by_lang: dict[str, str] = Field(
        default_factory=lambda: {
            "en": "How do I care for my {name}?",
            "es": "¿Cómo cuido mi {name}?",
        }
    )
    photo_identified_by_lang: dict[str, str] = Field(
        default_factory=lambda: {
            "en": (
                "Identified from your photo as {name} — a visual match, not a cited fact. "
                "The guidance below is grounded in the cited corpus."
            ),
            "es": (
                "Identificado en tu foto como {name}: una coincidencia visual, no un hecho "
                "citado. La siguiente orientación proviene del corpus citado."
            ),
        }
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

    def safety_directive_for(self, language: str) -> str:
        """The full safety message shown on every toxicity answer/refusal.

        Three research-backed parts, in urgency order: the time-critical routing line
        (E2), the "not listed as toxic is not safe" caveat (R7), and the standardized
        vet/poison-control escalation card (E9). It never certifies a plant safe, and
        because the caveat is source-attributed the never-certify-safe guard keeps it
        intact.
        """
        return " ".join(
            (
                self.safety_route_for(language),
                self.nontoxic_caveat_for(language),
                self.escalation_card_for(language),
            )
        )


class ServerConfig(_Model):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    max_question_chars: int = Field(default=500, ge=1, le=4000)
    session_memory: int = Field(default=4, ge=0, le=50)


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
