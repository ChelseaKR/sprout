"""Tests for the deterministic foundation: hashing, text, language, config, models."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from sprout import __version__
from sprout.config import Config, load_config
from sprout.determinism import (
    canonical_bytes,
    sha256_of_file,
    sha256_of_obj,
    sha256_of_text,
    short,
)
from sprout.lang import detect_language
from sprout.models import Answer, AnswerSentence, Chunk, Citation
from sprout.text import (
    contains_phrase,
    content_tokens,
    coverage,
    has_antonym_conflict,
    has_negation,
    jaccard,
    normalize,
    split_sentences,
    tokenize,
)


def test_version_matches_pyproject() -> None:
    assert __version__ == "0.1.0"


# --- determinism -----------------------------------------------------------------
def test_canonical_bytes_is_order_independent() -> None:
    assert canonical_bytes({"b": 1, "a": 2}) == canonical_bytes({"a": 2, "b": 1})


def test_hash_helpers_are_stable_and_consistent() -> None:
    obj = {"x": [1, 2, 3], "y": "café"}
    assert sha256_of_obj(obj) == sha256_of_obj(dict(reversed(list(obj.items()))))
    assert sha256_of_text("hello") == sha256_of_text("hello")
    assert sha256_of_text("hello") != sha256_of_text("world")
    assert len(short(sha256_of_text("hello"))) == 12


def test_sha256_of_file(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("contents", encoding="utf-8")
    assert sha256_of_file(f) == sha256_of_text("contents")


# --- text ------------------------------------------------------------------------
def test_tokenize_folds_accents_and_case() -> None:
    assert tokenize("Riego TAMBIÉN") == ["riego", "tambien"]


def test_tokenize_keeps_decimals_whole() -> None:
    assert "1.5" in tokenize("let the top 1.5 inches dry")


def test_content_tokens_drop_stopwords_and_stem() -> None:
    toks = content_tokens("the leaves are yellowing")
    assert "the" not in toks
    assert "are" not in toks
    assert "leav" in toks  # 'leaves' -> 'leav'
    assert "yellow" in toks  # 'yellowing' -> 'yellow'


def test_split_sentences_protects_decimals() -> None:
    out = split_sentences("Let the top 1.5 inches dry. Then water deeply.")
    assert out == ["Let the top 1.5 inches dry.", "Then water deeply."]


def test_split_sentences_empty() -> None:
    assert split_sentences("   ") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pothos is toxic to cats", False),
        ("Pothos is not toxic", True),
        ("It cannot hurt", True),
        ("no es tóxica", True),
        ("isn't fine", True),
    ],
)
def test_has_negation(text: str, expected: bool) -> None:
    assert has_negation(text) is expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("Aloe vera is safe for dogs.", "Aloe vera is toxic to dogs.", True),
        ("El potos es toxico para los gatos.", "El potos es seguro para los gatos.", True),
        ("La planta es toxica.", "La planta es segura.", True),
        ("Es venenosa para los perros.", "Es segura para los perros.", True),
        # Same side of the pair (or no pair vocabulary at all) is not a conflict.
        ("Aloe vera is toxic for dogs.", "Aloe vera is toxic to dogs.", False),
        ("Water weekly in summer.", "Water weekly in summer.", False),
        ("Pothos is toxic to cats.", "Bright indirect light is best.", False),
    ],
)
def test_has_antonym_conflict(a: str, b: str, expected: bool) -> None:
    assert has_antonym_conflict(a, b) is expected


def test_coverage_full_and_partial() -> None:
    assert coverage("yellow leaves", "yellowing leaves indicate overwatering") == 1.0
    assert coverage("", "anything") == 1.0
    assert 0.0 < coverage("yellow fertilizer", "yellow leaves") < 1.0


def test_jaccard_bounds() -> None:
    assert jaccard("water the plant", "water the plant") == 1.0
    assert jaccard("", "") == 1.0
    assert jaccard("cats toxic", "sunlight bright") == 0.0


def test_normalize_and_contains_phrase() -> None:
    assert normalize("  A  B\nC ") == "a b c"
    assert contains_phrase("This Plant Is Toxic to Cats", "toxic to cats")
    assert not contains_phrase("safe and sound", "toxic")


# --- language --------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Why are my Monstera leaves yellowing?", "en"),
        ("¿Por qué se amarillean las hojas?", "es"),
        ("Las hojas de la planta están amarillas", "es"),
        ("", "en"),
        ("12345 6789", "en"),  # no markers -> default
    ],
)
def test_detect_language(text: str, expected: str) -> None:
    assert detect_language(text) == expected


def test_detect_language_custom_default() -> None:
    assert detect_language("", default="es") == "es"


# --- config ----------------------------------------------------------------------
def test_default_config_is_valid() -> None:
    cfg = Config()
    assert cfg.languages.reference == "en"
    assert cfg.prompts.refusal_for("es").startswith("No tengo")
    assert cfg.prompts.refusal_for("fr") == cfg.prompts.refusal_for("en")  # fallback
    assert "veterinario" in cfg.prompts.safety_route_for("es")


def test_safety_directive_has_en_es_parity_and_never_certifies() -> None:
    # The urgency routing (E2), the non-toxic-caveat (R7), and the escalation card (E9)
    # must each exist in every supported language, and the composed directive must never
    # trip the never-certify-safe guard or carry an eval-suite forbidden phrase.
    from sprout.guards import asserts_safety

    cfg = Config()
    langs = set(cfg.languages.supported)
    for catalog in (
        cfg.prompts.safety_route_by_lang,
        cfg.prompts.nontoxic_caveat_by_lang,
        cfg.prompts.escalation_card_by_lang,
    ):
        assert set(catalog) == langs
    forbidden = ["is safe", "non-toxic", "safe for", "harmless", "perfectly fine"]
    for lang in langs:
        directive = cfg.prompts.safety_directive_for(lang)
        assert not asserts_safety(directive, lang, cfg.guards)
        low = directive.lower()
        assert not any(term in low for term in forbidden)
        # The standardized escalation card names the real public authorities.
        assert "888-426-4435" in directive and "855-764-7661" in directive


def test_detect_exposure_type_classifies_child_animal_both_unspecified() -> None:
    # FIX-13: exposure-type routing must be deterministic and keyword-driven, matching
    # the audience the query actually names.
    from sprout.guards import detect_exposure_type

    cfg = Config().guards
    assert detect_exposure_type("Is this toxic to my cat?", "en", cfg) == "animal"
    assert detect_exposure_type("My dog chewed a leaf, is that bad?", "en", cfg) == "animal"
    assert detect_exposure_type("My toddler bit a leaf off this plant", "en", cfg) == "child"
    assert detect_exposure_type("Is this safe for my baby?", "en", cfg) == "child"
    assert detect_exposure_type("Is this toxic to kids or pets?", "en", cfg) == "both"
    assert detect_exposure_type("Is this plant poisonous?", "en", cfg) == "unspecified"
    # Spanish mirrors the English classification (multilingual parity, R4).
    assert detect_exposure_type("¿Es tóxico para mi gato?", "es", cfg) == "animal"
    assert detect_exposure_type("Mi niño mordió una hoja de esta planta", "es", cfg) == "child"


def test_human_escalation_card_gated_off_by_default() -> None:
    # FIX-13 hard gate: the human-poison-control card must not render for any exposure
    # type until a real clinician sign-off flips ``human_card_reviewed`` to True (see
    # docs/audits/human-poison-control-card-review.md). Default config behavior for a
    # child-ingestion query is unchanged from before FIX-13: only the animal card shows.
    cfg = Config()
    assert cfg.prompts.human_card_reviewed is False
    for exposure_type in ("child", "animal", "both", "unspecified", None):
        directive = cfg.prompts.safety_directive_for("en", exposure_type)
        assert "1-800-222-1222" not in directive
        assert "poison.org" not in directive
        # The animal card still renders exactly as before FIX-13.
        assert "888-426-4435" in directive


def test_human_escalation_card_renders_only_for_child_exposure_once_reviewed() -> None:
    # Simulates post-sign-off state: a reviewer has flipped human_card_reviewed to True
    # (docs/audits/human-poison-control-card-review.md filled in). The human card must
    # then appear *alongside*, never instead of, the animal card, and only for
    # audiences that name a child ("child" or "both") -- never for a pure animal query.
    cfg = Config()
    reviewed_prompts = cfg.prompts.model_copy(update={"human_card_reviewed": True})

    for exposure_type in ("child", "both"):
        directive = reviewed_prompts.safety_directive_for("en", exposure_type)
        assert "1-800-222-1222" in directive
        assert "888-426-4435" in directive  # animal card still present, not replaced

    for non_child_exposure_type in ("animal", "unspecified", None):
        directive = reviewed_prompts.safety_directive_for("en", non_child_exposure_type)
        assert "1-800-222-1222" not in directive
        assert "888-426-4435" in directive

    # Spanish parity for the human card too.
    directive_es = reviewed_prompts.safety_directive_for("es", "child")
    assert "1-800-222-1222" in directive_es
    assert "888-426-4435" in directive_es


def test_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"corpus": {"nope": 1}})


def test_config_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"retrieval": {"min_score": 2.0}})


def test_load_config_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("retrieval:\n  top_k: 9\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.retrieval.top_k == 9


def test_load_config_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "absent.yaml")


def test_load_config_empty_is_defaults(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    assert load_config(p).retrieval.top_k == Config().retrieval.top_k


def test_load_config_non_mapping(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_config(p)


# --- models ----------------------------------------------------------------------
def _chunk() -> Chunk:
    return Chunk(
        chunk_id="c1",
        doc_id="d1",
        title="Monstera care",
        source="monstera.md",
        text="Yellowing leaves indicate overwatering.",
        language="en",
        topic="watering",
        source_name="Synthetic Care Notes",
        url="https://example.invalid/monstera",
        license="CC0-1.0",
        fetch_date="2026-05-01",
    )


def test_chunk_citation_label() -> None:
    assert _chunk().citation_label == "Monstera care — monstera.md (as of 2026-05-01)"


def test_answer_text_citations_and_coverage() -> None:
    c = _chunk()
    cit = Citation(
        chunk_id=c.chunk_id,
        doc_id=c.doc_id,
        title=c.title,
        source=c.source,
        quote=c.text,
        license=c.license,
        fetch_date=c.fetch_date,
        url=c.url,
    )
    s = AnswerSentence(text=c.text, chunk_id=c.chunk_id, citation=cit)
    ans = Answer(question="why yellow?", language="en", sentences=(s, s))
    assert ans.text == f"{c.text} {c.text}"
    assert len(ans.citations) == 1  # deduped by chunk_id
    assert math.isclose(ans.citation_coverage, 1.0)


def test_empty_answer_coverage_is_zero() -> None:
    assert Answer(question="q", language="en").citation_coverage == 0.0


def test_models_are_frozen() -> None:
    c = _chunk()
    with pytest.raises(ValidationError):
        c.text = "mutated"  # frozen model rejects assignment
