"""Photo plant-ID -> grounded care lookup: resolution, fallback, and grounding preserved.

These tests prove the load-bearing property: a photo identification is only ever a
*selector*. The species it yields is routed back through the unchanged grounded pipeline,
so the rendered answer still carries citations and the never-certify-safe routing; the
visual match is never presented as a cited fact. Everything here is offline/deterministic.
"""

from __future__ import annotations

from sprout.answer import Assistant
from sprout.config import Config
from sprout.identify import (
    Identification,
    OfflineIdentifier,
    PhotoCareService,
    PlantCandidate,
    build_identifier,
    parse_plantnet,
    resolve_species,
)


class FakeIdentifier:
    """A deterministic stand-in for a vision API: returns a preset identification."""

    def __init__(self, identification: Identification) -> None:
        self._identification = identification

    def identify(self, image: bytes) -> Identification:
        return self._identification


def _ident(*candidates: PlantCandidate, provider: str = "fake") -> Identification:
    return Identification(provider=provider, candidates=candidates)


def test_offline_identifier_always_falls_back() -> None:
    ident = OfflineIdentifier().identify(b"jpeg-bytes")
    assert ident.provider == "offline"
    assert ident.candidates == ()
    assert ident.best is None


def test_resolve_species_by_scientific_name(config: Config) -> None:
    ident = _ident(PlantCandidate(scientific_name="Epipremnum aureum", score=0.9))
    resolved = resolve_species(ident, {"monstera", "pothos", "spider-plant"}, config)
    assert resolved is not None
    assert resolved.slug == "pothos"
    assert resolved.display_name == "Pothos"


def test_resolve_species_by_common_name(config: Config) -> None:
    ident = _ident(
        PlantCandidate(
            scientific_name="Unknownus plantus",
            common_names=("Golden pothos", "Devil's ivy"),
            score=0.8,
        )
    )
    resolved = resolve_species(ident, {"monstera", "pothos"}, config)
    assert resolved is not None and resolved.slug == "pothos"


def test_resolve_species_below_confidence_does_not_resolve(config: Config) -> None:
    ident = _ident(PlantCandidate(scientific_name="Epipremnum aureum", score=0.1))
    assert resolve_species(ident, {"pothos"}, config) is None


def test_resolve_species_unknown_species_does_not_resolve(config: Config) -> None:
    ident = _ident(PlantCandidate(scientific_name="Ficus benjamina", score=0.95))
    assert resolve_species(ident, {"monstera", "pothos"}, config) is None


def test_resolve_species_via_common_name_alias() -> None:
    # An unknown scientific name whose common name matches the configured alias glossary.
    cfg = Config.model_validate(
        {"retrieval": {"species_aliases": {"unrelated name": "monstera", "golden vine": "pothos"}}}
    )
    ident = _ident(
        PlantCandidate(
            scientific_name="Mysterius plantus", common_names=("Golden vine",), score=0.9
        )
    )
    resolved = resolve_species(ident, {"pothos"}, cfg)
    assert resolved is not None and resolved.slug == "pothos"


def test_resolve_species_prefers_first_confident_known_candidate(config: Config) -> None:
    ident = _ident(
        PlantCandidate(scientific_name="Ficus benjamina", score=0.9),  # unknown
        PlantCandidate(scientific_name="Monstera deliciosa", score=0.7),  # known
    )
    resolved = resolve_species(ident, {"monstera", "pothos"}, config)
    assert resolved is not None and resolved.slug == "monstera"


def test_parse_plantnet_sorts_and_skips_malformed() -> None:
    payload = {
        "results": [
            {"score": 0.4, "species": {"scientificNameWithoutAuthor": "Monstera deliciosa"}},
            {
                "score": 0.9,
                "species": {
                    "scientificNameWithoutAuthor": "Epipremnum aureum",
                    "commonNames": ["Golden pothos"],
                },
            },
            {"score": "bad", "species": {"scientificNameWithoutAuthor": "Aloe vera"}},
            "not-a-dict",
            {"score": 0.3, "species": "not-a-dict"},
            {"score": 0.2, "species": {"scientificNameWithoutAuthor": ""}},
        ]
    }
    ident = parse_plantnet(payload, top_k=10)
    names = [c.scientific_name for c in ident.candidates]
    # Highest score first; malformed entries dropped; the "bad" score coerces to 0.0.
    assert names[0] == "Epipremnum aureum"
    assert "Monstera deliciosa" in names
    assert ident.best is not None and ident.best.common_names == ("Golden pothos",)


