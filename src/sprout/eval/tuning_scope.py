"""Mechanical enforcement of the Phase 3 tuning discipline (docs/ROADMAP.md):

    Tune retrieval/prompts against eval failures only; never the held-out test set.

That rule was previously only a sentence in the roadmap. This module turns it into a gate:
when a change touches the "tunable surface" (retrieval, generation, guards, calibration,
lexical scoring, or their config), at least one commit in the range must carry a
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
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

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
    "src/sprout/providers/",
    "config/sprout.yaml",
)

_TRAILER_RE = re.compile(r"(?im)^Tunes-Against:\s*(.+)\s*$")


def is_tunable_path(path: str) -> bool:
    """Is ``path`` (repo-relative, as reported by ``git diff --name-only``) tunable surface?"""
    return any(path == entry or path.startswith(entry) for entry in TUNABLE_SURFACE)


def tunable_paths(changed: list[str]) -> list[str]:
    return sorted(p for p in changed if is_tunable_path(p))


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
    changed = changed_files(base_ref, head_ref, cwd=repo_root)
    tunable = tunable_paths(changed)
    if not tunable:
        return []

    messages = commit_messages(base_ref, head_ref, cwd=repo_root)
    cited = referenced_case_ids(messages)
    if not cited:
        return [
            "this change touches tunable surface ("
            + ", ".join(tunable)
            + ") but no commit in range carries a `Tunes-Against: <case-id>[, <case-id>...]` "
            "trailer. docs/ROADMAP.md (Phase 3) requires tuning to be justified against an "
            "already-committed eval failure, never the held-out set."
        ]

    baseline_ref = f"{base_ref}:{Path(baseline_path).as_posix()}"
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
