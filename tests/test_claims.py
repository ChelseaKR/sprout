"""Claims-integrity gate: docs/claims.yaml resolved against code/config, and mutation detection."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sprout.claims import ClaimsError, check
from sprout.cli import app

runner = CliRunner()

_CONFIG_YAML = """
confidence:
  abstain_threshold: 0.25
  low_confidence_threshold: 0.50
"""


def _write_fixture(root: Path, *, abstain: str = "0.25") -> None:
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "sprout.yaml").write_text(_CONFIG_YAML, encoding="utf-8")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "audits").mkdir(exist_ok=True)
    (root / "docs" / "doc.md").write_text(
        f"Below `abstain_threshold` (default **{abstain}**)<!-- claim:abstain -->, refuse.\n",
        encoding="utf-8",
    )
    claims = {
        "claims": [
            {
                "id": "abstain",
                "file": "docs/doc.md",
                "source": "config:confidence.abstain_threshold",
                "expected": "0.25",
                "marker": "<!-- claim:abstain -->",
            }
        ]
    }
    (root / "docs" / "claims.yaml").write_text(yaml.safe_dump(claims), encoding="utf-8")


def test_check_passes_on_reconciled_tree() -> None:
    """The real registry, checked against the real repo, has zero drift after reconciliation."""
    assert check() == []


def test_check_detects_mutated_doc_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_fixture(tmp_path, abstain="0.25")
    assert check() == []

    # Mutate only the doc text; config and registry are untouched.
    (tmp_path / "docs" / "doc.md").write_text(
        "Below `abstain_threshold` (default **0.99**)<!-- claim:abstain -->, refuse.\n",
        encoding="utf-8",
    )
    problems = check()
    assert len(problems) == 1
    assert "abstain" in problems[0]
    assert "0.25" in problems[0]


def test_check_detects_stale_registry_vs_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If config drifts and the registry is not updated, that is reported too."""
    monkeypatch.chdir(tmp_path)
    _write_fixture(tmp_path, abstain="0.25")
    (tmp_path / "config" / "sprout.yaml").write_text(
        "confidence:\n  abstain_threshold: 0.30\n  low_confidence_threshold: 0.50\n",
        encoding="utf-8",
    )
    problems = check()
    assert len(problems) == 1
    assert "stale" in problems[0]


def test_check_policy_source_has_no_code_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A policy: source is registry-authoritative; only the doc side is checked."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "doc.md").write_text(
        "Sprout targets WCAG 2.2 Level AA.<!-- claim:wcag -->\n", encoding="utf-8"
    )
    claims = {
        "claims": [
            {
                "id": "wcag",
                "file": "docs/doc.md",
                "source": "policy:wcag-conformance-level",
                "expected": "AA",
                "marker": "<!-- claim:wcag -->",
            }
        ]
    }
    (tmp_path / "docs" / "claims.yaml").write_text(yaml.safe_dump(claims), encoding="utf-8")
    assert check() == []


def test_check_missing_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_fixture(tmp_path)
    (tmp_path / "docs" / "doc.md").write_text("no marker here\n", encoding="utf-8")
    problems = check()
    assert len(problems) == 1
    assert "marker" in problems[0]


def test_check_missing_doc_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_fixture(tmp_path)
    (tmp_path / "docs" / "doc.md").unlink()
    problems = check()
    assert len(problems) == 1
    assert "not found" in problems[0]


def test_check_unresolvable_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_fixture(tmp_path)
    claims = {
        "claims": [
            {
                "id": "abstain",
                "file": "docs/doc.md",
                "source": "config:confidence.nonexistent_field",
                "expected": "0.25",
                "marker": "<!-- claim:abstain -->",
            }
        ]
    }
    (tmp_path / "docs" / "claims.yaml").write_text(yaml.safe_dump(claims), encoding="utf-8")
    problems = check()
    assert len(problems) == 1
    assert "could not resolve" in problems[0]


