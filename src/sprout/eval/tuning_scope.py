"""Mechanical enforcement of the Phase 3 tuning discipline (docs/ROADMAP.md):

    Tune retrieval/prompts against eval failures only; never the held-out test set.

That rule was previously only a sentence in the roadmap. This module turns it into a gate:
when a change semantically changes the "tunable surface" (retrieval, generation, guards,
calibration, lexical scoring, or their config), at least one commit in the range must carry a
``Tunes-Against: <case-id>[, <case-id>...]`` trailer, and every cited case id must already
be a *committed* failure — i.e. it appears in ``failing_examples`` of the committed
``docs/audits/eval-baseline.json`` produced by ``sprout eval --update-baseline`` before this
branch started. That is the only artifact in the repo that records what the corpus's own
eval already caught, so citing an id from it is the mechanical proxy for "I am tuning
against a known, public eval failure" rather than against a result only visible from a
private/local run or from cases outside the committed suite (the held-out-set discipline the
sentence in the roadmap names).

Deliberately narrow: this cannot stop someone from *looking* at extra cases before writing
the trailer, the same way a coverage gate cannot stop someone from writing a vacuous test.
What it can and does enforce is that every tuning change carries a checkable, falsifiable
citation to a pre-existing committed failure — an auditable trail instead of an assertion.
Comment/format-only YAML and ordinary tunable Python changes, plus the exact named operational
lifecycle wrapper around an otherwise-identical provider constructor, are mechanically normalized.
The initial lifecycle module is admitted once by an exact reviewed digest because it does not
exist at the branch's merge base; every later lifecycle or unknown provider hunk fails closed.
So are the ``Assistant`` methods an eval run never executes (``Assistant.trace``, the ``--debug``
dump): a gate on *eval outcomes* has nothing to say about code the eval never runs, and demanding
a ``Tunes-Against`` citation for it would only be satisfiable by writing a false one.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import yaml

from .runner import RunResult

# Files/directories where a change constitutes "tuning" the assistant's behavior: retrieval
# ranking, generation/prompt assembly, safety/citation guards, calibrated abstention, lexical
# scoring, offline provider heuristics, and the config that drives all of the above.
TUNABLE_SURFACE: tuple[str, ...] = (
    "src/sprout/retrieve.py",
    "src/sprout/answer.py",
    "src/sprout/guards.py",
    "src/sprout/confidence.py",
    "src/sprout/lexical.py",
    "src/sprout/config.py",
    "src/sprout/provider_lifecycle.py",
    "src/sprout/providers/",
    "config/sprout.yaml",
)

_TRAILER_RE = re.compile(r"(?im)^Tunes-Against:\s*(.+)\s*$")
_SEMANTIC_YAML_PATHS = frozenset({"config/sprout.yaml"})
_CONFIG_MODULE_PATH = "src/sprout/config.py"
# Config classes that no eval-visible code path reads: the eval harness drives
# ``Assistant`` directly, and ``Assistant``/retrieval/guards/confidence/providers never
# consult these classes (transport-level knobs consumed only by ``sprout.server`` /
# ``sprout.cli``). A ``config.py`` delta confined to these class bodies therefore cannot
# change any behavior the eval suites measure. The invariant that keeps this exemption
# sound — no eval-visible module ever grows a read of ``config.server`` /
# ``config.observability`` — is pinned by
# ``tests/test_tuning_scope.py::test_eval_visible_modules_never_read_exempt_config``.
# ``CorpusRegistryConfig``/``TrustedPublisher`` (EXP-15) are the same shape: they drive
# ``sprout corpus verify|install`` only, which installs bundle files under
# ``corpus_registry.registry_path`` and never wires them into ``corpus.path``/
# ``corpus.manifest`` — no eval-visible module reads ``config.corpus_registry``.
_EVAL_INVISIBLE_CONFIG_CLASSES = frozenset(
    {
        "ServerConfig",
        "ObservabilityConfig",
        "ReviewConfig",
        "CorpusRegistryConfig",
        "TrustedPublisher",
    }
)
# The same classes' top-level keys in ``config/sprout.yaml``; a YAML delta confined to
# these subtrees is operational for the same reason (and with the same pinned invariant).
_EVAL_INVISIBLE_YAML_KEYS = frozenset({"server", "observability", "review", "corpus_registry"})
_ANSWER_MODULE_PATH = "src/sprout/answer.py"
# ``Assistant`` methods that an eval run never executes. ``sprout eval`` replays the harness
# through ``Assistant.answer`` (``src/sprout/eval/record.py``); ``Assistant.trace`` exists only
# for the ``--debug`` CLI dump and the review-queue record built from it, and nothing under
# ``src/sprout/eval/`` — nor retrieval/guards/confidence/providers — ever calls it. Code inside
# these methods is therefore not merely "eval-invisible" in the sense the config exemption above
# uses: it does not run at all during an eval, so it cannot move an eval outcome, which is the
# only thing this gate exists to constrain. Without this, a fix to the debug trace could be
# merged only by attaching a ``Tunes-Against`` citation that is not true — a gate satisfiable
# only by a false statement is worse than no gate. The invariant that keeps the exemption sound
# is pinned by
# ``tests/test_tuning_scope.py::test_eval_visible_modules_never_call_debug_only_methods``.
_EVAL_INVISIBLE_ASSISTANT_METHODS = frozenset({"trace"})
_PROVIDER_FACTORY_PATH = "src/sprout/providers/__init__.py"
_PROVIDER_LIFECYCLE_PATH = "src/sprout/provider_lifecycle.py"
# One-time bootstrap: origin/main predates the operational lifecycle seam, so the exact
# reviewed initial file is admitted by digest. Once the file exists at the merge base,
# every later hunk is tunable by default; the digest can never exempt an update.
_PROVIDER_LIFECYCLE_BOOTSTRAP_SHA256 = (
    "02e881e5cfd0fa3c2039686281e0049e08e87b2fddc31c70b94c30fe39271ca7"
)
_MAX_COST_EXPR = ast.parse("config.generation.max_cost_usd", mode="eval").body
_GENERATION_CONSTRUCTORS = frozenset({"AnthropicGenerator", "BedrockGenerator"})
_EMBEDDING_CONSTRUCTORS = frozenset({"TitanEmbedding"})


def is_tunable_path(path: str) -> bool:
    """Is ``path`` (repo-relative, as reported by ``git diff --name-only``) tunable surface?"""
    return any(path == entry or path.startswith(entry) for entry in TUNABLE_SURFACE)


def tunable_paths(changed: list[str]) -> list[str]:
    return sorted(p for p in changed if is_tunable_path(p))


class _LifecycleWrapperNormalizer(ast.NodeTransformer):
    """Erase only the mechanically constrained operational wrapper seam.

    The provider constructor, model literal, region, provider branch, and every
    behavior-bearing expression remain in the tree. Unknown calls/imports are retained,
    so their diff fails closed as tuning surface.
    """

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        if (
            node.level == 2
            and node.module == "provider_lifecycle"
            and len(node.names) == 1
            and node.names[0].name in {"observe_embedding", "observe_generation"}
            and node.names[0].asname is None
        ):
            return None
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        visited = self.generic_visit(node)
        if not isinstance(visited, ast.Call) or not isinstance(visited.func, ast.Name):
            return visited
        if len(visited.args) != 1 or not isinstance(visited.args[0], ast.Call):
            return visited
        constructor = visited.args[0]
        if not isinstance(constructor.func, ast.Name):
            return visited
        if (
            visited.func.id == "observe_embedding"
            and constructor.func.id in _EMBEDDING_CONSTRUCTORS
            and not visited.keywords
        ):
            return constructor
        if (
            visited.func.id == "observe_generation"
            and constructor.func.id in _GENERATION_CONSTRUCTORS
            and len(visited.keywords) == 1
            and visited.keywords[0].arg == "max_cost_usd"
            and ast.dump(visited.keywords[0].value, include_attributes=False)
            == ast.dump(_MAX_COST_EXPR, include_attributes=False)
        ):
            return constructor
        return visited


def _provider_factory_fingerprint(source: str) -> str:
    tree = ast.parse(source)
    normalized = _LifecycleWrapperNormalizer().visit(tree)
    ast.fix_missing_locations(normalized)
    return ast.dump(normalized, include_attributes=False)


class _DropEvalInvisibleConfigClasses(ast.NodeTransformer):
    """Erase only the class bodies named in ``_EVAL_INVISIBLE_CONFIG_CLASSES``, plus the
    ``Config`` field lines whose declared type IS one of those classes (adding the class
    without a field on ``Config`` would be dead code; the field line carries no behavior
    beyond wiring the exempt class in).

    Everything else in ``config.py`` — retrieval, generation, guards, prompts,
    confidence — stays in the tree, so a mixed change still fails closed.
    """

    @staticmethod
    def _is_exempt_field(stmt: ast.stmt) -> bool:
        return (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.annotation, ast.Name)
            and stmt.annotation.id in _EVAL_INVISIBLE_CONFIG_CLASSES
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST | None:
        if node.name in _EVAL_INVISIBLE_CONFIG_CLASSES:
            return None
        if node.name == "Config":
            node.body = [stmt for stmt in node.body if not self._is_exempt_field(stmt)] or [
                ast.Pass()
            ]
        return self.generic_visit(node)


class _DropEvalInvisibleAssistantMethods(ast.NodeTransformer):
    """Erase only the ``Assistant`` methods named in ``_EVAL_INVISIBLE_ASSISTANT_METHODS``.

    Everything else in ``answer.py`` — prompt assembly, routing, guard application, confidence,
    and every module-level import and constant — stays in the tree, so a mixed change still
    fails closed. Module-level imports are deliberately *not* dropped: an import added for a
    debug-only method still changes the module the eval executes.
    """

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        if node.name == "Assistant":
            node.body = [
                stmt
                for stmt in node.body
                if not (
                    isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef)
                    and stmt.name in _EVAL_INVISIBLE_ASSISTANT_METHODS
                )
            ] or [ast.Pass()]
        return self.generic_visit(node)


def _answer_without_eval_invisible_methods(source: str) -> str:
    tree = _DropEvalInvisibleAssistantMethods().visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    return ast.dump(tree, include_attributes=False)


def _config_without_eval_invisible_classes(source: str) -> str:
    tree = _DropEvalInvisibleConfigClasses().visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    return ast.dump(tree, include_attributes=False)


def _python_fingerprint(source: str) -> str:
    """Return a formatting- and comment-insensitive Python syntax fingerprint."""

    return ast.dump(ast.parse(source, type_comments=True), include_attributes=False)


def _source_at(ref: str, path: str, *, cwd: str | Path) -> str | None:
    try:
        return _run_git(["show", f"{ref}:{path}"], cwd=cwd)
    except TuningScopeError:
        return None


def _operational_only_change(
    path: str,
    *,
    base_ref: str,
    head_ref: str,
    repo_root: str | Path,
) -> bool:
    head_source = _source_at(head_ref, path, cwd=repo_root)
    if head_source is None:
        return False
    base_source = _source_at(base_ref, path, cwd=repo_root)
    if path == _PROVIDER_LIFECYCLE_PATH:
        return base_source is None and (
            hashlib.sha256(head_source.encode("utf-8")).hexdigest()
            == _PROVIDER_LIFECYCLE_BOOTSTRAP_SHA256
        )
    if base_source is None:
        return False
    if path in _SEMANTIC_YAML_PATHS:
        try:
            base_data, head_data = yaml.safe_load(base_source), yaml.safe_load(head_source)
        except yaml.YAMLError:
            return False
        if base_data == head_data:
            return True
        # A delta confined to eval-invisible top-level keys (server/observability) is
        # operational: drop those subtrees from both sides and require equality on
        # everything else, mirroring the config-class exemption above.
        if isinstance(base_data, dict) and isinstance(head_data, dict):
            base_rest = {k: v for k, v in base_data.items() if k not in _EVAL_INVISIBLE_YAML_KEYS}
            head_rest = {k: v for k, v in head_data.items() if k not in _EVAL_INVISIBLE_YAML_KEYS}
            return base_rest == head_rest
        return False
    fingerprint = _FINGERPRINT_BY_PATH.get(
        path, _python_fingerprint if path.endswith(".py") else None
    )
    if fingerprint is None:
        return False
    try:
        return fingerprint(base_source) == fingerprint(head_source)
    except SyntaxError:
        return False


# Per-path source fingerprints for the equivalence check above. `config.py` exempts only a
# delta confined to eval-invisible config class bodies — outside them the two trees must be
# syntactically identical, so a change that also touches retrieval/generation/guard/prompt
# config still fails closed. `answer.py` is the same shape for the debug-only `Assistant`
# methods an eval run never executes.
_FINGERPRINT_BY_PATH: dict[str, Callable[[str], str]] = {
    _ANSWER_MODULE_PATH: _answer_without_eval_invisible_methods,
    _CONFIG_MODULE_PATH: _config_without_eval_invisible_classes,
    _PROVIDER_FACTORY_PATH: _provider_factory_fingerprint,
}


def effective_tunable_paths(
    changed: list[str],
    *,
    base_ref: str,
    head_ref: str = "HEAD",
    repo_root: str | Path = ".",
) -> list[str]:
    """Tunable paths after narrow, mechanically proven operational equivalence."""

    comparison_base = merge_base(base_ref, head_ref, cwd=repo_root)
    return [
        path
        for path in tunable_paths(changed)
        if not _operational_only_change(
            path, base_ref=comparison_base, head_ref=head_ref, repo_root=repo_root
        )
    ]


def _run_git(args: list[str], *, cwd: str | Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise TuningScopeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


class TuningScopeError(RuntimeError):
    """Raised when the check cannot even be evaluated (bad refs, missing git, etc.)."""


def merge_base(base_ref: str, head_ref: str = "HEAD", *, cwd: str | Path = ".") -> str:
    """Commit where this branch diverged, used for both diff and authorization evidence."""

    value = _run_git(["merge-base", base_ref, head_ref], cwd=cwd).strip()
    if not value:
        raise TuningScopeError(f"git merge-base {base_ref} {head_ref} returned no commit")
    return value


def changed_files(base_ref: str, head_ref: str = "HEAD", *, cwd: str | Path = ".") -> list[str]:
    """Files touched by ``head_ref`` relative to their merge-base with ``base_ref``."""
    out = _run_git(["diff", "--name-only", f"{base_ref}...{head_ref}"], cwd=cwd)
    return [line for line in out.splitlines() if line.strip()]


def commit_messages(base_ref: str, head_ref: str = "HEAD", *, cwd: str | Path = ".") -> list[str]:
    """Full messages of every commit in ``head_ref`` not reachable from ``base_ref``."""
    out = _run_git(["log", f"{base_ref}..{head_ref}", "--format=%B%x00"], cwd=cwd)
    return [msg for msg in out.split("\x00") if msg.strip()]


def referenced_case_ids(messages: list[str]) -> set[str]:
    """Case ids cited via a ``Tunes-Against:`` trailer across a set of commit messages."""
    ids: set[str] = set()
    for msg in messages:
        for match in _TRAILER_RE.finditer(msg):
            ids.update(part.strip() for part in match.group(1).split(",") if part.strip())
    return ids


def committed_failing_ids(baseline_path: str | Path) -> set[str]:
    """Every ``item_id`` recorded as a failing example in the committed eval baseline."""
    baseline = RunResult.model_validate_json(Path(baseline_path).read_text(encoding="utf-8"))
    return _failing_ids(baseline)


def _failing_ids(baseline: RunResult) -> set[str]:
    return {
        outcome.item_id for suite in baseline.suite_results for outcome in suite.failing_examples
    }


def check_tuning_scope(
    *,
    base_ref: str,
    head_ref: str = "HEAD",
    baseline_path: str | Path = "docs/audits/eval-baseline.json",
    repo_root: str | Path = ".",
) -> list[str]:
    """Return violation messages; an empty list means the change is in scope (or n/a).

    No violations are possible when the diff does not touch ``TUNABLE_SURFACE`` at all —
    the gate only fires on the changes it is meant to constrain.
    """
    branch_base = merge_base(base_ref, head_ref, cwd=repo_root)
    changed = changed_files(branch_base, head_ref, cwd=repo_root)
    tunable = effective_tunable_paths(
        changed, base_ref=branch_base, head_ref=head_ref, repo_root=repo_root
    )
    if not tunable:
        return []

    messages = commit_messages(branch_base, head_ref, cwd=repo_root)
    cited = referenced_case_ids(messages)
    if not cited:
        return [
            "this change touches tunable surface ("
            + ", ".join(tunable)
            + ") but no commit in range carries a `Tunes-Against: <case-id>[, <case-id>...]` "
            "trailer. docs/ROADMAP.md (Phase 3) requires tuning to be justified against an "
            "already-committed eval failure, never the held-out set."
        ]

    baseline_ref = f"{branch_base}:{Path(baseline_path).as_posix()}"
    try:
        baseline_json = _run_git(["show", baseline_ref], cwd=repo_root)
    except TuningScopeError:
        return [
            f"this change touches tunable surface but no committed baseline exists at "
            f"{baseline_ref} to verify the `Tunes-Against` ids against — run "
            "`sprout eval --update-baseline` and commit it first."
        ]

    try:
        known_failures = _failing_ids(RunResult.model_validate_json(baseline_json))
    except ValueError as exc:
        raise TuningScopeError(f"committed baseline {baseline_ref} is malformed: {exc}") from exc
    unknown = sorted(cited - known_failures)
    if unknown:
        return [
            "`Tunes-Against` cites case id(s) not present in "
            f"{baseline_ref}'s committed failing_examples: {', '.join(unknown)}. "
            "Tuning must target a failure that was already committed to the eval baseline, "
            "not a case only observed via a local or held-out run."
        ]
    return []
