"""Tests for the per-language data bundles and completeness gate (FIX-09).

``docs/ideation/02-large-scale-fixes.md`` FIX-09: EN/ES data lives in one
``locales/<lang>/bundle.yaml`` per language, and a load-time completeness validator
keyed off ``languages.supported`` fails config load — not render — when a supported
language's bundle is missing or missing a key the reference bundle defines.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sprout import locales
from sprout.config import Config


def test_available_languages_has_reference_first() -> None:
    langs = locales.available_languages()
    assert langs[0] == locales.REFERENCE_LANGUAGE == "en"
    assert set(langs) == {"en", "es"}


def test_load_bundle_en_and_es_share_the_same_key_shape() -> None:
    en_keys = locales._flatten_keys(locales.load_bundle("en"))
    es_keys = locales._flatten_keys(locales.load_bundle("es"))
    # es may carry no *more* required-schema keys than en defines missing, but must
    # carry at least everything en defines (the completeness gate's own invariant).
    assert en_keys <= es_keys


def test_load_bundle_missing_language_raises() -> None:
    with pytest.raises(locales.LocaleCompletenessError, match="no locale bundle"):
        locales.load_bundle("xx")


def test_validate_completeness_passes_for_default_languages() -> None:
    locales.validate_completeness(["en", "es"])


def test_validate_completeness_empty_is_a_noop() -> None:
    locales.validate_completeness([])


def test_validate_completeness_fails_for_language_with_no_bundle() -> None:
    with pytest.raises(locales.LocaleCompletenessError, match="no locale bundle"):
        locales.validate_completeness(["en", "fr"])


def test_validate_completeness_fails_for_incomplete_stub_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stub ``fr/`` bundle that exists but is missing keys the reference (en) bundle
    defines fails the completeness gate rather than silently falling back to English —
    this is FIX-09's stated "excellent looks like" bar.
    """
    en_dir = tmp_path / "en"
    en_dir.mkdir()
    (en_dir / "bundle.yaml").write_text(
        "prompts:\n  refusal: 'no'\n  disclosure: 'no'\n", encoding="utf-8"
    )
    fr_dir = tmp_path / "fr"
    fr_dir.mkdir()
    (fr_dir / "bundle.yaml").write_text("prompts:\n  refusal: 'non'\n", encoding="utf-8")
    monkeypatch.setattr(locales, "_LOCALES_DIR", tmp_path)
    locales.load_bundle.cache_clear()
    try:
        with pytest.raises(locales.LocaleCompletenessError, match="missing keys"):
            locales.validate_completeness(["en", "fr"])
    finally:
        locales.load_bundle.cache_clear()


def test_config_rejects_unsupported_language_with_no_bundle() -> None:
    with pytest.raises(locales.LocaleCompletenessError):
        Config.model_validate({"languages": {"supported": ["en", "fr"]}})


def test_merged_list_unions_and_dedupes_preserving_order() -> None:
    merged = locales.merged_list("eval", "poison_terms", ("en", "es"))
    assert merged == ["poison", "envenen", "intoxica"]


def test_by_lang_returns_one_value_per_language() -> None:
    values = locales.by_lang("prompts", "refusal", ("en", "es"))
    assert set(values) == {"en", "es"}
    assert values["en"] != values["es"]