def test_check_unknown_source_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_fixture(tmp_path)
    claims = {
        "claims": [
            {
                "id": "abstain",
                "file": "docs/doc.md",
                "source": "mystery:whatever",
                "expected": "0.25",
                "marker": "<!-- claim:abstain -->",
            }
        ]
    }
    (tmp_path / "docs" / "claims.yaml").write_text(yaml.safe_dump(claims), encoding="utf-8")
    problems = check()
    assert len(problems) == 1
    assert "unknown claim source kind" in problems[0]


def test_check_string_and_bool_config_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-float config values (str, bool) compare as text, not as numbers."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sprout.yaml").write_text(
        "retrieval:\n  embedding_provider: deterministic\n  hybrid: true\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "doc.md").write_text(
        "Provider **deterministic**<!-- claim:provider -->,"
        " hybrid **True**<!-- claim:hybrid -->.\n",
        encoding="utf-8",
    )
    claims = {
        "claims": [
            {
                "id": "provider",
                "file": "docs/doc.md",
                "source": "config:retrieval.embedding_provider",
                "expected": "deterministic",
                "marker": "<!-- claim:provider -->",
            },
            {
                "id": "hybrid",
                "file": "docs/doc.md",
                "source": "config:retrieval.hybrid",
                "expected": "True",
                "marker": "<!-- claim:hybrid -->",
            },
        ]
    }
    (tmp_path / "docs" / "claims.yaml").write_text(yaml.safe_dump(claims), encoding="utf-8")
    assert check() == []


def test_check_eval_report_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_fixture(tmp_path)
    claims = {
        "claims": [
            {
                "id": "abstain",
                "file": "docs/doc.md",
                "source": "eval-report:refusal.metric.threshold",
                "expected": "0.90",
                "marker": "<!-- claim:abstain -->",
            }
        ]
    }
    (tmp_path / "docs" / "claims.yaml").write_text(yaml.safe_dump(claims), encoding="utf-8")
    problems = check()
    assert len(problems) == 1
    assert "could not resolve" in problems[0]


def test_check_eval_report_missing_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_fixture(tmp_path)
    (tmp_path / "docs" / "audits" / "eval-report.json").write_text(
        '{"suite_results": []}', encoding="utf-8"
    )
    claims = {
        "claims": [
            {
                "id": "abstain",
                "file": "docs/doc.md",
                "source": "eval-report:refusal.metric.threshold",
                "expected": "0.90",
                "marker": "<!-- claim:abstain -->",
            }
        ]
    }
    (tmp_path / "docs" / "claims.yaml").write_text(yaml.safe_dump(claims), encoding="utf-8")
    problems = check()
    assert len(problems) == 1
    assert "could not resolve" in problems[0]


def test_load_claims_entry_not_a_mapping(tmp_path: Path) -> None:
    bad = tmp_path / "claims.yaml"
    bad.write_text(yaml.safe_dump({"claims": ["not-a-mapping"]}), encoding="utf-8")
    with pytest.raises(ClaimsError):
        check(claims_path=bad)


def test_check_refusal_suite_source() -> None:
    """The suite: source resolves live against RefusalSuite().metric.threshold (0.90)."""
    problems = check()
    assert not any("roadmap-refusal-target" in p for p in problems)


def test_check_eval_report_source() -> None:
    """The eval-report: source resolves a field from the committed eval report."""
    problems = check()
    assert not any("roadmap-groundedness-threshold" in p for p in problems)


# --- README claims (issue #97): floor vs. measured, and the real suite list -----------------


def test_check_readme_calibration_floor_sources() -> None:
    """suite:calibration.min_agreement / min_kappa resolve to the ENFORCED FLOOR (0.80/0.60),
    not the last measured value (0.955/0.906) — the exact collapse issue #97 found in the
    README."""
    problems = check()
    assert not any("readme-judge-calibration-floor-agreement" in p for p in problems)
    assert not any("readme-judge-calibration-floor-kappa" in p for p in problems)


def test_check_readme_refusal_target_source() -> None:
    problems = check()
    assert not any("readme-refusal-target" in p for p in problems)


