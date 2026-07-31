"""EN/ES key + placeholder parity — the I18N ledger row (docs/ROADMAP.md), FIX-02.

Walks every per-language string/list bundle reachable from ``Config`` (any dict field
whose keys are drawn from ``languages.supported``, e.g. ``PromptConfig.refusal_by_lang``
or ``GuardsConfig.forbidden_safe_phrases``) and asserts two things the ledger has claimed
as an ``AUTO`` gate since before this test existed: (a) no orphan keys — a bundle's key
set exactly matches the supported languages, so no language is silently missing or an
extra one silently ignored; (b) for string-valued (template) bundles, the ``{placeholder}``
names used in one language's text are used in every other language's text too, so a
translation can't drop or rename a substitution and crash ``str.format`` at answer time.

Previously the ledger's "per-language bundle diff" measured-by cell named no such
mechanism (AIEV/I18N gap, corrected 2026-07-08) — this closes that gap for real.
"""

from __future__ import annotations

import contextlib
import re

import pytest
from pydantic import BaseModel

from sprout.config import Config, load_config

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_DEFAULT_CONFIG_PATH = "config/sprout.yaml"


def _iter_language_bundles(
    model: BaseModel, supported: frozenset[str], path: str = ""
) -> list[tuple[str, dict[str, object]]]:
    """Yield (field_path, bundle) for every non-empty dict field keyed only by
    supported-language codes, recursing into nested config models."""
    found: list[tuple[str, dict[str, object]]] = []
    for name in type(model).model_fields:
        value = getattr(model, name)
        field_path = f"{path}.{name}" if path else name
        if isinstance(value, BaseModel):
            found.extend(_iter_language_bundles(value, supported, field_path))
        elif isinstance(value, dict) and value and set(value.keys()) <= supported:
            found.append((field_path, value))
    return found


def _configs() -> list[Config]:
    """Both the library defaults and the shipped config — either could drift."""
    configs = [Config()]
    with contextlib.suppress(FileNotFoundError):
        # test_foundation.py already covers the load-failure path; not this test's job.
        configs.append(load_config(_DEFAULT_CONFIG_PATH))
    return configs


@pytest.mark.parametrize("cfg", _configs(), ids=lambda c: "loaded" if c is not None else "x")
def test_language_bundles_have_no_orphan_keys(cfg: Config) -> None:
    supported = frozenset(cfg.languages.supported)
    bundles = _iter_language_bundles(cfg, supported)
    assert bundles, "expected at least one per-language bundle on Config"
    problems = []
    for field_path, bundle in bundles:
        keys = set(bundle.keys())
        if keys != supported:
            missing = supported - keys
            extra = keys - supported
            problems.append(f"{field_path}: missing={sorted(missing)} extra={sorted(extra)}")
    assert not problems, "orphan/missing language key(s):\n" + "\n".join(problems)


@pytest.mark.parametrize("cfg", _configs(), ids=lambda c: "loaded" if c is not None else "x")
def test_language_bundle_placeholders_match_across_languages(cfg: Config) -> None:
    supported = frozenset(cfg.languages.supported)
    bundles = _iter_language_bundles(cfg, supported)
    problems = []
    for field_path, bundle in bundles:
        if not all(isinstance(v, str) for v in bundle.values()):
            continue  # list-valued bundles (deny-lists/keyword lists) carry no placeholders
        placeholder_sets = {
            lang: frozenset(_PLACEHOLDER.findall(str(text))) for lang, text in bundle.items()
        }
        reference = next(iter(placeholder_sets.values()))
        mismatched = {lang: ph for lang, ph in placeholder_sets.items() if ph != reference}
        if mismatched:
            problems.append(f"{field_path}: placeholder mismatch {dict(placeholder_sets)}")
    assert not problems, "placeholder parity violated:\n" + "\n".join(problems)
