"""Unit tests for the eval core: dataset, stats, judge, calibration."""

from __future__ import annotations

import ast
import inspect
import math
from pathlib import Path

import pytest

from sprout.eval import stats
from sprout.eval.calibration import (
    JudgeProbe,
    calibrate,
    cohens_kappa,
    is_stale,
)
from sprout.eval.dataset import (
    Dataset,
    DatasetError,
    DatasetItem,
    Provenance,
    load_suite_dir,
    write_sidecar,
)
from sprout.eval.judge import DeterministicJudge, build_judge
from sprout.eval.stats import (
    Z_95,
    is_underpowered,
    wilson_difference_interval,
    wilson_interval,
)

PROV = {"source": "synthetic", "license": "CC0-1.0", "added": "2026-06-22"}


def _yaml(cases: str) -> str:
    return "cases:\n" + cases


# --- dataset ---------------------------------------------------------------------
def test_dataset_from_items_hash_is_order_independent() -> None:
    a = DatasetItem(id="a", question="q1", provenance=Provenance(**PROV))
    b = DatasetItem(id="b", question="q2", provenance=Provenance(**PROV))
    assert Dataset.from_items([a, b]).content_hash == Dataset.from_items([b, a]).content_hash


def test_dataset_rejects_duplicates_and_empty() -> None:
    a = DatasetItem(id="a", question="q", provenance=Provenance(**PROV))
    with pytest.raises(ValueError, match="duplicate"):
        Dataset.from_items([a, a])
    with pytest.raises(ValueError, match="empty"):
        Dataset.from_items([])


