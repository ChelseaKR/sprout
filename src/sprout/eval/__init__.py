"""Sprout's evaluation harness — the headline artifact.

120+ YAML cases across five suites (groundedness, safety, calibration, refusal,
multilingual), scored by deterministic checks blended with an optional LLM judge whose
model differs from the answer model. Runs are content-hashed and produce byte-identical
reports for identical inputs. Everything fails closed: a bad case, a hash mismatch, an
empty suite, or a malformed judge response fails the run rather than passing quietly.

**Public plugin API (ADR-0019).** The names in ``__all__`` below are the frozen surface a
third-party suite is written against: ``Dataset``/``DatasetItem`` (what a suite reads),
``Judge`` (the one model-touching seam a suite calls through), ``Suite``/``EvalContext``
(the contract a suite implements and receives), ``SuiteResult``/``MetricDefinition``
(what a suite must return and how it's scored), and ``register``/``ENTRY_POINT_GROUP``
(how a suite gets discovered without forking this repo). These follow semver: within a
major version, existing fields are never removed or repurposed and existing behavior is
never changed incompatibly — only additive, optional fields/functions land in a minor
release. See ``docs/adr/0019-frozen-plugin-api-for-sprout-eval.md`` and the worked,
installable example at ``examples/herb-garden-plugin/``.
"""

from __future__ import annotations

from .dataset import (
    Dataset,
    DatasetError,
    DatasetItem,
    Provenance,
    TargetResponse,
    load_cases,
    load_suite_dir,
    write_sidecar,
)
from .history import (
    HistoryEntry,
    SuiteScore,
    append_history_entry,
    check_drift,
    history_entry_from_result,
    load_history,
)
from .judge import DeterministicJudge, Judge, JudgeDecision, build_judge
from .runner import RunFingerprint, RunResult, run_evaluation
from .suite import (
    ENTRY_POINT_GROUP,
    EvalContext,
    ExampleOutcome,
    MetricDefinition,
    SegmentScore,
    Suite,
    SuiteResult,
    Verdict,
    aggregate,
    available,
    fail_closed,
    load_entry_point_suites,
    register,
    resolve_suites,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "Dataset",
    "DatasetError",
    "DatasetItem",
    "DeterministicJudge",
    "EvalContext",
    "ExampleOutcome",
    "HistoryEntry",
    "Judge",
    "JudgeDecision",
    "MetricDefinition",
    "Provenance",
    "RunFingerprint",
    "RunResult",
    "SegmentScore",
    "Suite",
    "SuiteResult",
    "SuiteScore",
    "TargetResponse",
    "Verdict",
    "aggregate",
    "append_history_entry",
    "available",
    "build_judge",
    "check_drift",
    "fail_closed",
    "history_entry_from_result",
    "load_cases",
    "load_entry_point_suites",
    "load_history",
    "load_suite_dir",
    "register",
    "resolve_suites",
    "run_evaluation",
    "write_sidecar",
]
