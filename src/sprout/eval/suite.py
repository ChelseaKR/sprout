"""The suite contract: a metric definition, a fail-closed result, and a registry.

Design invariants borrowed from the portfolio's eval harness:

* ``Verdict`` has only PASS and FAIL — there is no "skipped". Absent data fails closed.
* Every suite carries a *written* :class:`MetricDefinition` (name, definition, threshold,
  direction) that is reproduced verbatim in the report — no opaque score.
* A ``SuiteResult`` with ``n_items == 0`` cannot be PASS: a validator raises, so an empty
  or mis-filtered suite can never pass quietly.
* Suites self-register and are resolved by a CLI selector (``all`` or ``a,b,c``); an
  unknown name raises.
* Third-party suites register the same way, discovered via the ``sprout.eval.suites``
  ``importlib.metadata`` entry-point group (see :func:`load_entry_point_suites`) — a
  suite name collision between the built-ins/an already-loaded plugin and a newly
  discovered one is a hard error (fail-closed), never a silent overwrite. This is the
  ADR-0019 plugin seam: an installed package can add a suite with zero fork of this repo.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from .stats import is_underpowered, wilson_interval

if TYPE_CHECKING:
    from .dataset import Dataset
    from .judge import Judge

#: The ``importlib.metadata`` entry-point group third-party packages register suites
#: under, e.g. in ``pyproject.toml``::
#:
#:     [project.entry-points."sprout.eval.suites"]
#:     my-suite = "my_package.suite:build_suite"
#:
#: The entry point must resolve (``.load()``) to either a ready :class:`Suite` instance
#: or a zero-argument callable that returns one. See ``examples/herb-garden-plugin`` for
#: a worked, installable example.
ENTRY_POINT_GROUP = "sprout.eval.suites"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class MetricDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    definition: str
    threshold: float
    higher_is_better: bool = True


class ExampleOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str
    passed: bool
    score: float
    detail: str = ""


class SegmentScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    score: float
    n: int
    verdict: Verdict


class SuiteResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    suite: str
    metric: MetricDefinition
    score: float
    verdict: Verdict
    n_items: int
    ci_low: float
    ci_high: float
    underpowered: bool
    dataset_version: str
    judge_method: str
    judge_config_hash: str
    notes: str = ""
    segments: tuple[SegmentScore, ...] = ()
    failing_examples: tuple[ExampleOutcome, ...] = ()

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.PASS

    @model_validator(mode="after")
    def _fail_closed_when_empty(self) -> SuiteResult:
        if self.n_items == 0 and self.verdict is Verdict.PASS:
            raise ValueError(f"suite {self.suite!r} reported PASS with zero items")
        return self


@dataclass(frozen=True)
class EvalContext:
    """Everything a suite needs: the dataset to evaluate and the judge to consult."""

    dataset: Dataset
    judge: Judge


@runtime_checkable
class Suite(Protocol):
    name: str
    metric: MetricDefinition

    def run(self, ctx: EvalContext) -> SuiteResult: ...


def aggregate(
    *,
    suite: str,
    metric: MetricDefinition,
    outcomes: Sequence[ExampleOutcome],
    dataset_version: str,
    judge: Judge,
    extra_pass: bool = True,
    notes: str = "",
    segments: Sequence[SegmentScore] = (),
    score_override: float | None = None,
) -> SuiteResult:
    """Turn per-item outcomes into a fail-closed SuiteResult with a Wilson CI."""
    n = len(outcomes)
    n_pass = sum(1 for o in outcomes if o.passed)
    score = score_override if score_override is not None else (n_pass / n if n else 0.0)
    low, high = wilson_interval(n_pass, n)
    meets = score >= metric.threshold if metric.higher_is_better else score <= metric.threshold
    verdict = Verdict.PASS if (n > 0 and meets and extra_pass) else Verdict.FAIL
    failing = tuple(o for o in outcomes if not o.passed)[:20]
    return SuiteResult(
        suite=suite,
        metric=metric,
        score=round(score, 4),
        verdict=verdict,
        n_items=n,
        ci_low=round(low, 4),
        ci_high=round(high, 4),
        underpowered=is_underpowered(n),
        dataset_version=dataset_version,
        judge_method=judge.method,
        judge_config_hash=judge.config_hash,
        notes=notes,
        segments=tuple(segments),
        failing_examples=failing,
    )


def fail_closed(
    *, suite: str, metric: MetricDefinition, dataset_version: str, judge: Judge, reason: str
) -> SuiteResult:
    """A zero-item FAIL result for a suite that could not run (absent data, exception)."""
    return SuiteResult(
        suite=suite,
        metric=metric,
        score=0.0,
        verdict=Verdict.FAIL,
        n_items=0,
        ci_low=0.0,
        ci_high=0.0,
        underpowered=True,
        dataset_version=dataset_version,
        judge_method=judge.method,
        judge_config_hash=judge.config_hash,
        notes=f"fail-closed: {reason}",
    )


# --- registry --------------------------------------------------------------------
_REGISTRY: dict[str, Suite] = {}
_entry_points_loaded = False


def register(suite: Suite) -> Suite:
    _REGISTRY[suite.name] = suite
    return suite


def load_entry_point_suites() -> list[str]:
    """Discover and register third-party suites from the ``sprout.eval.suites`` entry-point
    group, alongside the in-tree registry populated by ``import sprout.eval.suites``.

    Idempotent and cached for the process lifetime — the first call scans installed
    package metadata and registers every discovered suite; later calls are a no-op. A
    discovered suite whose ``name`` collides with an already-registered suite (built-in
    or another plugin) is a hard error: entry-point suites never silently shadow or get
    shadowed. Returns the names newly registered (empty on a cached call).
    """
    global _entry_points_loaded
    if _entry_points_loaded:
        return []
    newly_registered: list[str] = []
    for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            loaded = ep.load()
        except Exception as exc:  # pragma: no cover - defensive, broken plugin install
            raise ImportError(
                f"failed to load suite entry point {ep.name!r} ({ep.value}): {exc}"
            ) from exc
        suite = loaded() if callable(loaded) and not hasattr(loaded, "run") else loaded
        if not isinstance(suite, Suite):
            raise TypeError(
                f"entry point {ep.name!r} ({ep.value}) did not resolve to a Suite "
                f"(an object with .name, .metric, and .run) — got {suite!r}"
            )
        if suite.name in _REGISTRY:
            raise ValueError(
                f"duplicate suite name {suite.name!r}: entry point {ep.name!r} ({ep.value}) "
                "collides with an already-registered suite (built-in or another plugin); "
                "fail-closed rather than silently shadowing it"
            )
        register(suite)
        newly_registered.append(suite.name)
    # Only mark the scan complete after it finishes cleanly: a raising plugin must be
    # re-scanned (and re-raise) on the next call, never silently skipped for the rest of
    # the process lifetime.
    _entry_points_loaded = True
    return newly_registered


def _reset_entry_point_cache() -> None:
    """Test-only hook: forget that entry points were scanned, so a test can re-trigger
    discovery against a monkeypatched ``importlib.metadata.entry_points``."""
    global _entry_points_loaded
    _entry_points_loaded = False


def available() -> list[str]:
    load_entry_point_suites()
    return sorted(_REGISTRY)


def resolve_suites(selector: str) -> list[Suite]:
    """Resolve ``all`` or a comma-separated list of suite names. Unknown name raises.

    Both the built-in suites (registered when ``sprout.eval.suites`` is imported) and any
    third-party suites registered via the ``sprout.eval.suites`` entry-point group
    (:func:`load_entry_point_suites`) are eligible.
    """
    load_entry_point_suites()
    if selector.strip() == "all":
        return [_REGISTRY[name] for name in available()]
    names = [n.strip() for n in selector.split(",") if n.strip()]
    missing = [n for n in names if n not in _REGISTRY]
    if missing:
        raise KeyError(f"unknown suite(s): {missing}; available: {available()}")
    return [_REGISTRY[n] for n in names]
