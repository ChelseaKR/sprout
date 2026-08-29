"""Tests for the `make verify` vs. `ci-gate` invocation-diff (`sprout.ci_parity`).

Covers both the unit-level normalization/diff logic (synthetic fixtures, so a regression here
fails independent of the real repo files) and, critically, the real repo: `.github/workflows/ci.yml`
and `Makefile` are diffed as they exist on disk, the same way `make ci-parity-check` and the CI
`ci-parity` job invoke it — so if this drifts, this test (not just the CI job) turns red.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sprout.ci_parity import (
    ParityReport,
    _normalize,
    check_parity,
    diff_group,
    format_reports,
)
from sprout.cli import app

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parent.parent

_MAKEFILE_FIXTURE = """\
PY := uv run
CONFIG ?= config/sprout.yaml

.PHONY: lint test

lint: ## Lint
\t$(PY) ruff check src tests

test: ## Test
\t$(PY) pytest

ingest: ## Ingest
\t$(PY) sprout ingest --config $(CONFIG)

security: ## Security
\t$(PY) pip-audit
\t@command -v gitleaks >/dev/null 2>&1 && gitleaks detect --no-banner --redact || \\
\t  ( echo "not installed" )
"""

_CI_YAML_FIXTURE = """\
jobs:
  test:
    steps:
      - uses: actions/checkout@v7
      - run: uv sync --locked
      - name: lint
        run: uv run ruff check src tests
      - name: test
        run: uv run pytest
"""


def test_normalize_strips_leading_at_and_collapses_whitespace() -> None:
    assert _normalize("  @echo   hi   ") == "echo hi"


def test_normalize_substitutes_make_vars_and_drops_default_config_flag() -> None:
    make_vars = {"PY": "uv run", "CONFIG": "config/sprout.yaml"}
    normalized = _normalize("$(PY) sprout ingest --config $(CONFIG)", make_vars)
    assert normalized == "uv run sprout ingest"


def test_diff_group_matching_sets_is_ok() -> None:
    report = diff_group("g", {"a", "b"}, {"a", "b"})
    assert report.ok
    assert report.ci_only == ()
    assert report.make_only == ()


def test_diff_group_reports_ci_only_drift() -> None:
    report = diff_group("g", {"a", "b", "new-ci-command"}, {"a", "b"})
    assert not report.ok
    assert report.ci_only == ("new-ci-command",)
    assert report.make_only == ()


def test_diff_group_reports_make_only_drift() -> None:
    report = diff_group("g", {"a"}, {"a", "stray-local-command"})
    assert not report.ok
    assert report.make_only == ("stray-local-command",)


def test_diff_group_ignores_allowlisted_ci_only_command() -> None:
    # `uv build` (CQ-10 packaging smoke build) is documented as CI-only.
    report = diff_group("test", {"uv run pytest", "uv build"}, {"uv run pytest"})
    assert report.ok


def test_diff_group_ignores_allowlisted_make_only_prefix() -> None:
    # gitleaks runs as a GitHub Action in CI, so it never appears as a `run:` command.
    report = diff_group(
        "security",
        {"uv run pip-audit"},
        {
            "uv run pip-audit",
            'if command -v gitleaks >/dev/null 2>&1; then gitleaks detect; else echo "no"; fi',
        },
    )
    assert report.ok


def test_the_old_gitleaks_and_or_form_is_no_longer_allowlisted() -> None:
    """The allowlist says "gitleaks is CI-side only", not "any shell shape is fine".

    `command -v gitleaks && gitleaks detect || <fallback>` routed a real finding into the
    fallback branch and exited 0 (see tests/test_security_gate.py). Waving it through here
    would let it come back without the parity gate noticing.
    """
    report = diff_group(
        "security",
        {"uv run pip-audit"},
        {"uv run pip-audit", "command -v gitleaks >/dev/null 2>&1 && gitleaks detect || echo no"},
    )
    assert not report.ok


def test_check_parity_on_synthetic_fixtures_matches(tmp_path: Path) -> None:
    ci_path = tmp_path / "ci.yml"
    ci_path.write_text(_CI_YAML_FIXTURE, encoding="utf-8")
    make_path = tmp_path / "Makefile"
    make_path.write_text(_MAKEFILE_FIXTURE, encoding="utf-8")

    # Only the "test" job/target pair is present in this fixture; the others resolve to empty
    # sets on both sides, which is trivially equal (ok).
    reports = check_parity(ci_path, make_path)
    by_group = {r.group: r for r in reports}
    assert by_group["test"].ok, by_group["test"]


def test_check_parity_catches_injected_ci_side_drift(tmp_path: Path) -> None:
    ci_path = tmp_path / "ci.yml"
    ci_path.write_text(
        _CI_YAML_FIXTURE.replace(
            "run: uv run pytest",
            "run: uv run pytest\n      - name: extra\n        run: uv run new-tool",
        ),
        encoding="utf-8",
    )
    make_path = tmp_path / "Makefile"
    make_path.write_text(_MAKEFILE_FIXTURE, encoding="utf-8")

    reports = check_parity(ci_path, make_path)
    by_group = {r.group: r for r in reports}
    assert not by_group["test"].ok
    assert "uv run new-tool" in by_group["test"].ci_only


def test_format_reports_renders_ok_and_drift() -> None:
    ok = ParityReport(group="clean")
    drift = ParityReport(group="dirty", ci_only=("x",), make_only=("y",))
    text = format_reports([ok, drift])
    assert "OK    clean" in text
    assert "DRIFT dirty" in text
    assert "x" in text
    assert "y" in text


def test_cli_default_config_matches_makefile_default() -> None:
    """`_normalize` drops `--config <default>` as a no-op flag; that's only sound if the CLI's
    own default equals the Makefile's `CONFIG ?=` default. Guard the assumption directly."""
    from sprout.ci_parity import _resolve_make_vars
    from sprout.cli import _DEFAULT_CONFIG

    make_vars = _resolve_make_vars((REPO_ROOT / "Makefile").read_text(encoding="utf-8"))
    assert make_vars["CONFIG"] == _DEFAULT_CONFIG


def test_real_repo_make_verify_matches_ci_gate() -> None:
    """The actual point of this module: the repo's own ci.yml and Makefile agree right now."""
    reports = check_parity(REPO_ROOT / ".github" / "workflows" / "ci.yml", REPO_ROOT / "Makefile")
    assert reports, "expected at least one comparison group"
    failures = [r for r in reports if not r.ok]
    assert not failures, format_reports(reports)
    assert "smoke" in {r.group for r in reports}


def test_cli_ci_parity_check_passes_on_real_repo() -> None:
    result = runner.invoke(app, ["ci-parity-check"])
    assert result.exit_code == 0, result.output
    assert "DRIFT" not in result.output


def test_cli_ci_parity_check_fails_on_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ci-parity-check", "--workflow", str(tmp_path / "nope.yml")])
    assert result.exit_code != 0
