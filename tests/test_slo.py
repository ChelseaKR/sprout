"""Schema validation for the Tier-A SLO + burn-rate-alert files, and the committed
``slos/*.yaml`` / ``alerts/*.yml`` themselves — a regression that would otherwise only be
caught by the (not-installed-here) `promtool` at deploy time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sprout.slo import (
    SLOSchemaError,
    check_all,
    validate_alert_rules_file,
    validate_burn_rate_tiers,
    validate_slo_file,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_committed_slo_files_are_valid() -> None:
    slo_dir = _REPO_ROOT / "slos"
    files = sorted(slo_dir.glob("*.yaml"))
    assert files, "expected at least one committed SLO file"
    for f in files:
        validate_slo_file(f)  # raises on failure


def test_committed_alert_rules_file_is_valid_and_has_both_burn_tiers() -> None:
    path = _REPO_ROOT / "alerts" / "burn-rate.yml"
    assert path.exists()
    validate_alert_rules_file(path)
    validate_burn_rate_tiers(path)


def test_check_all_on_repo_root_reports_no_problems() -> None:
    assert check_all(_REPO_ROOT / "slos", _REPO_ROOT / "alerts") == []


def test_check_all_tolerates_missing_directories(tmp_path: Path) -> None:
    assert check_all(tmp_path / "no-slos", tmp_path / "no-alerts") == []


def test_check_all_collects_problems_from_both_slos_and_alerts(tmp_path: Path) -> None:
    slo_dir = tmp_path / "slos"
    alerts_dir = tmp_path / "alerts"
    slo_dir.mkdir()
    alerts_dir.mkdir()
    (slo_dir / "bad.yaml").write_text(yaml.dump({"name": "x"}), encoding="utf-8")
    (alerts_dir / "bad.yml").write_text(
        yaml.dump({"groups": [{"name": "g", "rules": [{"alert": "a", "expr": "x > 1"}]}]}),
        encoding="utf-8",
    )  # valid shape, but missing the high-burn-rate tier
    problems = check_all(slo_dir, alerts_dir)
    assert len(problems) == 2


def test_slo_file_with_no_groups_key_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text(yaml.dump({"not_groups": []}), encoding="utf-8")
    with pytest.raises(SLOSchemaError):
        validate_alert_rules_file(bad)


def test_alert_group_missing_name_or_rules_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text(yaml.dump({"groups": [{"name": "g"}]}), encoding="utf-8")
    with pytest.raises(SLOSchemaError):
        validate_alert_rules_file(bad)


def test_alert_group_rules_not_a_list_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text(yaml.dump({"groups": [{"name": "g", "rules": "oops"}]}), encoding="utf-8")
    with pytest.raises(SLOSchemaError):
        validate_alert_rules_file(bad)


def test_slo_file_rejects_missing_required_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.dump({"name": "x", "sli_query": "1", "target_percentage": 99.0}),
        encoding="utf-8",
    )
    with pytest.raises(SLOSchemaError):
        validate_slo_file(bad)


def test_slo_file_rejects_unknown_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.dump(
            {
                "name": "x",
                "sli_query": "1",
                "target_percentage": 99.0,
                "window_days": 28,
                "error_budget_policy": "freeze",
                "unexpected_key": "oops",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SLOSchemaError):
        validate_slo_file(bad)


def test_alert_rule_must_be_exactly_one_of_record_or_alert(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text(
        yaml.dump({"groups": [{"name": "g", "rules": [{"expr": "up"}]}]}),
        encoding="utf-8",
    )
    with pytest.raises(SLOSchemaError):
        validate_alert_rules_file(bad)


def test_alert_rule_rejects_both_record_and_alert(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text(
        yaml.dump(
            {"groups": [{"name": "g", "rules": [{"record": "r", "alert": "a", "expr": "up"}]}]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(SLOSchemaError):
        validate_alert_rules_file(bad)


def test_alert_rule_rejects_empty_expr(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text(
        yaml.dump({"groups": [{"name": "g", "rules": [{"alert": "a", "expr": "  "}]}]}),
        encoding="utf-8",
    )
    with pytest.raises(SLOSchemaError):
        validate_alert_rules_file(bad)


def test_burn_rate_tiers_requires_both_critical_and_high(tmp_path: Path) -> None:
    only_critical = tmp_path / "only-critical.yml"
    only_critical.write_text(
        yaml.dump(
            {
                "groups": [
                    {
                        "name": "g",
                        "rules": [{"alert": "Crit", "expr": "x > (14.4 * 0.01)"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SLOSchemaError):
        validate_burn_rate_tiers(only_critical)


def test_burn_rate_tiers_passes_with_both(tmp_path: Path) -> None:
    both = tmp_path / "both.yml"
    both.write_text(
        yaml.dump(
            {
                "groups": [
                    {
                        "name": "g",
                        "rules": [
                            {"alert": "Crit", "expr": "x > (14.4 * 0.01)"},
                            {"alert": "High", "expr": "x > (6 * 0.01)"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    validate_burn_rate_tiers(both)  # does not raise


def test_not_yaml_raises_schema_error(tmp_path: Path) -> None:
    bad = tmp_path / "broken.yaml"
    bad.write_text("name: [unterminated", encoding="utf-8")
    with pytest.raises(SLOSchemaError):
        validate_slo_file(bad)
