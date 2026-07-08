"""`sprout fit-confidence` (FIX-08 / ADR-0013): train-split loading, evidence collection,
the grid-search fit, and the config-YAML text surgery that writes `confidence.fit`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from sprout.answer import Assistant
from sprout.confidence import retrieval_config_fingerprint
from sprout.config import ConfidenceFit, Config
from sprout.eval.dataset import Dataset, DatasetItem, Provenance
from sprout.fit_confidence import (
    FitConfidenceError,
    TrainExample,
    collect_examples,
    fit_confidence,
    fit_constants,
    load_train_split,
    render_fit_yaml_block,
    upsert_confidence_fit,
    write_fit_to_config,
)

_PROV = Provenance(source="synthetic-train", license="CC0-1.0", added="2026-07-08")

_TRAIN_YAML = """
cases:
- id: t1
  question: why are my monstera leaves yellowing?
  expected_behavior: answer
  expected_facts:
  - overwatering
  provenance: {source: synthetic-train, license: CC0-1.0, added: '2026-07-08'}
- id: t2
  question: how do I patch a flat bicycle tire?
  expected_behavior: refuse-and-redirect
  should_refuse: true
  provenance: {source: synthetic-train, license: CC0-1.0, added: '2026-07-08'}
"""


# --- load_train_split --------------------------------------------------------------
def test_load_train_split_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FitConfidenceError, match="not found"):
        load_train_split(tmp_path / "nope.yaml")


def test_load_train_split_empty_raises(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("cases: []\n", encoding="utf-8")
    with pytest.raises(FitConfidenceError, match="no cases"):
        load_train_split(p)


def test_load_train_split_parses_cases(tmp_path: Path) -> None:
    p = tmp_path / "train.yaml"
    p.write_text(_TRAIN_YAML, encoding="utf-8")
    dataset = load_train_split(p)
    assert {it.id for it in dataset.items} == {"t1", "t2"}


# --- collect_examples ---------------------------------------------------------------
def test_collect_examples_labels_grounded_correct_answer_true(assistant: Assistant) -> None:
    item = DatasetItem(
        id="a1",
        question="why are my monstera leaves yellowing",
        expected_behavior="answer",
        expected_facts=["overwatering"],
        provenance=_PROV,
    )
    dataset = Dataset.from_items([item])
    examples = collect_examples(assistant, dataset)
    assert len(examples) == 1
    ex = examples[0]
    assert ex.item_id == "a1"
    assert ex.best > 0.0
    assert ex.label is True


def test_collect_examples_labels_wrong_expected_fact_false(assistant: Assistant) -> None:
    # In-corpus and answerable, but the expected fact never appears in the source text.
    item = DatasetItem(
        id="a2",
        question="why are my monstera leaves yellowing",
        expected_behavior="answer",
        expected_facts=["a fact absolutely not present in the corpus text anywhere"],
        provenance=_PROV,
    )
    dataset = Dataset.from_items([item])
    examples = collect_examples(assistant, dataset)
    assert examples[0].label is False


def test_collect_examples_labels_out_of_scope_false(assistant: Assistant) -> None:
    item = DatasetItem(
        id="r1",
        question="how do I patch a flat bicycle tire",
        expected_behavior="refuse-and-redirect",
        should_refuse=True,
        provenance=_PROV,
    )
    dataset = Dataset.from_items([item])
    examples = collect_examples(assistant, dataset)
    ex = examples[0]
    assert ex.label is False
    # Out-of-scope: no retrieved evidence clears the species filter/min_score meaningfully.
    assert ex.best >= 0.0


def test_collect_examples_should_refuse_true_forces_false_even_if_grounded(
    assistant: Assistant,
) -> None:
    # should_refuse=True on an otherwise-answerable, in-corpus question must still label
    # False -- the label encodes "should this evidence read as confidence-worthy", not
    # "did the generator produce text".
    item = DatasetItem(
        id="r2",
        question="why are my monstera leaves yellowing",
        should_refuse=True,
        provenance=_PROV,
    )
    dataset = Dataset.from_items([item])
    examples = collect_examples(assistant, dataset)
    assert examples[0].label is False


# --- fit_constants -------------------------------------------------------------------
def test_fit_constants_raises_on_empty() -> None:
    with pytest.raises(FitConfidenceError, match="no train examples"):
        fit_constants([])


def test_fit_constants_separates_well_evidenced_examples() -> None:
    # Strong-evidence correct answers vs. weak-evidence refusals: the fit should land on
    # a midpoint that puts the two populations on opposite sides of the logistic curve.
    examples = [
        TrainExample(item_id=f"pos{i}", best=0.85, margin=0.2, label=True) for i in range(10)
    ] + [TrainExample(item_id=f"neg{i}", best=0.05, margin=0.0, label=False) for i in range(10)]
    midpoint, steepness, margin_bonus = fit_constants(examples)
    assert 0.05 < midpoint < 0.85
    assert steepness > 0.0
    assert margin_bonus >= 0.0


# --- YAML text surgery ---------------------------------------------------------------
_FIT = ConfidenceFit(
    midpoint=0.31,
    steepness=7.5,
    margin_bonus=0.06,
    train_dataset_hash="abc123",
    train_path="eval/train/calibration_train.yaml",
    retrieval_config_hash="def456",
    n_items=24,
    fitted_at="2026-07-08",
)


def test_render_fit_yaml_block_has_every_field() -> None:
    block = render_fit_yaml_block(_FIT)
    for token in ("0.31", "7.5", "0.06", "abc123", "def456", "24", "2026-07-08"):
        assert token in block


def test_upsert_confidence_fit_inserts_when_no_confidence_key() -> None:
    original = "corpus:\n  path: corpus/processed\n"
    updated = upsert_confidence_fit(original, _FIT)
    assert "corpus:\n  path: corpus/processed\n" in updated
    parsed = yaml.safe_load(updated)
    assert parsed["confidence"]["fit"]["midpoint"] == 0.31


def test_upsert_confidence_fit_preserves_sibling_keys_and_comments() -> None:
    original = (
        "confidence:\n"
        "  abstain_threshold: 0.25   # a comment worth preserving\n"
        "  low_confidence_threshold: 0.50\n"
        "  reliability_bins: 10\n"
        "\n"
        "languages:\n"
        "  supported: [en, es]\n"
    )
    updated = upsert_confidence_fit(original, _FIT)
    assert "# a comment worth preserving" in updated
    assert "languages:\n  supported: [en, es]" in updated
    parsed = yaml.safe_load(updated)
    assert parsed["confidence"]["abstain_threshold"] == 0.25
    assert parsed["confidence"]["fit"]["train_dataset_hash"] == "abc123"
    assert parsed["languages"]["supported"] == ["en", "es"]


def test_upsert_confidence_fit_is_idempotent_on_refit() -> None:
    original = (
        "confidence:\n  abstain_threshold: 0.25\n  reliability_bins: 10\n\nlanguages:\n  a: b\n"
    )
    once = upsert_confidence_fit(original, _FIT)
    refit = ConfidenceFit(**{**_FIT.model_dump(), "midpoint": 0.5, "fitted_at": "2026-08-01"})
    twice = upsert_confidence_fit(once, refit)
    parsed = yaml.safe_load(twice)
    assert parsed["confidence"]["fit"]["midpoint"] == 0.5
    assert parsed["confidence"]["fit"]["fitted_at"] == "2026-08-01"
    # Only one `fit:` block survives, not two.
    assert twice.count("  fit:") == 1
    assert parsed["languages"]["a"] == "b"


def test_write_fit_to_config_validates_and_persists(tmp_path: Path) -> None:
    cfg_path = tmp_path / "sprout.yaml"
    cfg_path.write_text("confidence:\n  abstain_threshold: 0.25\n", encoding="utf-8")
    write_fit_to_config(_FIT, cfg_path)
    reloaded = Config.model_validate(yaml.safe_load(cfg_path.read_text(encoding="utf-8")))
    assert reloaded.confidence.fit is not None
    assert reloaded.confidence.fit.midpoint == 0.31


def test_confidence_fit_rejects_out_of_range_midpoint() -> None:
    # ConfidenceFit's own bounds are the first line of defense the config-YAML text
    # surgery in write_fit_to_config relies on: an invalid fit can never be constructed.
    with pytest.raises(ValidationError):
        ConfidenceFit(**{**_FIT.model_dump(), "midpoint": 5.0})


# --- end-to-end ------------------------------------------------------------------------
def test_fit_confidence_end_to_end_writes_matching_retrieval_hash(
    tmp_path: Path, assistant: Assistant
) -> None:
    train_path = tmp_path / "train.yaml"
    train_path.write_text(_TRAIN_YAML, encoding="utf-8")
    cfg_path = tmp_path / "sprout.yaml"
    cfg_path.write_text("confidence:\n  abstain_threshold: 0.25\n", encoding="utf-8")

    config = Config()
    fit = fit_confidence(assistant, config, train_path, cfg_path)

    assert fit.n_items == 2
    assert fit.retrieval_config_hash == retrieval_config_fingerprint(config.retrieval)
    reloaded = Config.model_validate(yaml.safe_load(cfg_path.read_text(encoding="utf-8")))
    assert reloaded.confidence.fit == fit
