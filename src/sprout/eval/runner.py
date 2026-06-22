"""The run loop: fingerprint, run each suite fail-closed, decide an overall verdict.

The :class:`RunFingerprint` is the run's identity — harness version, seed, dataset hash,
judge config hash, target name, suite names — and deliberately excludes wall-clock time, so
the JSON artifact is byte-identical for identical inputs (the reproducibility property the
report and baseline diff rely on). Any suite that raises is converted to a fail-closed FAIL
rather than aborting the run. Threshold overrides are applied copy-on-write so the registry
singletons are never mutated.
"""

from __future__ import annotations

import copy

from pydantic import BaseModel, ConfigDict

from .. import __version__
from ..determinism import DEFAULT_SEED, sha256_of_obj
from . import suites as _suites  # noqa: F401 - import registers the built-in suites
from .dataset import Dataset
from .judge import Judge
from .suite import EvalContext as _EvalContext
from .suite import Suite, SuiteResult, Verdict, fail_closed


class RunFingerprint(BaseModel):
    model_config = ConfigDict(frozen=True)

    harness_version: str
    seed: int
    dataset_hash: str
    judge_config_hash: str
    target: str
    suite_names: tuple[str, ...]

    @property
    def digest(self) -> str:
        return sha256_of_obj(self.model_dump())


class RunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    fingerprint: RunFingerprint
    overall_verdict: Verdict
    suite_results: tuple[SuiteResult, ...]

    @property
    def passed(self) -> bool:
        return self.overall_verdict is Verdict.PASS

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1


def _with_threshold(suite: Suite, threshold: float) -> Suite:
    clone = copy.copy(suite)
    clone.metric = suite.metric.model_copy(update={"threshold": threshold})  # instance shadow
    return clone


def _apply_statistical_gate(result: SuiteResult) -> SuiteResult:
    """Flip PASS->FAIL if the Wilson lower bound does not clear the threshold."""
    if result.verdict is not Verdict.PASS or not result.metric.higher_is_better:
        return result
    if result.ci_low >= result.metric.threshold:
        return result
    return result.model_copy(
        update={
            "verdict": Verdict.FAIL,
            "notes": (result.notes + "; " if result.notes else "")
            + f"statistical gate: CI lower bound {result.ci_low:.3f} < threshold",
        }
    )


def run_evaluation(
    dataset: Dataset,
    judge: Judge,
    suites: list[Suite],
    *,
    target: str,
    seed: int = DEFAULT_SEED,
    threshold_overrides: dict[str, float] | None = None,
    statistical_gate: bool = False,
) -> RunResult:
    overrides = threshold_overrides or {}
    names = {s.name for s in suites}
    unknown = [k for k in overrides if k not in names]
    if unknown:
        raise ValueError(f"threshold_overrides for unknown suite(s): {unknown}")

    fingerprint = RunFingerprint(
        harness_version=__version__,
        seed=seed,
        dataset_hash=dataset.content_hash,
        judge_config_hash=judge.config_hash,
        target=target,
        suite_names=tuple(s.name for s in suites),
    )
    ctx = _EvalContext(dataset=dataset, judge=judge)

    results: list[SuiteResult] = []
    for suite in suites:
        active = _with_threshold(suite, overrides[suite.name]) if suite.name in overrides else suite
        try:
            result = active.run(ctx)
        except Exception as exc:
            result = fail_closed(
                suite=suite.name,
                metric=suite.metric,
                dataset_version=dataset.version,
                judge=judge,
                reason=f"{type(exc).__name__}: {exc}",
            )
        if statistical_gate:
            result = _apply_statistical_gate(result)
        results.append(result)

    overall = Verdict.PASS if results and all(r.passed for r in results) else Verdict.FAIL
    return RunResult(fingerprint=fingerprint, overall_verdict=overall, suite_results=tuple(results))
