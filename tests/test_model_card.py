"""Model-card front-matter completeness lint — AIEV-22.

Validates the HuggingFace-style YAML front matter in ``docs/cards/model-card.md`` carries
the fields the AI-Evaluation-Standard requires (language, license, tags, co2_eq_emissions,
model-index), each present and non-empty. ``docs/RESPONSIBLE-TECH-AUDITS.md`` §D previously
claimed a "model-card / datasheet YAML completeness lint" with no such check actually wired
(AIEV-22); this test closes that gap for real rather than just softening the claim.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REQUIRED_FIELDS = ("language", "license", "tags", "co2_eq_emissions", "model-index")
_MODEL_CARD = Path("docs/cards/model-card.md")


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
