"""Sprout's evaluation harness — the headline artifact.

120+ YAML cases across five suites (groundedness, safety, calibration, refusal,
multilingual), scored by deterministic checks blended with an optional LLM judge whose
model differs from the answer model. Runs are content-hashed and produce byte-identical
reports for identical inputs. Everything fails closed: a bad case, a hash mismatch, an
empty suite, or a malformed judge response fails the run rather than passing quietly.
"""

from __future__ import annotations

from .dataset import Dataset, DatasetItem, load_suite_dir
from .history import (
    HistoryEntry,
    SuiteScore,
    append_history_entry,
    check_drift,
    history_entry_from_result,
    load_history,
)
from .runner import RunResult, run_evaluation
from .suite import MetricDefinition, SuiteResult, Verdict, resolve_suites

__all__ = [
    "Dataset",
    "DatasetItem",
    "HistoryEntry",
    "MetricDefinition",
    "RunResult",
    "SuiteResult",
    "SuiteScore",
    "Verdict",
    "append_history_entry",
    "check_drift",
    "history_entry_from_result",
    "load_history",
    "load_suite_dir",
    "resolve_suites",
    "run_evaluation",
]
