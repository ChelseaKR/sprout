"""Model-card front-matter completeness lint — AIEV-22.

Validates the HuggingFace-style YAML front matter in ``docs/cards/model-card.md`` carries
the fields the AI-Evaluation-Standard requires (language, license, tags, co2_eq_emissions,
model-index), each present and non-empty. ``docs/RESPONSIBLE-TECH-AUDITS.md`` §D previously
claimed a "model-card / datasheet YAML completeness lint" with no such check actually wired
(AIEV-22); this test closes that gap for real rather than just softening the claim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_REQUIRED_FIELDS = ("language", "license", "tags", "co2_eq_emissions", "model-index")
_MODEL_CARD = Path("docs/cards/model-card.md")
_EVAL_REPORT = Path("docs/audits/eval-report.json")


def _front_matter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} must open with a '---' YAML front-matter block"
    _, _, rest = text.partition("---\n")
    raw, sep, _ = rest.partition("\n---")
    assert sep, f"{path} front-matter block is not closed with a second '---'"
    data = yaml.safe_load(raw)
    assert isinstance(data, dict), f"{path} front matter must parse to a YAML mapping"
    return data


def test_model_card_front_matter_has_required_fields() -> None:
    data = _front_matter(_MODEL_CARD)
    missing = [f for f in _REQUIRED_FIELDS if not data.get(f) and data.get(f) != 0]
    assert not missing, f"{_MODEL_CARD} front matter missing/empty required field(s): {missing}"
    assert isinstance(data["tags"], list) and data["tags"], "tags must be a non-empty list"
    assert isinstance(data["language"], list) and data["language"], "language must be non-empty"
    assert isinstance(data["model-index"], list) and data["model-index"], (
        "model-index must be a non-empty list"
    )
    assert isinstance(data["co2_eq_emissions"], dict) and "emissions" in data["co2_eq_emissions"]


def _front_matter_metric(metric_type: str) -> dict[str, Any]:
    data = _front_matter(_MODEL_CARD)
    results = data["model-index"][0]["results"]  # type: ignore[index]
    metrics = [m for entry in results for m in entry["metrics"]]
    matches = [m for m in metrics if m["type"] == metric_type]
    assert len(matches) == 1, f"expected exactly one {metric_type!r} metric, got {len(matches)}"
    return dict(matches[0])


def test_model_card_en_es_parity_matches_the_committed_eval_report() -> None:
    """The card's `en-es-parity` figure is a *measurement*, so it gets pinned to the run.

    Every other `model-index` value states a by-construction guarantee (groundedness = 1.0,
    forbidden certifications = 0.0). This one moves with the corpus and the case set, which
    makes a hand-typed number here exactly the kind of stale-figure-in-a-card the claims
    gate exists to prevent — and it cannot be covered by `docs/claims.yaml`, whose values
    are matched at two decimal places and whose markers cannot live inside YAML front
    matter. So it is pinned directly, at full precision, to the `language-parity` score in
    the committed report. (`tests/test_committed_artifacts_are_current.py` separately
    guarantees that report is not itself stale.)
    """
    report = json.loads(_EVAL_REPORT.read_text(encoding="utf-8"))
    suites = {s["suite"]: s for s in report["suite_results"]}
    assert "language-parity" in suites, (
        "the committed eval report has no `language-parity` suite; the card cannot state a "
        "measured EN/ES parity gap without one"
    )
    measured = suites["language-parity"]["score"]
    metric = _front_matter_metric("en-es-parity")
    assert metric["value"] == measured, (
        f"model card front matter says en-es-parity={metric['value']!r} but the committed "
        f"eval report measured {measured!r}; regenerate the card's figure (`make eval`)"
    )


def test_model_card_en_es_parity_is_never_silently_null() -> None:
    """`value: null` meant "never measured" and was honest while nothing computed it.

    Something computes it now, so a null here would no longer be honesty — it would be a
    measurement that went missing while the surrounding prose still claimed a gate.
    """
    assert _front_matter_metric("en-es-parity")["value"] is not None
