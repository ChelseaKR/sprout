"""Selective-prediction coverage/risk curve (RESEARCH-ROADMAP E4).

Kept in its own file rather than the guarded ``tests/test_rag.py`` so this addition does
not require touching a CODEOWNERS-guarded test file; it exercises only the new,
purely-additive ``coverage_risk_curve`` in ``sprout.confidence``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sprout.confidence import DEFAULT_COVERAGE_THRESHOLDS, CoveragePoint, coverage_risk_curve


def test_empty_pairs_yield_zero_coverage_and_zero_risk() -> None:
    curve = coverage_risk_curve([])
    assert len(curve) == len(set(DEFAULT_COVERAGE_THRESHOLDS))
    assert all(p.coverage == 0.0 for p in curve)
    assert all(p.risk == 0.0 for p in curve)
    assert all(p.n_covered == 0 for p in curve)


def test_threshold_zero_covers_everything() -> None:
    pairs = [(0.9, True), (0.1, False), (0.5, True), (0.0, False)]
    curve = coverage_risk_curve(pairs, thresholds=(0.0,))
    assert len(curve) == 1
    assert curve[0].coverage == 1.0
    assert curve[0].n_covered == len(pairs)
    # 2 of 4 wrong among the covered set.
    assert curve[0].risk == 0.5


def test_threshold_above_all_confidences_covers_nothing() -> None:
    pairs = [(0.2, True), (0.3, False)]
    curve = coverage_risk_curve(pairs, thresholds=(0.99,))
    assert curve[0].coverage == 0.0
    assert curve[0].n_covered == 0
    # No error to report when nothing is covered -- not the same claim as "zero risk."
    assert curve[0].risk == 0.0


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
    assert risks == sorted(risks, reverse=True)
    # At the highest threshold only the two always-correct cases remain -> zero risk.
    assert covered[-1].risk == 0.0


def test_thresholds_are_deduplicated_and_sorted() -> None:
    curve = coverage_risk_curve([(0.5, True)], thresholds=(0.5, 0.1, 0.5, 0.1))
    assert [p.threshold for p in curve] == [0.1, 0.5]


def test_coverage_point_is_frozen() -> None:
    point = CoveragePoint(threshold=0.5, coverage=1.0, risk=0.0, n_covered=1)
    with pytest.raises(ValidationError):
        point.threshold = 0.9  # frozen model rejects assignment
