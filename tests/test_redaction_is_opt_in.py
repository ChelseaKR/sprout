"""The cloud path's PII redaction is a second switch, and it is off (#179).

Three documents used to state redaction as a property of "cloud mode". It is not: it runs only
when ``generation.redact_query_pii`` is true, that flag is false in all three places it is
declared, and nothing couples it to ``generation.provider``. The prose was corrected to say so;
these tests pin the facts the corrected prose asserts, so a change to either side fails loudly
instead of re-opening the gap.

Two directions are pinned:

* **The default.** All three declaration sites agree, and choosing a cloud provider does not
  flip any of them. If the default is ever changed to true (the behaviour-change repair
  recorded in #179), these fail together with the three ``*-redact-query-pii-default`` entries
  in ``docs/claims.yaml`` -- the docs cannot silently keep the old sentence either way.
* **The scope.** ``redact_pii`` recognises exactly the three classes the documents name.
  A document that grows a fourth class has to grow a pattern with it.

Every literal below is synthetic: ``example.invalid`` is reserved by RFC 2606, ``555-0100`` is
a reserved fictional exchange, and an all-zero SSN is never issued.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sprout.config import Config, load_config
from sprout.guards import redact_pii

ROOT = Path(__file__).resolve().parents[1]
_REPO_CONFIG = ROOT / "config" / "sprout.yaml"
_PACKAGED_CONFIG = ROOT / "src" / "sprout" / "data" / "sprout.yaml"


def test_the_flag_is_false_in_all_three_declaration_sites() -> None:
    """The dataclass default, the repo config, and the packaged config must agree."""
    dataclass_default = Config().generation.redact_query_pii
    repo_config = load_config(_REPO_CONFIG).generation.redact_query_pii
    packaged = load_config(_PACKAGED_CONFIG).generation.redact_query_pii
    assert dataclass_default == repo_config == packaged, (
        "the three declaration sites of generation.redact_query_pii disagree; "
        "docs/THREAT-MODEL.md T5 states them as one value"
    )
    assert dataclass_default is False, (
        "generation.redact_query_pii is no longer false by default -- that is the "
        "behaviour-change repair recorded in #179, and it requires rewriting the T5 "
        "mitigation bullet, the R3 control bullet and the RESPONSIBLE-TECH-AUDITS "
        "lawful-basis bullet, plus their docs/claims.yaml entries"
    )


def test_the_packaged_yaml_declares_the_flag_explicitly() -> None:
    """The packaged default is a written value, not an omission that inherits the dataclass."""
    raw = yaml.safe_load(_PACKAGED_CONFIG.read_text(encoding="utf-8"))
    assert "redact_query_pii" in raw["generation"]


@pytest.mark.parametrize("provider", ["deterministic", "bedrock", "anthropic"])
def test_choosing_a_cloud_provider_does_not_enable_redaction(provider: str) -> None:
    """The premise of the corrected sentence: the two switches are independent."""
    cfg = Config.model_validate({"generation": {"provider": provider}})
    assert cfg.generation.redact_query_pii is False


# The three classes docs/THREAT-MODEL.md T5 names, and a sample of what it now says is
# *not* covered. Synthetic values only.
_MASKED = {
    "email": "write to plantfan@example.invalid about it",
    "ssn": "my number is 000-00-0000",
    "phone": "call 555-0100-9999",
}
_NOT_MASKED = {
    "person_name": "my name is Jane Q. Publicsample",
    "street_address": "I live at 1234 Nowhere Terrace",
    "ip_address": "from 203.0.113.7",
    "geo_coordinates": "at 0.000000, 0.000000",
}


@pytest.mark.parametrize("name", sorted(_MASKED))
def test_redact_pii_masks_each_class_the_docs_name(name: str) -> None:
    probe = _MASKED[name]
    assert redact_pii(probe) != probe, f"{name} is documented as masked but survived redaction"


@pytest.mark.parametrize("name", sorted(_NOT_MASKED))
def test_redact_pii_does_not_claim_classes_it_has_no_pattern_for(name: str) -> None:
    """Pins the scope sentence. If a pattern is added, the docs must name the new class."""
    probe = _NOT_MASKED[name]
    assert redact_pii(probe) == probe, (
        f"redact_pii now touches {name}; docs/THREAT-MODEL.md T5 says emails / SSNs / phones "
        "are the only classes it knows and must be updated"
    )
