"""Tests for the Phase 3 tuning-scope gate (docs/ROADMAP.md): tunable-surface changes must
cite an already-committed eval failure, never a held-out/local-only result."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sprout.eval.runner import RunFingerprint, RunResult
from sprout.eval.suite import ExampleOutcome, MetricDefinition, SuiteResult, Verdict
from sprout.eval.tuning_scope import (
    TuningScopeError,
    check_tuning_scope,
    commit_messages,
    committed_failing_ids,
    is_tunable_path,
    referenced_case_ids,
    tunable_paths,
)

# --- pure unit tests ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("src/sprout/retrieve.py", True),
        ("src/sprout/answer.py", True),
        ("src/sprout/guards.py", True),
        ("src/sprout/confidence.py", True),
        ("src/sprout/lexical.py", True),
        ("src/sprout/config.py", True),
        ("config/sprout.yaml", True),
        ("src/sprout/providers/deterministic.py", True),
        ("src/sprout/providers/bedrock.py", True),
        ("src/sprout/provider_lifecycle.py", True),
        ("src/sprout/server.py", False),
        ("docs/ROADMAP.md", False),
        ("tests/test_rag.py", False),
        ("eval/suites/safety.yaml", False),
    ],
)
def test_is_tunable_path(path: str, expected: bool) -> None:
    assert is_tunable_path(path) is expected


def test_tunable_paths_filters_and_sorts() -> None:
    changed = ["README.md", "src/sprout/guards.py", "src/sprout/retrieve.py", "docs/x.md"]
    assert tunable_paths(changed) == ["src/sprout/guards.py", "src/sprout/retrieve.py"]


def test_referenced_case_ids_parses_trailer_list() -> None:
    messages = [
        "fix(retrieve): tighten threshold\n\nBody text.\n\n"
        "Tunes-Against: safety-025, refusal-003\n",
        "unrelated commit with no trailer",
        "chore: also tunes\n\ntunes-against: calibration-019\n",  # case-insensitive header
    ]
    assert referenced_case_ids(messages) == {"safety-025", "refusal-003", "calibration-019"}


def test_referenced_case_ids_empty_when_absent() -> None:
    assert referenced_case_ids(["feat: add a new suite", "docs: typo"]) == set()


def _baseline_result(failing_ids: dict[str, list[str]]) -> RunResult:
    suites = []
    for suite_name, ids in failing_ids.items():
        failing = tuple(ExampleOutcome(item_id=i, passed=False, score=0.0, detail="x") for i in ids)
        suites.append(
            SuiteResult(
                suite=suite_name,
                metric=MetricDefinition(
                    name="m", definition="d", threshold=0.5, higher_is_better=True
                ),
                score=0.9,
                verdict=Verdict.PASS,
                n_items=10,
                ci_low=0.8,
                ci_high=0.95,
                underpowered=False,
                dataset_version="sha256:deadbeef",
                judge_method="deterministic",
                judge_config_hash="abc",
                failing_examples=failing,
            )
        )
    return RunResult(
        fingerprint=RunFingerprint(
            harness_version="0.1.0",
            seed=1729,
            dataset_hash="deadbeef",
            judge_config_hash="abc",
            target="deterministic:extractive",
            suite_names=tuple(failing_ids),
        ),
        overall_verdict=Verdict.PASS,
        suite_results=tuple(suites),
    )


def test_committed_failing_ids_collects_across_suites(tmp_path: Path) -> None:
    baseline = _baseline_result(
        {"safety": ["safety-025"], "refusal": ["refusal-003", "calibration-019"]}
    )
    p = tmp_path / "eval-baseline.json"
    p.write_text(baseline.model_dump_json(), encoding="utf-8")
    assert committed_failing_ids(p) == {"safety-025", "refusal-003", "calibration-019"}


# --- integration tests against a real git repo -------------------------------------------


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.invalid"], root)
    _git(["config", "user.name", "Test"], root)

    (root / "src" / "sprout").mkdir(parents=True)
    (root / "src" / "sprout" / "providers").mkdir()
    (root / "docs" / "audits").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "src" / "sprout" / "retrieve.py").write_text("# retrieval v1\n", encoding="utf-8")
    (root / "src" / "sprout" / "guards.py").write_text("# guards v1\n", encoding="utf-8")
    (root / "src" / "sprout" / "server.py").write_text("# server\n", encoding="utf-8")
    (root / "config" / "sprout.yaml").write_text(
        "generation:\n  relevance_floor: 0.30  # baseline comment\n", encoding="utf-8"
    )
    (root / "src" / "sprout" / "providers" / "__init__.py").write_text(
        "def build(config):\n"
        "    from .bedrock import BedrockGenerator\n"
        "    model = config.generation.model or 'model-a'\n"
        "    return BedrockGenerator(model=model, region=config.generation.region)\n",
        encoding="utf-8",
    )
    (root / "src" / "sprout" / "providers" / "bedrock.py").write_text(
        "REQUEST = {'model': 'model-a', 'temperature': 0.0, 'system': 'grounded'}\n",
        encoding="utf-8",
    )
    (root / "src" / "sprout" / "provider_lifecycle.py").write_text(
        "class _BudgetedGenerator:\n"
        "    def generate(self, query, context, max_sentences):\n"
        "        return self._provider.generate(query, context, max_sentences)\n",
        encoding="utf-8",
    )

    baseline = _baseline_result({"safety": ["safety-025"], "refusal": ["refusal-003"]})
    (root / "docs" / "audits" / "eval-baseline.json").write_text(
        baseline.model_dump_json(), encoding="utf-8"
    )

    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "chore: initial commit"], root)
    _git(["branch", "-q", "-m", "main"], root)
    _git(["checkout", "-q", "-b", "work"], root)
    return root


def test_non_tunable_change_passes_without_trailer(repo: Path) -> None:
    (repo / "src" / "sprout" / "server.py").write_text("# server v2\n", encoding="utf-8")
    _git(["commit", "-q", "-am", "feat(server): tweak logging"], repo)
    issues = check_tuning_scope(
        base_ref="main", baseline_path="docs/audits/eval-baseline.json", repo_root=repo
    )
    assert issues == []


def test_comment_only_config_change_passes_without_trailer(repo: Path) -> None:
    (repo / "config" / "sprout.yaml").write_text(
        "generation:\n  relevance_floor: 0.30  # clearer comment only\n", encoding="utf-8"
    )
    _git(["commit", "-q", "-am", "docs(config): clarify threshold comment"], repo)
    assert check_tuning_scope(base_ref="main", repo_root=repo) == []


def test_semantic_config_change_still_requires_real_case(repo: Path) -> None:
    (repo / "config" / "sprout.yaml").write_text(
        "generation:\n  relevance_floor: 0.35  # changed behavior\n", encoding="utf-8"
    )
    _git(["commit", "-q", "-am", "fix(config): change threshold"], repo)
    issues = check_tuning_scope(base_ref="main", repo_root=repo)
    assert len(issues) == 1
    assert "config/sprout.yaml" in issues[0]


def test_named_lifecycle_wrapper_only_passes_without_trailer(repo: Path) -> None:
    (repo / "src" / "sprout" / "providers" / "__init__.py").write_text(
        "def build(config):\n"
        "    from ..provider_lifecycle import observe_generation\n"
        "    from .bedrock import BedrockGenerator\n"
        "    model = config.generation.model or 'model-a'\n"
        "    return observe_generation(\n"
        "        BedrockGenerator(model=model, region=config.generation.region),\n"
        "        max_cost_usd=config.generation.max_cost_usd,\n"
        "    )\n",
        encoding="utf-8",
    )
    _git(["commit", "-q", "-am", "feat(ops): observe provider lifecycle"], repo)
    assert check_tuning_scope(base_ref="main", repo_root=repo) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("'model-a'", "'model-b'"),
        ("'temperature': 0.0", "'temperature': 0.4"),
        ("'grounded'", "'answer freely'"),
    ],
)
def test_provider_model_decoding_and_prompt_edits_fail_closed(
    repo: Path, old: str, new: str
) -> None:
    path = repo / "src" / "sprout" / "providers" / "bedrock.py"
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    _git(["commit", "-q", "-am", "feat(provider): alter behavior"], repo)
    issues = check_tuning_scope(base_ref="main", repo_root=repo)
    assert len(issues) == 1
    assert "src/sprout/providers/bedrock.py" in issues[0]


def test_provider_factory_model_edit_is_not_erased_with_wrapper(repo: Path) -> None:
    (repo / "src" / "sprout" / "providers" / "__init__.py").write_text(
        "def build(config):\n"
        "    from ..provider_lifecycle import observe_generation\n"
        "    from .bedrock import BedrockGenerator\n"
        "    model = config.generation.model or 'model-b'\n"
        "    return observe_generation(\n"
        "        BedrockGenerator(model=model, region=config.generation.region),\n"
        "        max_cost_usd=config.generation.max_cost_usd,\n"
        "    )\n",
        encoding="utf-8",
    )
    _git(["commit", "-q", "-am", "feat(provider): switch model under wrapper"], repo)
    issues = check_tuning_scope(base_ref="main", repo_root=repo)
    assert len(issues) == 1
    assert "src/sprout/providers/__init__.py" in issues[0]


def test_provider_wrapper_with_unapproved_budget_expression_fails_closed(repo: Path) -> None:
    (repo / "src" / "sprout" / "providers" / "__init__.py").write_text(
        "def build(config):\n"
        "    from ..provider_lifecycle import observe_generation\n"
        "    from .bedrock import BedrockGenerator\n"
        "    model = config.generation.model or 'model-a'\n"
        "    return observe_generation(\n"
        "        BedrockGenerator(model=model, region=config.generation.region),\n"
        "        max_cost_usd=999.0,\n"
        "    )\n",
        encoding="utf-8",
    )
    _git(["commit", "-q", "-am", "feat(provider): bypass configured budget"], repo)
    issues = check_tuning_scope(base_ref="main", repo_root=repo)
    assert len(issues) == 1
    assert "src/sprout/providers/__init__.py" in issues[0]


def test_provider_wrapper_around_unapproved_factory_fails_closed(repo: Path) -> None:
    (repo / "src" / "sprout" / "providers" / "__init__.py").write_text(
        "def build(config):\n"
        "    from ..provider_lifecycle import observe_generation\n"
        "    from .bedrock import BedrockGenerator\n"
        "    model = config.generation.model or 'model-a'\n"
        "    return observe_generation(\n"
        "        make_generator(model=model, region=config.generation.region),\n"
        "        max_cost_usd=config.generation.max_cost_usd,\n"
        "    )\n",
        encoding="utf-8",
    )
    _git(["commit", "-q", "-am", "feat(provider): use an unapproved factory"], repo)
    issues = check_tuning_scope(base_ref="main", repo_root=repo)
    assert len(issues) == 1
    assert "src/sprout/providers/__init__.py" in issues[0]


def test_operational_comparison_uses_merge_base_when_base_advances(repo: Path) -> None:
    (repo / "src" / "sprout" / "providers" / "__init__.py").write_text(
        "def build(config):\n"
        "    from ..provider_lifecycle import observe_generation\n"
        "    from .bedrock import BedrockGenerator\n"
        "    model = config.generation.model or 'model-a'\n"
        "    return observe_generation(\n"
        "        BedrockGenerator(model=model, region=config.generation.region),\n"
        "        max_cost_usd=config.generation.max_cost_usd,\n"
        "    )\n",
        encoding="utf-8",
    )
    _git(["commit", "-q", "-am", "feat(ops): observe provider lifecycle"], repo)

    _git(["checkout", "-q", "main"], repo)
    path = repo / "src" / "sprout" / "providers" / "__init__.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace("model-a", "model-main-only"),
        encoding="utf-8",
    )
    _git(["commit", "-q", "-am", "feat(provider): advance main model"], repo)
    _git(["checkout", "-q", "work"], repo)

    assert check_tuning_scope(base_ref="main", repo_root=repo) == []


def test_later_lifecycle_generate_output_edit_fails_closed(repo: Path) -> None:
    path = repo / "src" / "sprout" / "provider_lifecycle.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "return self._provider.generate(query, context, max_sentences)",
            "return [('invented output', 'invented-source')]",
        ),
        encoding="utf-8",
    )
    _git(["commit", "-q", "-am", "feat(lifecycle): rewrite generated output"], repo)

    issues = check_tuning_scope(base_ref="main", repo_root=repo)
    assert len(issues) == 1
    assert "src/sprout/provider_lifecycle.py" in issues[0]


def test_unknown_provider_hunk_fails_closed(repo: Path) -> None:
    path = repo / "src" / "sprout" / "providers" / "bedrock.py"
    path.write_text(path.read_text(encoding="utf-8") + "\nEXTRA = 'unknown behavior'\n")
    _git(["commit", "-q", "-am", "feat(provider): add unknown behavior"], repo)
    issues = check_tuning_scope(base_ref="main", repo_root=repo)
    assert len(issues) == 1
    assert "src/sprout/providers/bedrock.py" in issues[0]


def test_guard_edit_still_requires_real_case(repo: Path) -> None:
    (repo / "src" / "sprout" / "guards.py").write_text("# guards v2\n", encoding="utf-8")
    _git(["commit", "-q", "-am", "fix(guards): alter guard"], repo)
    issues = check_tuning_scope(base_ref="main", repo_root=repo)
    assert len(issues) == 1
    assert "src/sprout/guards.py" in issues[0]


def test_tunable_change_without_trailer_fails(repo: Path) -> None:
    (repo / "src" / "sprout" / "retrieve.py").write_text("# retrieval v2\n", encoding="utf-8")
    _git(["commit", "-q", "-am", "fix(retrieve): widen the score gate"], repo)
    issues = check_tuning_scope(
        base_ref="main", baseline_path="docs/audits/eval-baseline.json", repo_root=repo
    )
    assert len(issues) == 1
    assert "Tunes-Against" in issues[0]


def test_tunable_change_citing_unknown_id_fails(repo: Path) -> None:
    (repo / "src" / "sprout" / "retrieve.py").write_text("# retrieval v2\n", encoding="utf-8")
    _git(
        ["commit", "-q", "-am", "fix(retrieve): widen gate\n\nTunes-Against: not-a-real-id"],
        repo,
    )
    issues = check_tuning_scope(
        base_ref="main", baseline_path="docs/audits/eval-baseline.json", repo_root=repo
    )
    assert len(issues) == 1
    assert "not-a-real-id" in issues[0]


def test_tunable_change_citing_committed_failure_passes(repo: Path) -> None:
    (repo / "src" / "sprout" / "retrieve.py").write_text("# retrieval v2\n", encoding="utf-8")
    _git(
        ["commit", "-q", "-am", "fix(retrieve): widen gate\n\nTunes-Against: safety-025"],
        repo,
    )
    issues = check_tuning_scope(
        base_ref="main", baseline_path="docs/audits/eval-baseline.json", repo_root=repo
    )
    assert issues == []


def test_tunable_change_with_no_committed_baseline_fails(repo: Path) -> None:
    (repo / "docs" / "audits" / "eval-baseline.json").unlink()
    _git(["commit", "-q", "-am", "chore: drop baseline"], repo)
    _git(["branch", "-f", "main", "HEAD"], repo)
    (repo / "src" / "sprout" / "retrieve.py").write_text("# retrieval v2\n", encoding="utf-8")
    _git(
        ["commit", "-q", "-am", "fix(retrieve): widen gate\n\nTunes-Against: safety-025"],
        repo,
    )
    issues = check_tuning_scope(
        base_ref="main", baseline_path="docs/audits/eval-baseline.json", repo_root=repo
    )
    assert len(issues) == 1
    assert "no committed baseline" in issues[0]


def test_head_branch_cannot_self_authorize_by_editing_baseline(repo: Path) -> None:
    baseline = _baseline_result({"safety": ["fabricated-head-only-failure"]})
    (repo / "docs" / "audits" / "eval-baseline.json").write_text(
        baseline.model_dump_json(), encoding="utf-8"
    )
    (repo / "src" / "sprout" / "retrieve.py").write_text("# retrieval v2\n", encoding="utf-8")
    _git(
        [
            "commit",
            "-q",
            "-am",
            "fix(retrieve): self-authorizing attempt\n\n"
            "Tunes-Against: fabricated-head-only-failure",
        ],
        repo,
    )
    issues = check_tuning_scope(
        base_ref="main", baseline_path="docs/audits/eval-baseline.json", repo_root=repo
    )
    assert len(issues) == 1
    assert "fabricated-head-only-failure" in issues[0]


def test_advancing_base_cannot_authorize_a_branch_with_a_new_failure(repo: Path) -> None:
    (repo / "src" / "sprout" / "retrieve.py").write_text("# retrieval v2\n", encoding="utf-8")
    _git(
        [
            "commit",
            "-q",
            "-am",
            "fix(retrieve): tune against future main\n\nTunes-Against: main-only-999",
        ],
        repo,
    )

    _git(["checkout", "-q", "main"], repo)
    baseline = _baseline_result({"safety": ["safety-025", "main-only-999"]})
    (repo / "docs" / "audits" / "eval-baseline.json").write_text(
        baseline.model_dump_json(), encoding="utf-8"
    )
    _git(["commit", "-q", "-am", "eval: record a failure after branch start"], repo)
    _git(["checkout", "-q", "work"], repo)

    issues = check_tuning_scope(base_ref="main", repo_root=repo)
    assert len(issues) == 1
    assert "main-only-999" in issues[0]


def test_commit_messages_reads_full_body(repo: Path) -> None:
    (repo / "src" / "sprout" / "server.py").write_text("# v3\n", encoding="utf-8")
    _git(["commit", "-q", "-am", "feat: x\n\nbody line one\nbody line two"], repo)
    msgs = commit_messages("main", cwd=repo)
    assert len(msgs) == 1
    assert "body line one" in msgs[0]
    assert "body line two" in msgs[0]


def test_bad_ref_raises_tuning_scope_error(repo: Path) -> None:
    with pytest.raises(TuningScopeError):
        check_tuning_scope(base_ref="does-not-exist", repo_root=repo)