def test_load_suite_dir_and_sidecar(tmp_path: Path) -> None:
    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "g.yaml").write_text(
        _yaml(
            '  - id: g1\n    question: "why yellow?"\n'
            '    provenance: {source: synthetic, license: CC0-1.0, added: "2026-06-22"}\n'
        ),
        encoding="utf-8",
    )
    ds = load_suite_dir(suites, verify_hash=False)
    assert len(ds.items) == 1

    sidecar = tmp_path / "suites.sha256"
    write_sidecar(ds, sidecar)
    # Matching sidecar loads fine.
    assert load_suite_dir(suites).items[0].id == "g1"
    # Tampered sidecar fails closed.
    sidecar.write_text("deadbeef\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="hash mismatch"):
        load_suite_dir(suites)


def test_load_cases_invalid_field_fails_closed(tmp_path: Path) -> None:
    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "bad.yaml").write_text(
        _yaml(
            "  - id: x\n    question: q\n    bogus_field: 1\n    provenance: " + str(PROV) + "\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(DatasetError, match="invalid case"):
        load_suite_dir(suites, verify_hash=False)


def test_load_suite_dir_no_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DatasetError, match="no suite"):
        load_suite_dir(empty)


def test_coerce_top_level_list(tmp_path: Path) -> None:
    suites = tmp_path / "s"
    suites.mkdir()
    (suites / "l.yaml").write_text(
        "- id: a\n  question: q\n"
        '  provenance: {source: s, license: CC0-1.0, added: "2026-06-22"}\n',
        encoding="utf-8",
    )
    assert len(load_suite_dir(suites, verify_hash=False).items) == 1


# --- stats -----------------------------------------------------------------------
def test_wilson_interval_bounds() -> None:
    low, high = wilson_interval(8, 10)
    assert 0.0 <= low <= 0.8 <= high <= 1.0
    assert wilson_interval(0, 0) == (0.0, 0.0)
    full_low, full_high = wilson_interval(10, 10)
    assert full_high == pytest.approx(1.0)
    assert full_low < 1.0  # the lower bound stays below 1.0 even for a perfect rate


def test_is_underpowered() -> None:
    assert is_underpowered(29)
    assert not is_underpowered(30)


def test_wilson_difference_interval_brackets_the_difference() -> None:
    low, high = wilson_difference_interval(90, 100, 80, 100)
    assert low < 0.10 < high
    assert low >= -1.0 and high <= 1.0


def test_wilson_difference_interval_widens_as_a_slice_thins() -> None:
    """The comparison is limited by its smallest slice, and the interval must say so."""
    wide_low, wide_high = wilson_difference_interval(9, 10, 8, 10)
    narrow_low, narrow_high = wilson_difference_interval(900, 1000, 800, 1000)
    assert (wide_high - wide_low) > (narrow_high - narrow_low)


def test_wilson_difference_interval_is_vacuous_on_an_empty_slice() -> None:
    """A difference against nothing is not 0.0 — absence must not render as agreement."""
    assert wilson_difference_interval(5, 5, 0, 0) == (-1.0, 1.0)
    assert wilson_difference_interval(0, 0, 5, 5) == (-1.0, 1.0)


def test_wilson_difference_interval_is_antisymmetric() -> None:
    low, high = wilson_difference_interval(9, 12, 4, 11)
    flipped_low, flipped_high = wilson_difference_interval(4, 11, 9, 12)
    assert flipped_low == pytest.approx(-high)
    assert flipped_high == pytest.approx(-low)


# --- judge -----------------------------------------------------------------------
def test_deterministic_judge_entails_and_negation() -> None:
    j = DeterministicJudge()
    assert j.entails(
        "Yellowing leaves indicate overwatering", ["Yellowing leaves indicate overwatering."]
    ).passed
    # High lexical overlap but opposite polarity is a contradiction, not entailment.
    contradiction = j.entails("Pothos is not toxic to cats", ["Pothos is toxic to cats."])
    assert not contradiction.passed
    assert "polarity" in contradiction.detail
    assert not j.entails("anything", []).passed


def test_deterministic_judge_contains_and_equivalent() -> None:
    j = DeterministicJudge()
    assert j.contains("You must report changes within 10 days.", "report within 10 days").passed
    assert j.equivalent("water the monstera weekly", "water the monstera weekly").passed
    assert not j.equivalent("toxic to cats", "bright indirect light").passed


def test_deterministic_judge_catches_antonym_contradiction_without_negation() -> None:
    """No explicit negation marker, but "safe" vs "toxic" is still a contradiction —
    the failure mode the judge-calibration probe set (g5) flagged as a false positive."""
    j = DeterministicJudge()
    contradiction = j.entails("Aloe vera is safe for dogs to eat.", ["Aloe vera is toxic to dogs."])
    assert not contradiction.passed
    assert "polarity" in contradiction.detail
    # High lexical overlap alone would otherwise have passed this (coverage >= threshold).
    assert contradiction.score >= 0.5


def test_deterministic_judge_equivalent_rejects_antonym_flip() -> None:
    """Near-identical sentences that flip a safety antonym are not equivalent, even
    though jaccard similarity is high (probe e3: "toxico" vs "seguro")."""
    j = DeterministicJudge()
    decision = j.equivalent(
        "El potos es toxico para los gatos si lo ingieren.",
        "El potos es seguro para los gatos si lo ingieren.",
    )
    assert not decision.passed
    assert "antonym" in decision.detail


def test_build_judge() -> None:
    assert isinstance(build_judge("deterministic"), DeterministicJudge)
    with pytest.raises(ValueError, match="unknown judge"):
        build_judge("nope")


# --- calibration -----------------------------------------------------------------
def test_cohens_kappa() -> None:
    assert cohens_kappa([True, True, False, False], [True, True, False, False]) == 1.0
    assert cohens_kappa([], []) == 1.0
    # Perfectly imbalanced (all same) -> degenerate expected agreement -> 1.0.
    assert cohens_kappa([True, True], [True, True]) == 1.0
    partial = cohens_kappa([True, False, True, False], [True, True, False, False])
    assert -1.0 <= partial < 1.0


def test_calibrate_and_staleness() -> None:
    judge = DeterministicJudge()
    probes = [
        JudgeProbe(
            id="p1",
            kind="entails",
            text_a="leaves yellow from overwatering",
            sources=["Yellow leaves come from overwatering."],
            human_label=True,
        ),
        JudgeProbe(
            id="p2",
            kind="contains",
            text_a="report within 10 days",
            text_b="10 days",
            human_label=True,
        ),
        JudgeProbe(
            id="p3",
            kind="equivalent",
            text_a="toxic to cats",
            text_b="bright light",
            human_label=False,
        ),
    ]
    record = calibrate(judge, probes)
    assert record.n_probes == 3
    assert record.agreement == 1.0
    assert record.meets_threshold
    assert "entails" in record.per_operation
    assert not is_stale(record, judge)
    # A reconfigured judge invalidates the record.
    assert is_stale(record, DeterministicJudge(entail_threshold=0.9))


def test_calibrate_unknown_probe_kind() -> None:
    with pytest.raises(ValueError, match="unknown probe kind"):
        calibrate(
            DeterministicJudge(), [JudgeProbe(id="x", kind="bogus", text_a="a", human_label=True)]
        )


# --- the published bounds must be the same bytes on every machine ---------------------


def _wilson_interval_pow(successes: int, n: int) -> tuple[float, float]:
    """What ``wilson_interval`` computed before: ``x ** 0.5`` for the margin."""
    z = Z_95
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * ((phat * (1 - phat) / n + z * z / (4 * n * n)) ** 0.5)
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def _wilson_interval_sqrt(successes: int, n: int) -> tuple[float, float]:
    """The correctly-rounded reference: ``math.sqrt`` for the margin."""
    z = Z_95
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def _wilson_inputs_that_separate_pow_from_sqrt(limit: int = 5) -> list[tuple[int, int]]:
    """(successes, n) pairs whose *interval*, not merely its margin, differs.

    A last-bit difference in the margin usually washes out in the division, so the search
    keeps only the pairs that survive into the returned bounds. Which pairs those are
    depends on the platform's libm, so they are searched for rather than hard-coded --
    a constant that separates the two roots on macOS is vacuous on glibc. On macOS
    (arm64, CPython 3.12.14) the first is (42, 62), a suite size this harness reaches.
    """
    found: list[tuple[int, int]] = []
    for n in range(1, 601):
        if len(found) >= limit:
            break
        for successes in range(n + 1):
            if len(found) >= limit:
                break
            if _wilson_interval_pow(successes, n) != _wilson_interval_sqrt(successes, n):
                found.append((successes, n))
    return found


def test_the_wilson_margin_uses_the_correctly_rounded_square_root() -> None:
    """``x ** 0.5`` is ``pow``, which IEEE 754 does not require to be correctly rounded.

    ``math.sqrt`` is ``sqrt``, which it does. The two differ in the last bit on some
    inputs, and *which* inputs depends on the platform's libm. These bounds are printed
    into ``docs/audits/eval-report.*``, which is byte-compared against a fresh
    regeneration, so a last-bit platform difference here is a red build on a file nobody
    edited -- the disagreement being between the laptop and the runner, not between two
    versions of the code.

    Measured on macOS 2026-09-01: 99 of the 80600 ``(successes, n)`` pairs with n<=400
    give a different margin under ``pow`` than under ``sqrt``, and the first whose
    published *bounds* differ is 42 of 62. None of them changed the report's 3-decimal
    figure today, which is the difference between "not currently broken" and "cannot
    break".
    """
    separating = _wilson_inputs_that_separate_pow_from_sqrt()
    if not separating:
        pytest.skip("this platform's pow is correctly rounded for every searched input")

    for successes, n in separating:
        assert wilson_interval(successes, n) == _wilson_interval_sqrt(successes, n)
        assert wilson_interval(successes, n) != _wilson_interval_pow(successes, n)


def test_no_published_statistic_is_computed_with_pow() -> None:
    """No ``x ** 0.5`` anywhere in ``eval/stats.py`` -- not just in ``wilson_interval``.

    Both functions in this module print into ``docs/audits/eval-report.*``, which is
    byte-compared against a fresh regeneration. Pinning only ``wilson_interval`` would let
    the next one in: ``wilson_difference_interval`` arrived with two inline ``** 0.5``
    calls and would have merged cleanly beside a fix that removed the first one, because
    git has no reason to see a contradiction between an addition and a deletion in
    different hunks. This asserts the property over the whole module, so the next
    published statistic cannot reintroduce the platform-dependent root either.
    """
    source = Path(inspect.getsourcefile(stats) or "").read_text(encoding="utf-8")
    offenders = [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Pow)
        and isinstance(node.right, ast.Constant)
        and node.right.value == 0.5
    ]
    assert not offenders, (
        f"sprout/eval/stats.py computes a square root with pow at line(s) {offenders}; "
        "use math.sqrt so the published bounds are the same bytes on every platform"
    )
