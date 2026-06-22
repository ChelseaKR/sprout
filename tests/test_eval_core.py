"""Unit tests for the eval core: dataset, stats, judge, calibration."""

from __future__ import annotations

from pathlib import Path

import pytest

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
from sprout.eval.stats import is_underpowered, wilson_interval

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
