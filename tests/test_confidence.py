"""Selective-prediction coverage/risk curve (RESEARCH-ROADMAP E4).

Kept in its own file rather than the guarded ``tests/test_rag.py`` so this addition does
not require touching a CODEOWNERS-guarded test file; it exercises only the new,
purely-additive ``coverage_risk_curve`` in ``sprout.confidence``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sprout.confidence import DEFAULT_COVERAGE_THRESHOLDS, CoveragePoint, coverage_risk_curve


def test_empty_pairs_yield_zero_coverage_and_no_risk_to_report() -> None:
    """Zero coverage means no error rate exists, which is not the same as zero risk."""
    curve = coverage_risk_curve([])
    assert len(curve) == len(set(DEFAULT_COVERAGE_THRESHOLDS))
    assert all(p.coverage == 0.0 for p in curve)
    assert all(p.risk is None for p in curve)
    assert all(p.n_covered == 0 for p in curve)


def test_threshold_zero_covers_everything() -> None:
    pairs = [(0.9, True), (0.1, False), (0.5, True), (0.0, False)]
    curve = coverage_risk_curve(pairs, thresholds=(0.0,))
    assert len(curve) == 1
    assert curve[0].coverage == 1.0
    assert curve[0].n_covered == len(pairs)
    # 2 of 4 wrong among the covered set.
    assert curve[0].risk == 0.5


def test_threshold_above_all_confidences_reports_no_risk_rather_than_zero() -> None:
    pairs = [(0.2, True), (0.3, False)]
    curve = coverage_risk_curve(pairs, thresholds=(0.99,))
    assert curve[0].coverage == 0.0
    assert curve[0].n_covered == 0
    # An error rate over an empty set is undefined. Publishing 0.0 here would plot as
    # "abstain from everything and be perfectly safe", a claim no data supports.
    assert curve[0].risk is None


def test_coverage_is_non_increasing_in_threshold() -> None:
    pairs = [(0.9, True), (0.7, True), (0.5, False), (0.3, True), (0.1, False)]
    curve = coverage_risk_curve(pairs, thresholds=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0))
    coverages = [p.coverage for p in curve]
    assert coverages == sorted(coverages, reverse=True)


def test_perfectly_calibrated_confidence_gives_monotonically_non_increasing_risk() -> None:
    # Confidence exactly tracks correctness: high-confidence cases are always right,
    # low-confidence cases are always wrong. Raising the bar can only help or be neutral.
    pairs = [(0.9, True), (0.8, True), (0.6, False), (0.4, False), (0.2, False)]
    curve = coverage_risk_curve(pairs, thresholds=(0.0, 0.3, 0.5, 0.7, 0.9))
    covered = [p for p in curve if p.n_covered]
    risks = [p.risk for p in covered]
    assert all(r is not None for r in risks), "a covered point must have a measured risk"
    assert risks == sorted(risks, reverse=True)  # type: ignore[type-var]
    # At the highest threshold only the two always-correct cases remain -> zero risk.
    assert covered[-1].risk == 0.0


def test_thresholds_are_deduplicated_and_sorted() -> None:
    curve = coverage_risk_curve([(0.5, True)], thresholds=(0.5, 0.1, 0.5, 0.1))
    assert [p.threshold for p in curve] == [0.1, 0.5]


def test_coverage_point_is_frozen() -> None:
    point = CoveragePoint(threshold=0.5, coverage=1.0, risk=0.0, n_covered=1)
    with pytest.raises(ValidationError):
        point.threshold = 0.9  # frozen model rejects assignment
