"""What an eval-report comparison may and may not claim.

The load-bearing case is the one that looks like good news: a case that was failing and is
no longer in the later report's failures. That is a fix *only* if both runs held the same
cases, because a report records nothing about a case that passed — so a removed case and a
fixed case are the same absence. These tests pin that a changed ``dataset_hash`` turns
every such disappearance into ``not_comparable`` rather than a green tick.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sprout.cli import app
from sprout.eval.diffing import (
    CaseChange,
    Comparability,
    SuiteChange,
    diff_reports,
    exit_code_for,
    load_report,
    render_markdown,
)
from sprout.eval.runner import RunFingerprint, RunResult
from sprout.eval.suite import ExampleOutcome, MetricDefinition, SegmentScore, SuiteResult, Verdict

runner = CliRunner()

_METRIC = MetricDefinition(name="pass-rate", definition="Cases passed.", threshold=0.9)


def _fingerprint(**overrides: object) -> RunFingerprint:
    base: dict[str, object] = {
        "harness_version": "0.1.0",
        "seed": 1729,
        "dataset_hash": "a" * 64,
        "judge_config_hash": "b" * 64,
        "target": "deterministic:extractive",
        "suite_names": ("safety",),
    }
    return RunFingerprint(**{**base, **overrides})  # type: ignore[arg-type]


def _outcome(
    item_id: str, *, score: float = 0.0, detail: str = "missing citation"
) -> ExampleOutcome:
    return ExampleOutcome(item_id=item_id, passed=False, score=score, detail=detail)


def _suite(
    name: str = "safety",
    *,
    score: float = 0.95,
    verdict: Verdict = Verdict.PASS,
    n_items: int = 20,
    ci: tuple[float, float] = (0.9, 0.99),
    failures: tuple[ExampleOutcome, ...] = (),
    segments: tuple[SegmentScore, ...] = (),
) -> SuiteResult:
    return SuiteResult(
        suite=name,
        metric=_METRIC,
        score=score,
        verdict=verdict,
        n_items=n_items,
        ci_low=ci[0],
        ci_high=ci[1],
        underpowered=False,
        dataset_version="sha256:aaaaaaaaaaaa",
        judge_method="deterministic-lexical",
        judge_config_hash="b" * 64,
        segments=segments,
        failing_examples=failures,
    )


def _report(
    suites: tuple[SuiteResult, ...],
    *,
    verdict: Verdict = Verdict.PASS,
    **fingerprint: object,
) -> RunResult:
    return RunResult(
        fingerprint=_fingerprint(**fingerprint),
        overall_verdict=verdict,
        suite_results=suites,
    )


# --- absence is not a fix -------------------------------------------------------------


def test_a_case_that_stops_failing_is_a_fix_when_the_dataset_did_not_move() -> None:
    diff = diff_reports(
        _report((_suite(failures=(_outcome("safety-004"),)),)),
        _report((_suite(),)),
    )

    (case,) = diff.suites[0].cases
    assert case.change is CaseChange.FIXED
    assert not diff.regressions


def test_a_case_that_stops_failing_is_not_a_fix_when_the_dataset_moved() -> None:
    """A report records only failures, so a removed case and a fixed case look the same."""
    diff = diff_reports(
        _report((_suite(failures=(_outcome("safety-004"),)),)),
        _report((_suite(),), dataset_hash="c" * 64),
    )

    (case,) = diff.suites[0].cases
    assert case.change is CaseChange.NOT_COMPARABLE
    assert "removed" in case.reason
    rendered = render_markdown(diff)
    assert "| `safety-004` | not comparable |" in rendered
    assert "| fixed |" not in rendered


def test_a_case_that_stops_failing_is_not_a_fix_when_the_suite_did_not_run() -> None:
    diff = diff_reports(
        _report((_suite(failures=(_outcome("safety-004"),)),)),
        _report((_suite("refusal"),)),
    )

    safety = next(suite for suite in diff.suites if suite.suite == "safety")
    assert safety.change is SuiteChange.ONLY_BEFORE
    assert safety.cases[0].change is CaseChange.NOT_COMPARABLE
    assert "did not run this suite" in safety.cases[0].reason


def test_a_new_failure_is_a_regression_even_when_the_dataset_moved() -> None:
    """Only the *absence* was ambiguous; the later report records this one failing."""
    diff = diff_reports(
        _report((_suite(),)),
        _report((_suite(failures=(_outcome("safety-009"),)),), dataset_hash="c" * 64),
    )

    (case,) = diff.suites[0].cases
    assert case.change is CaseChange.BROKEN
    assert diff.regressions == (case,)


# --- numbers are refused rather than misreported --------------------------------------


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"dataset_hash": "c" * 64}, Comparability.DATASET_CHANGED),
        ({"judge_config_hash": "d" * 64}, Comparability.JUDGE_CHANGED),
        ({"target": "bedrock:sonnet"}, Comparability.TARGET_CHANGED),
        ({"harness_version": "0.2.0"}, Comparability.HARNESS_CHANGED),
    ],
)
def test_a_changed_fingerprint_field_refuses_the_numeric_delta_and_names_itself(
    override: dict[str, object], expected: Comparability
) -> None:
    diff = diff_reports(
        _report((_suite(score=0.95),)),
        _report((_suite(score=0.80),), **override),  # type: ignore[arg-type]
    )

    assert diff.blocking == (expected,)
    assert not diff.numbers_comparable
    suite = diff.suites[0]
    assert suite.score_delta is None
    assert suite.intervals_overlap is None
    # Both scores are still shown; refusing to subtract is not refusing to report.
    assert (suite.before_score, suite.after_score) == (0.95, 0.80)
    rendered = render_markdown(diff)
    assert "Numeric deltas are refused" in rendered
    assert "0.95" in rendered and "0.8" in rendered


def test_flips_are_still_listed_when_the_numbers_are_refused() -> None:
    diff = diff_reports(
        _report((_suite(),)),
        _report((_suite(failures=(_outcome("safety-009"),)),), judge_config_hash="d" * 64),
    )

    assert not diff.numbers_comparable
    assert diff.regressions[0].item_id == "safety-009"


def test_comparable_runs_get_a_delta_and_an_interval_overlap_verdict() -> None:
    overlapping = diff_reports(
        _report((_suite(score=0.95, ci=(0.90, 0.99)),)),
        _report((_suite(score=0.93, ci=(0.88, 0.97)),)),
    ).suites[0]
    disjoint = diff_reports(
        _report((_suite(score=0.95, ci=(0.90, 0.99)),)),
        _report((_suite(score=0.50, ci=(0.40, 0.60)),)),
    ).suites[0]

    assert overlapping.score_delta == pytest.approx(-0.02)
    assert overlapping.intervals_overlap is True
    assert disjoint.intervals_overlap is False


# --- what changed, and why ------------------------------------------------------------


def test_a_case_failing_in_both_reports_names_whether_the_reason_moved() -> None:
    unchanged = diff_reports(
        _report((_suite(failures=(_outcome("safety-004", detail="missing citation"),)),)),
        _report((_suite(failures=(_outcome("safety-004", detail="missing citation"),)),)),
    ).suites[0]
    moved = diff_reports(
        _report((_suite(failures=(_outcome("safety-004", detail="missing citation"),)),)),
        _report((_suite(failures=(_outcome("safety-004", detail="certification string"),)),)),
    ).suites[0]

    assert unchanged.cases[0].change is CaseChange.STILL_FAILING
    assert unchanged.moved_cases == ()
    assert moved.cases[0].change is CaseChange.STILL_FAILING_DIFFERENT_REASON
    assert moved.cases[0].after_detail == "certification string"
    assert "certification string" in render_markdown(
        diff_reports(
            _report((_suite(failures=(_outcome("safety-004", detail="missing citation"),)),)),
            _report((_suite(failures=(_outcome("safety-004", detail="certification string"),)),)),
        )
    )


def test_a_confidence_bin_that_moved_is_reported_as_a_segment_delta() -> None:
    """For `calibration` these bins are the coverage-risk curve, so this is its delta."""
    before = (SegmentScore(label="[0.6,0.7)", score=0.73, n=26, verdict=Verdict.PASS),)
    after = (SegmentScore(label="[0.6,0.7)", score=0.51, n=26, verdict=Verdict.FAIL),)

    suite = diff_reports(
        _report((_suite("calibration", segments=before),)),
        _report((_suite("calibration", segments=after),)),
    ).suites[0]

    assert len(suite.segments) == 1
    assert (suite.segments[0].before_score, suite.segments[0].after_score) == (0.73, 0.51)
    assert suite.segments[0].after_verdict is Verdict.FAIL


def test_two_identical_reports_say_nothing_moved_rather_than_printing_nothing() -> None:
    report = _report((_suite(failures=(_outcome("safety-004"),)),))

    rendered = render_markdown(diff_reports(report, report))

    assert "No suite and no case moved between these two reports." in rendered


def test_a_suite_verdict_leaving_pass_is_a_regression_even_with_no_new_failing_case() -> None:
    diff = diff_reports(
        _report((_suite(score=0.95, verdict=Verdict.PASS),)),
        _report((_suite(score=0.80, verdict=Verdict.FAIL),)),
    )

    assert diff.regressed_suites
    assert exit_code_for(diff, fail_on_regression=True) == 1
    assert exit_code_for(diff, fail_on_regression=False) == 0


# --- the command ----------------------------------------------------------------------


def _write(path: Path, report: RunResult) -> Path:
    path.write_text(report.model_dump_json(), encoding="utf-8")
    return path


def test_the_command_only_fails_when_asked_to_and_something_regressed(tmp_path: Path) -> None:
    clean = _write(tmp_path / "before.json", _report((_suite(),)))
    broken = _write(tmp_path / "after.json", _report((_suite(failures=(_outcome("safety-009"),)),)))

    assert runner.invoke(app, ["eval-diff", str(clean), str(broken)]).exit_code == 0
    assert (
        runner.invoke(app, ["eval-diff", str(clean), str(broken), "--fail-on-regression"]).exit_code
        == 1
    )
    assert (
        runner.invoke(app, ["eval-diff", str(broken), str(clean), "--fail-on-regression"]).exit_code
        == 0
    )


def test_the_command_exits_two_on_something_that_is_not_an_eval_report(tmp_path: Path) -> None:
    good = _write(tmp_path / "good.json", _report((_suite(),)))
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")

    result = runner.invoke(app, ["eval-diff", str(good), str(bad)])

    assert result.exit_code == 2
    assert "cannot read an eval report" in result.output


def test_the_json_output_is_machine_readable_and_names_the_change(tmp_path: Path) -> None:
    before = _write(tmp_path / "before.json", _report((_suite(),)))
    after = _write(tmp_path / "after.json", _report((_suite(failures=(_outcome("safety-009"),)),)))

    result = runner.invoke(app, ["eval-diff", str(before), str(after), "--json"])

    payload = json.loads(result.output)
    assert payload["suites"][0]["cases"][0]["change"] == "broken"
    assert payload["blocking"] == []


def test_the_committed_baseline_and_report_are_readable_by_this_verb() -> None:
    """The two files a maintainer will actually pass it, as committed."""
    root = Path(__file__).resolve().parents[1]
    baseline = load_report((root / "docs/audits/eval-baseline.json").read_text(encoding="utf-8"))
    report = load_report((root / "docs/audits/eval-report.json").read_text(encoding="utf-8"))

    diff = diff_reports(baseline, report)

    assert diff.suites, "the committed reports produced no suites; this check would be vacuous"
    assert all(suite.change is SuiteChange.PRESENT_IN_BOTH for suite in diff.suites)