def test_parse_plantnet_empty_on_missing_results() -> None:
    assert parse_plantnet({}, top_k=5).candidates == ()


def test_photo_care_grounded_and_routes_safety(assistant: Assistant, config: Config) -> None:
    ident = _ident(
        PlantCandidate(
            scientific_name="Epipremnum aureum", common_names=("Golden pothos",), score=0.92
        )
    )
    service = PhotoCareService(assistant, FakeIdentifier(ident), config)
    result = service.identify_and_answer(b"img", question="is this toxic to my cat?")

    assert result.identified is True
    assert result.species_slug == "pothos"
    assert result.label is not None and "not a cited fact" in result.label
    answer = result.answer
    assert answer is not None and not answer.refused
    # Grounding preserved: every rendered sentence is cited, and toxicity routes to a vet.
    assert answer.citations
    assert answer.citation_coverage == 1.0
    assert answer.is_safety_query
    assert answer.safety_notice is not None


def test_photo_care_default_question_when_none(assistant: Assistant, config: Config) -> None:
    ident = _ident(PlantCandidate(scientific_name="Monstera deliciosa", score=0.8))
    service = PhotoCareService(assistant, FakeIdentifier(ident), config)
    result = service.identify_and_answer(b"img")
    assert result.identified is True and result.species_slug == "monstera"
    assert result.answer is not None and result.answer.citations


def test_photo_care_falls_back_when_unidentified(assistant: Assistant, config: Config) -> None:
    service = PhotoCareService(assistant, OfflineIdentifier(), config)
    result = service.identify_and_answer(b"img", question="how often do I water?")
    assert result.identified is False
    assert result.answer is None
    assert result.message and "type the plant" in result.message.lower()


def test_photo_care_rejects_empty_and_oversized(assistant: Assistant) -> None:
    cfg = Config.model_validate({"identification": {"max_image_bytes": 4}})
    service = PhotoCareService(assistant, OfflineIdentifier(), cfg)
    assert service.identify_and_answer(b"").identified is False
    assert service.identify_and_answer(b"toolong").identified is False


def test_photo_care_spanish_fallback(assistant: Assistant, config: Config) -> None:
    service = PhotoCareService(assistant, OfflineIdentifier(), config)
    result = service.identify_and_answer(b"img", language="es")
    assert result.identified is False
    assert result.message and "Escribe el nombre" in result.message


def test_build_identifier_offline(config: Config) -> None:
    assert isinstance(build_identifier(config), OfflineIdentifier)


# --- the network provider, exercised through an injected fake transport ----------


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse(self._payload)


def test_plantnet_identifier_parses_via_injected_client() -> None:
    from sprout.providers.plantnet import PlantNetIdentifier

    payload: dict[str, object] = {
        "results": [
            {
                "score": 0.77,
                "species": {
                    "scientificNameWithoutAuthor": "Monstera deliciosa",
                    "commonNames": ["Swiss cheese plant"],
                },
            }
        ]
    }
    client = _FakeClient(payload)
    identifier = PlantNetIdentifier(client=client, api_key="test-key", top_k=3)
    ident = identifier.identify(b"jpeg")
    assert ident.provider == "plantnet"
    assert ident.best is not None
    assert ident.best.scientific_name == "Monstera deliciosa"
    assert client.calls  # the endpoint was actually called


def test_plantnet_identifier_fails_closed_without_key() -> None:
    from sprout.providers.plantnet import PlantNetIdentifier

    identifier = PlantNetIdentifier(api_key="")
    assert identifier.identify(b"jpeg").candidates == ()


def test_plantnet_identifier_fails_closed_on_error() -> None:
    from sprout.providers.plantnet import PlantNetIdentifier

    class _Boom:
        def post(self, *a: object, **k: object) -> object:
            raise RuntimeError("network down")

    identifier = PlantNetIdentifier(client=_Boom(), api_key="k")
    assert identifier.identify(b"jpeg").candidates == ()
