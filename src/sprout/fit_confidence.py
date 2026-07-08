"""``sprout fit-confidence``: fit the confidence logistic on a held-out train split.

FIX-08 (`docs/ideation/02-large-scale-fixes.md`), ADR-0013. `confidence.py`'s
``_MIDPOINT``/``_STEEPNESS``/``_MARGIN_BONUS`` were hand-tuned once (ADR-0012) and never
re-fit; every retrieval change silently invalidates them and nothing notices except a
slow ECE drift. This module:

1. Replays the live :class:`~sprout.answer.Assistant` over a **train split** of
   generated calibration questions -- ``eval/train/calibration_train.yaml`` by default,
   never ``eval/suites/`` (fitting against the eval set would make the calibration
   suite's ECE gate a check of nothing; see the train file's own header comment).
2. Collects (best cosine score, margin over runner-up) -> was-a-confident-answer-correct
   pairs, using :meth:`Assistant.confidence_signal`, which deliberately bypasses the
   *current* abstain threshold so the fit isn't circular.
3. Grid-searches the same 3-parameter logistic ``confidence.py`` already uses (no
   learned model beyond it, preserving the transparent-function property) for the
   (midpoint, steepness, margin_bonus) that minimizes binary cross-entropy against those
   pairs.
4. Writes the fit -- values *and* provenance (train dataset hash, retrieval-config hash,
   item count, date) -- into ``confidence.fit`` in the target config YAML, via a
   text-surgical edit that leaves every other line (including hand-written comments)
   untouched.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .answer import Assistant
from .confidence import retrieval_config_fingerprint
from .config import ConfidenceFit, Config
from .eval.dataset import Dataset, DatasetItem, load_cases
from .text import coverage

# Mirrors eval/record.py's _FACT_COVERAGE: at least this fraction of an expected fact's
# content tokens must appear in the rendered text for the "answer" case to count as a
# correct, confidence-deserving example.
_FACT_COVERAGE = 0.6

# A small, fixed grid, not gradient descent or an external solver: the search is
# reproducible (same train split + same live engine -> same fit, byte for byte) and the
# fitted function stays a 3-parameter logistic, never a black-box learned model.
_MIDPOINT_GRID: tuple[float, ...] = tuple(round(x * 0.02, 2) for x in range(51))  # 0.00..1.00
_STEEPNESS_GRID: tuple[float, ...] = (
    1.0,
    2.0,
    3.0,
    4.0,
    6.0,
    8.0,
    10.0,
    12.0,
    16.0,
    20.0,
    25.0,
    30.0,
)
_MARGIN_BONUS_GRID: tuple[float, ...] = (0.0, 0.02, 0.05, 0.08, 0.1, 0.15, 0.2)
_EPS = 1e-6


class FitConfidenceError(ValueError):
    """Raised when there is nothing to fit against (empty/malformed train split)."""


@dataclass(frozen=True)
class TrainExample:
    """One (retrieval evidence, outcome) pair collected from the train split."""

    item_id: str
    best: float
    margin: float
    label: bool  # True: a confident answer here was correct; False: it wasn't / shouldn't be


def load_train_split(path: str | Path) -> Dataset:
    """Load a train-split YAML (same schema as ``eval/suites/*.yaml``, reused as-is).

    Deliberately does **not** go through ``eval.dataset.load_suite_dir`` -- that loader
    hash-pins and is reserved for ``eval/suites/``. A train split has no such pin (it is
    regenerated freely) and must never be discoverable as part of the eval dataset.
    """
    p = Path(path)
    if not p.exists():
        raise FitConfidenceError(f"train split not found: {p}")
    items = load_cases(p)
    if not items:
        raise FitConfidenceError(f"train split {p} has no cases")
    return Dataset.from_items(items)


def _label(item: DatasetItem, grounded: bool, rendered_text: str) -> bool:
    """Was a confident answer, if given here, actually the right call?

    Mirrors ``eval.record._is_correct`` but is evaluated on the pre-gate evidence a
    :class:`~sprout.models.ConfidenceEvidence` carries, not a full ``Answer`` --
    fit-confidence intentionally never routes through the confidence gate it is fitting.
    """
    if item.should_refuse or item.expected_behavior == "refuse-and-redirect":
        # Out-of-scope by construction: no evidence strength here should read as
        # confidence-worthy, regardless of what the generator happened to produce.
        return False
    if not grounded or not rendered_text:
        return False
    if item.expected_behavior == "answer" and item.expected_facts:
        return any(coverage(fact, rendered_text) >= _FACT_COVERAGE for fact in item.expected_facts)
    return True


def collect_examples(assistant: Assistant, dataset: Dataset) -> list[TrainExample]:
    """Replay ``assistant`` over every train-split case, gate-free, to get raw evidence."""
    examples: list[TrainExample] = []
    for item in dataset.items:
        evidence = assistant.confidence_signal(item.question, item.language)
        label = _label(item, evidence.grounded, evidence.text)
        examples.append(
            TrainExample(item_id=item.id, best=evidence.best, margin=evidence.margin, label=label)
        )
    return examples


def _mean_bce(
    examples: list[TrainExample], midpoint: float, steepness: float, margin_bonus: float
) -> float:
    total = 0.0
    for ex in examples:
        base = 1.0 / (1.0 + math.exp(-steepness * (ex.best - midpoint)))
        pred = base + margin_bonus * min(ex.margin, 0.3)
        pred = min(max(pred, _EPS), 1.0 - _EPS)
        y = 1.0 if ex.label else 0.0
        total += -(y * math.log(pred) + (1.0 - y) * math.log(1.0 - pred))
    return total / len(examples)


def fit_constants(examples: list[TrainExample]) -> tuple[float, float, float]:
    """Grid-search (midpoint, steepness, margin_bonus) minimizing mean binary
    cross-entropy against the train examples. Deterministic and dependency-free."""
    if not examples:
        raise FitConfidenceError("no train examples to fit against")
    best_loss = math.inf
    best_params: tuple[float, float, float] | None = None
    for midpoint in _MIDPOINT_GRID:
        for steepness in _STEEPNESS_GRID:
            for margin_bonus in _MARGIN_BONUS_GRID:
                loss = _mean_bce(examples, midpoint, steepness, margin_bonus)
                if loss < best_loss:
                    best_loss = loss
                    best_params = (midpoint, steepness, margin_bonus)
    assert best_params is not None  # examples is non-empty, so the grid always yields one
    return best_params


def render_fit_yaml_block(fit: ConfidenceFit) -> str:
    """The ``confidence.fit:`` YAML block, at 2-space indent to nest under ``confidence:``."""
    return (
        "  fit:  # written by `sprout fit-confidence` -- see ADR-0013\n"
        f"    midpoint: {fit.midpoint}\n"
        f"    steepness: {fit.steepness}\n"
        f"    margin_bonus: {fit.margin_bonus}\n"
        f'    train_dataset_hash: "{fit.train_dataset_hash}"\n'
        f"    train_path: {fit.train_path}\n"
        f'    retrieval_config_hash: "{fit.retrieval_config_hash}"\n'
        f"    n_items: {fit.n_items}\n"
        f'    fitted_at: "{fit.fitted_at}"\n'
    )


_CONFIDENCE_KEY_RE = re.compile(r"^confidence:\s*(#.*)?$")
_FIT_KEY_RE = re.compile(r"^  fit:\s*(#.*)?$")


def upsert_confidence_fit(yaml_text: str, fit: ConfidenceFit) -> str:
    """Insert or replace the ``confidence.fit:`` block in a config YAML's text.

    A targeted line-level edit rather than a yaml.safe_load/dump round-trip, so every
    other line -- including the hand-written comments on ``abstain_threshold`` and
    ``low_confidence_threshold`` -- is left byte-identical.
    """
    lines = yaml_text.splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    found = False
    while i < n:
        line = lines[i]
        if _CONFIDENCE_KEY_RE.match(line):
            found = True
            out.append(line)
            i += 1
            body: list[str] = []
            while i < n and (lines[i].startswith(" ") or lines[i].strip() == ""):
                if _FIT_KEY_RE.match(lines[i]):
                    i += 1
                    while i < n and (lines[i].startswith("    ") or lines[i].strip() == ""):
                        i += 1
                    continue
                body.append(lines[i])
                i += 1
            while body and body[-1].strip() == "":
                body.pop()
            out.extend(body)
            out.extend(render_fit_yaml_block(fit).splitlines())
            out.append("")
            continue
        out.append(line)
        i += 1
    text = "\n".join(out).rstrip("\n") + "\n"
    if not found:
        text += "\nconfidence:\n" + render_fit_yaml_block(fit)
    return text


def write_fit_to_config(fit: ConfidenceFit, config_path: str | Path) -> None:
    """Upsert ``confidence.fit`` into ``config_path``, validating the result round-trips
    through :class:`~sprout.config.Config` before writing (fail closed, never leave a
    config file the loader itself would reject)."""
    import yaml

    p = Path(config_path)
    original = p.read_text(encoding="utf-8")
    updated = upsert_confidence_fit(original, fit)
    parsed = yaml.safe_load(updated)
    Config.model_validate(parsed)  # raises if the edit produced something invalid
    p.write_text(updated, encoding="utf-8")


def fit_confidence(
    assistant: Assistant,
    config: Config,
    train_path: str | Path,
    config_path: str | Path,
) -> ConfidenceFit:
    """Fit + write in one call: the body of the ``sprout fit-confidence`` CLI command."""
    dataset = load_train_split(train_path)
    examples = collect_examples(assistant, dataset)
    midpoint, steepness, margin_bonus = fit_constants(examples)
    fit = ConfidenceFit(
        midpoint=midpoint,
        steepness=steepness,
        margin_bonus=margin_bonus,
        train_dataset_hash=dataset.content_hash,
        train_path=str(train_path),
        retrieval_config_hash=retrieval_config_fingerprint(config.retrieval),
        n_items=len(examples),
        fitted_at=date.today().isoformat(),
    )
    write_fit_to_config(fit, config_path)
    return fit
