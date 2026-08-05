"""Per-language data bundles: one place per language, one completeness gate.

FIX-09 (``docs/ideation/02-large-scale-fixes.md``). Before this module, EN/ES data was
scattered across ``PromptConfig`` and ``GuardsConfig`` (:mod:`sprout.config`),
``guards._HARM_TOKENS``/``_SOURCE_MARKERS`` (:mod:`sprout.guards`), the ``lang.py``
marker sets, and bilingual term lists hard-coded in the safety eval suite — adding a
third language meant an eight-file surgery. Now each language's prompts, deny-list,
keyword vocab, detection markers, and eval-suite vocabulary live in one
``locales/<lang>/bundle.yaml``, and :func:`validate_completeness` fails fast at config
load time (not at render time) if a supported language's bundle is missing or
incomplete relative to the reference language's key shape.

Everything downstream (``config.py``, ``guards.py``, ``lang.py``,
``eval/suites/safety.py``) reads from these bundles rather than carrying its own copy,
so adding language #3 is a data drop: create ``locales/<lang>/bundle.yaml`` with every
key the reference bundle defines, add the tag to ``languages.supported``, done.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

_LOCALES_DIR = Path(__file__).resolve().parent

# The reference bundle's key shape is the schema every other language's bundle is
# validated against. Matches Config.languages.reference's convention (first-listed
# language is authoritative).
REFERENCE_LANGUAGE = "en"


class LocaleCompletenessError(RuntimeError):
    """Raised at config load time when a supported language's bundle is missing or
    missing keys the reference language's bundle defines."""


def available_languages() -> tuple[str, ...]:
    """Languages with a bundle on disk, reference language first if present.

    This is what drives ``lang.py``'s detectable-language set: a new
    ``locales/<lang>/bundle.yaml`` becomes detectable with no code change.
    """
    langs = sorted(
        p.name
        for p in _LOCALES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "bundle.yaml").exists()
    )
    if REFERENCE_LANGUAGE in langs:
        langs.remove(REFERENCE_LANGUAGE)
        langs.insert(0, REFERENCE_LANGUAGE)
    return tuple(langs)


@cache
def load_bundle(language: str) -> dict[str, Any]:
    """Load and cache one language's bundle. Raises if the file is absent or malformed."""
    path = _LOCALES_DIR / language / "bundle.yaml"
    if not path.exists():
        raise LocaleCompletenessError(
            f"no locale bundle for language {language!r} (expected {path})"
        )
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise LocaleCompletenessError(f"locale bundle for {language!r} must be a mapping")
    return raw


def _flatten_keys(d: dict[str, Any], prefix: str = "") -> set[str]:
    """Dotted key paths of every (possibly nested) mapping key in ``d``.

    Only mapping structure is walked (not list contents), so the schema check is about
    *which strings/lists exist*, not their length — a language may legitimately have a
    shorter deny-list, just not a missing one.
    """
    out: set[str] = set()
    for k, v in d.items():
        key = f"{prefix}{k}"
        out.add(key)
        if isinstance(v, dict):
            out |= _flatten_keys(v, prefix=f"{key}.")
    return out


def validate_completeness(languages: list[str]) -> None:
    """Fail fast if any of ``languages`` lacks a bundle, or a bundle is missing a key
    the reference language's bundle defines.

    The reference language is ``languages[0]`` (matches ``LanguageConfig.reference``).
    This is the load-time completeness gate FIX-09 requires: a stub bundle for a new
    language that doesn't carry every key the reference defines fails config load
    instead of silently falling back to English at render time.
    """
    if not languages:
        return
    reference = languages[0]
    ref_keys = _flatten_keys(load_bundle(reference))
    for lang in languages:
        keys = _flatten_keys(load_bundle(lang))
        missing = ref_keys - keys
        if missing:
            raise LocaleCompletenessError(
                f"locale bundle {lang!r} is missing keys present in reference language "
                f"{reference!r}: {sorted(missing)}"
            )


def by_lang(section: str, key: str, languages: tuple[str, ...]) -> dict[str, Any]:
    """``{language: bundle[section][key]}`` for each of ``languages``.

    Used for the ``*_by_lang`` config fields (prompts, deny-lists) that are genuinely
    rendered per-language, never merged.
    """
    return {lang: load_bundle(lang).get(section, {}).get(key) for lang in languages}


def merged_list(section: str, key: str, languages: tuple[str, ...]) -> list[str]:
    """Union of a list-valued leaf across ``languages``, preserving first-seen order.

    Used for cross-lingual vocabulary (harm tokens, source markers, suite routing
    terms) that is *authored* per-language for locality but *consumed* as one
    deduplicated set — e.g. the never-certify-safe negation check matches a harm token
    in either supported language regardless of which language the answer is in.
    """
    seen: dict[str, None] = {}
    for lang in languages:
        for v in load_bundle(lang).get(section, {}).get(key, []):
            seen[v] = None
    return list(seen)
