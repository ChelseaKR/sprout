"""EXP-13: the eval score-history ledger — append, load, and the consecutive-decline drift
rule that catches a slow multi-release bleed a single pinned-baseline diff cannot see."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sprout.eval.history import (
    HistoryEntry,
    append_history_entry,
    check_drift,
    history_entry_from_result,
    load_history,
)
from sprout.eval.report import render_html, render_markdown, render_trend_markdown
from sprout.eval.runner import RunFingerprint, RunResult
from sprout.eval.suite import MetricDefinition, SuiteResult, Verdict

FP = RunFingerprint(
    harness_version="0.1.0",
    seed=1729,
    dataset_hash="sha256:" + "a" * 64,
    judge_config_hash="sha256:" + "b" * 64,
    target="deterministic:extractive",
    suite_names=("safety", "groundedness"),
)


def _suite_result(name: str, score: float, *, threshold: float = 0.9) -> SuiteResult:
    verdict = Verdict.PASS if score >= threshold else Verdict.FAIL
    return SuiteResult(
        suite=name,
        metric=MetricDefinition(name=name, definition="d", threshold=threshold),
        score=score,
        verdict=verdict,
        n_items=20,
        ci_low=max(0.0, score - 0.05),
        ci_high=min(1.0, score + 0.05),
        underpowered=False,
        dataset_version="sha256:" + "c" * 64,
        judge_method="deterministic",
        judge_config_hash="sha256:" + "b" * 64,
    )


def _result(*, safety: float, groundedness: float = 1.0) -> RunResult:
    suites = (_suite_result("safety", safety), _suite_result("groundedness", groundedness))
    overall = Verdict.PASS if all(s.passed for s in suites) else Verdict.FAIL
    return RunResult(fingerprint=FP, overall_verdict=overall, suite_results=suites)


# --- append / load round trip -----------------------------------------------------
def test_append_and_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "eval-history.jsonl"
    entry = history_entry_from_result(_result(safety=0.97), release="v1.0.0")
    append_history_entry(path, entry)
    loaded = load_history(path)
    assert loaded == [entry]
    safety_score = loaded[0].score_for("safety")
    assert safety_score is not None
    assert safety_score.score == pytest.approx(0.97)
    assert loaded[0].score_for("nonexistent") is None


def test_load_history_missing_file_is_empty_ledger(tmp_path: Path) -> None:
    assert load_history(tmp_path / "does-not-exist.jsonl") == []


def test_append_is_additive_never_rewrites_prior_entries(tmp_path: Path) -> None:
    path = tmp_path / "eval-history.jsonl"
    e1 = history_entry_from_result(_result(safety=0.97), release="v1.0.0")
    e2 = history_entry_from_result(_result(safety=0.96), release="v1.1.0")
    append_history_entry(path, e1)
    append_history_entry(path, e2)
    loaded = load_history(path)
    assert [e.release for e in loaded] == ["v1.0.0", "v1.1.0"]


def test_history_entry_is_frozen_and_serialisable(tmp_path: Path) -> None:
    entry = history_entry_from_result(_result(safety=0.97), release="v1.0.0")
    with pytest.raises(ValidationError):
        entry.release = "mutated"
    round_tripped = HistoryEntry.model_validate_json(entry.model_dump_json())
    assert round_tripped == entry


# --- the drift rule ----------------------------------------------------------------
def test_drift_fires_on_k_consecutive_declines_even_inside_tolerance() -> None:
    # Each step drops 0.005 — comfortably inside a 0.05 baseline-diff tolerance — but it is
    # three declines in a row, which is exactly what the ledger is for.
    scores = [0.970, 0.965, 0.960, 0.955]
    history = [
        history_entry_from_result(_result(safety=s), release=f"v1.{i}.0")
        for i, s in enumerate(scores)
    ]
    issues = check_drift(history, k=3)
    assert any("safety" in i and "declined for 3 consecutive releases" in i for i in issues)


def test_drift_does_not_fire_when_scores_flat_or_improving() -> None:
    scores = [0.90, 0.95, 0.95, 0.97]
    history = [
        history_entry_from_result(_result(safety=s), release=f"v1.{i}.0")
        for i, s in enumerate(scores)
    ]
    assert check_drift(history, k=3) == []


def test_drift_does_not_fire_when_one_uptick_breaks_the_streak() -> None:
    scores = [0.97, 0.96, 0.965, 0.955]  # decline, uptick, decline — never k in a row
    history = [
        history_entry_from_result(_result(safety=s), release=f"v1.{i}.0")
        for i, s in enumerate(scores)
    ]
    assert check_drift(history, k=3) == []


def test_drift_requires_at_least_k_plus_1_releases() -> None:
    scores = [0.97, 0.96, 0.95]  # two declines only — k=3 needs 4 data points
    history = [
        history_entry_from_result(_result(safety=s), release=f"v1.{i}.0")
        for i, s in enumerate(scores)
    ]
    assert check_drift(history, k=3) == []


def test_drift_respects_lower_is_better_direction() -> None:
    def lower_is_better_result(score: float) -> RunResult:
        suite = SuiteResult(
            suite="calibration",
            metric=MetricDefinition(
                name="calibration", definition="d", threshold=0.15, higher_is_better=False
            ),
            score=score,
            verdict=Verdict.PASS if score <= 0.15 else Verdict.FAIL,
            n_items=20,
            ci_low=0.0,
            ci_high=1.0,
            underpowered=False,
            dataset_version="sha256:" + "c" * 64,
            judge_method="deterministic",
            judge_config_hash="sha256:" + "b" * 64,
        )
        return RunResult(fingerprint=FP, overall_verdict=Verdict.PASS, suite_results=(suite,))

    # A *rising* calibration error is the decline for a lower-is-better metric.
    scores = [0.08, 0.09, 0.10, 0.11]
    history = [
        history_entry_from_result(lower_is_better_result(s), release=f"v1.{i}.0")
        for i, s in enumerate(scores)
    ]
    issues = check_drift(history, k=3)
    assert any("calibration" in i for i in issues)


def test_drift_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError, match="k must be"):
        check_drift([], k=0)


def test_drift_skips_a_suite_missing_from_part_of_the_window() -> None:
    # `groundedness` is absent from the oldest release in the window — only 3 of the 4 points
    # needed for a k=3 trajectory — so it must be skipped without error, while `safety` (present
    # in every release, declining every step) still fires.
    entries = [
        history_entry_from_result(_result(safety=s), release=f"v1.{i}.0")
        for i, s in enumerate([0.97, 0.96, 0.95, 0.94])
    ]
    entries[0] = entries[0].model_copy(
        update={"suites": tuple(s for s in entries[0].suites if s.suite != "groundedness")}
    )
    issues = check_drift(entries, k=3)
    assert any("safety" in i for i in issues)
    assert not any("groundedness" in i for i in issues)


# --- trend rendering ----------------------------------------------------------------
def test_render_trend_markdown_empty_history() -> None:
    assert "No release history" in render_trend_markdown([])


def test_render_trend_markdown_has_sparkline_and_data_table() -> None:
    history = [
        history_entry_from_result(_result(safety=s), release=f"v1.{i}.0")
        for i, s in enumerate([0.90, 0.95, 0.97])
    ]
    md = render_trend_markdown(history)
    assert "`safety`" in md
    assert "Trend data table" in md
    assert "v1.0.0" in md and "v1.2.0" in md


def test_render_markdown_includes_trend_section_only_when_history_given() -> None:
    result = _result(safety=0.97)
    bare = render_markdown(result)
    assert "Score trend across releases" not in bare
    history = [history_entry_from_result(result, release="v1.0.0")]
    with_trend = render_markdown(result, history)
    assert "Score trend across releases" in with_trend


def test_render_html_with_history_is_accessible_and_has_data_table_equivalent() -> None:
    result = _result(safety=0.97)
    history = [
        history_entry_from_result(_result(safety=s), release=f"v1.{i}.0")
        for i, s in enumerate([0.90, 0.95, 0.97])
    ]
    doc = render_html(result, history)  # raises AccessibilityError on failure
    assert "score-trend" in doc
    assert "Trend data table" in doc
    assert 'aria-hidden="true"' in doc  # the sparkline is decorative; the table is the source


def test_render_html_without_history_is_unaffected() -> None:
    result = _result(safety=0.97)
    doc = render_html(result)
    assert "Score trend across releases" not in doc