def test_check_readme_coverage_floor_source() -> None:
    """pytest:cov-fail-under resolves the real --cov-fail-under value from pyproject.toml."""
    problems = check()
    assert not any("readme-coverage-floor" in p for p in problems)


def test_check_readme_eval_suite_count_and_names_sources() -> None:
    """eval-report:suites.count / suites.names resolve from the committed eval report — the
    README no longer hand-carries a suite list that can silently fall behind a new suite."""
    problems = check()
    assert not any("readme-eval-suite-count" in p for p in problems)
    assert not any("readme-eval-suite-names" in p for p in problems)


def test_resolve_suite_calibration_floors() -> None:
    from sprout.claims import _resolve_suite

    assert _resolve_suite("calibration.min_agreement") == "0.80"
    assert _resolve_suite("calibration.min_kappa") == "0.60"


def test_resolve_suite_unknown_raises() -> None:
    from sprout.claims import _resolve_suite

    with pytest.raises(ClaimsError, match="unknown suite claim source"):
        _resolve_suite("nonsense.field")


def test_resolve_pytest_cov_fail_under(tmp_path: Path) -> None:
    from sprout.claims import _resolve_pytest_cov_fail_under

    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        '[tool.pytest.ini_options]\naddopts = "--cov=x --cov-fail-under=77 -q"\n',
        encoding="utf-8",
    )
    assert _resolve_pytest_cov_fail_under(toml) == "77"


def test_resolve_pytest_cov_fail_under_missing_file(tmp_path: Path) -> None:
    from sprout.claims import _resolve_pytest_cov_fail_under

    with pytest.raises(FileNotFoundError):
        _resolve_pytest_cov_fail_under(tmp_path / "nope.toml")


def test_resolve_pytest_cov_fail_under_missing_flag(tmp_path: Path) -> None:
    from sprout.claims import _resolve_pytest_cov_fail_under

    toml = tmp_path / "pyproject.toml"
    toml.write_text('[tool.pytest.ini_options]\naddopts = "-q"\n', encoding="utf-8")
    with pytest.raises(ClaimsError, match="no --cov-fail-under"):
        _resolve_pytest_cov_fail_under(toml)


def test_resolve_eval_report_suite_names_and_count(tmp_path: Path) -> None:
    from sprout.claims import _resolve_eval_report_suite_count, _resolve_eval_report_suite_names

    report = tmp_path / "eval-report.json"
    report.write_text(
        '{"suite_results": [{"suite": "a"}, {"suite": "b"}, {"suite": "c"}]}',
        encoding="utf-8",
    )
    assert _resolve_eval_report_suite_names(report) == "a, b, c"
    assert _resolve_eval_report_suite_count(report) == "3"


def test_load_claims_missing_registry(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        check(claims_path=tmp_path / "nope.yaml")


def test_load_claims_malformed_registry(tmp_path: Path) -> None:
    bad = tmp_path / "claims.yaml"
    bad.write_text("not_a_claims_key: []\n", encoding="utf-8")
    with pytest.raises(ClaimsError):
        check(claims_path=bad)


def test_load_claims_entry_missing_key(tmp_path: Path) -> None:
    bad = tmp_path / "claims.yaml"
    bad.write_text(yaml.safe_dump({"claims": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(ClaimsError):
        check(claims_path=bad)


# --- CLI ---------------------------------------------------------------------------------


def test_claims_check_cli_passes() -> None:
    ok = runner.invoke(app, ["claims-check"])
    assert ok.exit_code == 0
    assert "reconciled" in ok.stdout


def test_claims_check_cli_missing_file(tmp_path: Path) -> None:
    missing = runner.invoke(app, ["claims-check", str(tmp_path / "nope.yaml")])
    assert missing.exit_code == 2


def test_claims_check_cli_reports_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_fixture(tmp_path, abstain="0.99")
    fail = runner.invoke(app, ["claims-check"])
    assert fail.exit_code == 1
