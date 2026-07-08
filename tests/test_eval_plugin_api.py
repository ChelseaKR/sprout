"""EXP-14 / ADR-0013: entry-point suite discovery and the frozen public API surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import sprout.eval as eval_pkg
from sprout.eval.dataset import Dataset
from sprout.eval.judge import DeterministicJudge, Judge
from sprout.eval.suite import (
    _REGISTRY,
    ENTRY_POINT_GROUP,
    EvalContext,
    MetricDefinition,
    Suite,
    SuiteResult,
    _reset_entry_point_cache,
    available,
    load_entry_point_suites,
    register,
    resolve_suites,
)


class _StubSuite:
    """A minimal, valid third-party ``Suite`` for discovery tests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.metric = MetricDefinition(name=name, definition="stub", threshold=0.5)

    def run(self, ctx: EvalContext) -> SuiteResult:  # pragma: no cover - not exercised
        raise NotImplementedError


@dataclass
class _FakeEntryPoint:
    name: str
    _target: Any

    @property
    def value(self) -> str:
        return f"<stub {self.name}>"

    def load(self) -> Any:
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Every test gets a fresh entry-point cache and a registry snapshot restored after."""
    _reset_entry_point_cache()
    before = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(before)
    _reset_entry_point_cache()


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, *eps: _FakeEntryPoint) -> None:
    def fake_entry_points(*, group: str) -> tuple[_FakeEntryPoint, ...]:
        assert group == ENTRY_POINT_GROUP
        return eps

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)


# --- entry-point discovery --------------------------------------------------------
def test_discovers_and_registers_an_entry_point_suite_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_entry_points(monkeypatch, _FakeEntryPoint("stub-a", _StubSuite("stub-a")))
    newly = load_entry_point_suites()
    assert newly == ["stub-a"]
    assert "stub-a" in available()
    assert resolve_suites("stub-a")[0].name == "stub-a"


def test_discovers_a_zero_arg_factory_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    def build() -> _StubSuite:
        return _StubSuite("stub-factory")

    _patch_entry_points(monkeypatch, _FakeEntryPoint("stub-factory", build))
    assert load_entry_point_suites() == ["stub-factory"]
    assert "stub-factory" in available()


def test_discovery_is_cached_after_the_first_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_entry_points(*, group: str) -> tuple[_FakeEntryPoint, ...]:
        nonlocal calls
        calls += 1
        return (_FakeEntryPoint("stub-once", _StubSuite("stub-once")),)

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)
    assert load_entry_point_suites() == ["stub-once"]
    assert load_entry_point_suites() == []  # cached: no re-scan, nothing "newly" registered
    assert calls == 1


def test_duplicate_suite_name_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    register(_StubSuite("dup-name"))
    _patch_entry_points(monkeypatch, _FakeEntryPoint("plugin-dup", _StubSuite("dup-name")))
    with pytest.raises(ValueError, match="duplicate suite name"):
        load_entry_point_suites()


def test_entry_point_colliding_with_a_builtin_suite_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    colliding = _FakeEntryPoint("plugin-groundedness", _StubSuite("groundedness"))
    _patch_entry_points(monkeypatch, colliding)
    with pytest.raises(ValueError, match="duplicate suite name"):
        load_entry_point_suites()


def test_entry_point_that_fails_to_load_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, _FakeEntryPoint("broken", RuntimeError("boom")))
    with pytest.raises(ImportError, match="failed to load suite entry point"):
        load_entry_point_suites()


def test_entry_point_not_resolving_to_a_suite_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, _FakeEntryPoint("not-a-suite", object()))
    with pytest.raises(TypeError, match="did not resolve to a Suite"):
        load_entry_point_suites()


def test_resolve_suites_all_includes_a_discovered_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, _FakeEntryPoint("stub-b", _StubSuite("stub-b")))
    assert any(s.name == "stub-b" for s in resolve_suites("all"))
    assert "stub-b" in available()  # cached: the second call doesn't re-scan (or re-collide)


# --- the frozen public API surface (ADR-0013) --------------------------------------
def test_eval_package_exports_the_frozen_plugin_surface() -> None:
    expected = {
        "Dataset",
        "DatasetItem",
        "Judge",
        "JudgeDecision",
        "DeterministicJudge",
        "build_judge",
        "Suite",
        "EvalContext",
        "SuiteResult",
        "MetricDefinition",
        "ExampleOutcome",
        "SegmentScore",
        "Verdict",
        "register",
        "available",
        "resolve_suites",
        "load_entry_point_suites",
        "ENTRY_POINT_GROUP",
        "run_evaluation",
    }
    assert expected <= set(eval_pkg.__all__)
    for name in expected:
        assert hasattr(eval_pkg, name), f"sprout.eval.{name} is in __all__ but not importable"


def test_dataset_judge_suiteresult_metricdefinition_are_frozen() -> None:
    assert Dataset.model_config.get("frozen") is True
    assert SuiteResult.model_config.get("frozen") is True
    assert MetricDefinition.model_config.get("frozen") is True
    assert getattr(Suite, "_is_protocol", False) is True  # still a Protocol, not accidentally a class
    judge = DeterministicJudge()
    assert isinstance(judge, Judge)  # runtime_checkable Protocol conformance
