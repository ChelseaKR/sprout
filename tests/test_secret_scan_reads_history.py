"""The secret scan has to read every commit, not the commit it was handed.

The ``security`` job in ``.github/workflows/ci.yml`` is one of ``ci-gate``'s ``needs:``,
and ``ci-gate`` is the only required status check on ``main``. Until 2026-09-13 that job's
secret scan was ``gitleaks/gitleaks-action``, which picks its range from the triggering
event:

    push, N commits   gitleaks detect --log-opts=--no-merges --first-parent BASE^..HEAD
    push, 1 commit    gitleaks detect --log-opts=-1            <- exactly one commit
    pull_request      the pull request's own commits
    schedule /
    workflow_dispatch no --log-opts at all, i.e. the whole history

This workflow triggers on ``push`` and ``pull_request`` only — it has neither of the two
events for which the action reads history — and every squash merge into ``main`` is a
one-commit push. So the merge gate read 1 of ``main``'s 146 commits, and no lane in this
repository had ever read more. A credential added in one commit and deleted in the next
was invisible to it, in exactly the run that decided whether a branch could merge.

``fetch-depth: 0`` did not prevent that and could not: it decides how much history
``actions/checkout`` puts on **disk**, not how much of it the scanner is asked to read. A
checkout deep enough to scan and an invocation that declines to is precisely the state
this job was in. So the assertions below are about the *invocation*; the ``fetch-depth``
assertion is kept as the necessary precondition it actually is, and nothing more.

Measured on a throwaway clone of this repository (remote removed, nothing pushed): a
random, real-shaped AWS key planted in one commit and deleted in the next left
``gitleaks git . --log-opts=-1`` exiting 0 while ``gitleaks git .`` exited 1, over the
same 146-commit history.

``gitleaks git .`` walks ``git log --full-history --all``, not only what HEAD reaches, so
the count CI prints is the whole clone ``fetch-depth: 0`` produced and will exceed
``main``'s own 146. Measured, not assumed: in a scratch repository whose HEAD reaches one
commit and whose side branch holds a second, it reports "2 commits scanned" and finds the
key on the branch.

``tests/test_secret_scanning.py`` is the other half of this — it proves the committed
``.gitleaks.toml`` has rules at all.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"

_SCAN_JOB = "security"
_SCAN_INVOCATION = "gitleaks git . --no-banner --redact --exit-code 1"

#: Four conformance checks elsewhere in this portfolio passed because they matched a tool
#: name inside a COMMENT. The comment above the scan step in ``ci.yml`` names both the
#: action that was removed and the flag that must not return, so every substring assertion
#: here reads the file with its comments stripped and cannot be satisfied by prose.
_COMMENT = re.compile(r"(?m)^\s*#.*$|\s+#.*$")


def _ci_code() -> str:
    return _COMMENT.sub("", _CI.read_text(encoding="utf-8"))


def _ci_yaml() -> dict[str, Any]:
    loaded = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _scan_job() -> dict[str, Any]:
    job = _ci_yaml()["jobs"][_SCAN_JOB]
    assert isinstance(job, dict)
    return job


def _scan_step() -> dict[str, Any]:
    steps = [
        step
        for step in _scan_job()["steps"]
        if isinstance(step.get("run"), str) and "gitleaks" in step["run"]
    ]
    assert len(steps) == 1, f"expected exactly one gitleaks step in `{_SCAN_JOB}`, found {steps}"
    step: dict[str, Any] = steps[0]
    return step


def test_the_comment_stripper_actually_strips() -> None:
    """Without this the checks below could all be passing on prose.

    The workflow comment deliberately writes out `gitleaks/gitleaks-action` and
    `--log-opts` so a reader learns what was wrong. Both strings are what the absence
    assertions forbid, so they have to be gone before those assertions mean anything.
    """
    raw = _CI.read_text(encoding="utf-8")
    assert "gitleaks/gitleaks-action" in raw and "--log-opts" in raw, (
        "the workflow no longer explains what it replaced; the assertions below would "
        "then pass for a reason unrelated to the comment stripper working"
    )
    assert "gitleaks/gitleaks-action" not in _ci_code()
    assert "--log-opts" not in _ci_code()


def test_the_scanner_is_not_handed_a_range() -> None:
    text = _ci_code()
    assert _SCAN_INVOCATION in text, (
        "the secret scan no longer runs `gitleaks git .`. Whatever replaces it must still "
        "walk the whole history — `git log --full-history --all` — on every event."
    )
    assert "--log-opts" not in text, (
        "`--log-opts` scopes gitleaks to a commit range. A range chosen from the "
        "triggering event is how this check came to read 1 of main's 146 commits."
    )


def test_the_event_driven_action_does_not_come_back() -> None:
    assert "gitleaks/gitleaks-action" not in _ci_code(), (
        "gitleaks/gitleaks-action picks its range from the event and degrades to "
        "`--log-opts=-1` on a single-commit push, which is every squash merge here"
    )


def test_the_scan_is_not_conditioned_on_the_event() -> None:
    """The defect in its other form: a history scan only some triggers get.

    An `if:` on this step (`github.event_name == 'schedule'` is the usual shape) would
    put the repository back where it started — a merge gate whose secret scan reads a
    range the event chose, with the full scan happening on some other lane, or on none,
    since this workflow has no `schedule` trigger at all.
    """
    step = _scan_step()
    assert "if" not in step, f"the secret-scan step is conditional: {step['if']!r}"
    assert "if" not in _scan_job(), f"the `{_SCAN_JOB}` job is conditional: {_scan_job()['if']!r}"


def test_the_scan_still_backs_the_required_check() -> None:
    """A full-history scan in a job nothing requires blocks nothing."""
    needs = _ci_yaml()["jobs"]["ci-gate"]["needs"]
    assert _SCAN_JOB in needs, (
        f"`{_SCAN_JOB}` is no longer in ci-gate's needs, so the secret scan no longer gates a merge"
    )


def test_checkout_still_fetches_the_history_the_scan_walks() -> None:
    """Necessary, not sufficient: without it there is nothing on disk to walk.

    Asserted on this job's own checkout rather than anywhere in the file — `ci.yml` has
    several `fetch-depth: 0` steps for unrelated reasons, and any of them would satisfy
    a whole-file match while this one was quietly dropped.
    """
    checkouts = [
        step
        for step in _scan_job()["steps"]
        if isinstance(step.get("uses"), str) and step["uses"].startswith("actions/checkout@")
    ]
    assert len(checkouts) == 1, checkouts
    assert checkouts[0].get("with", {}).get("fetch-depth") == 0, (
        "`fetch-depth: 0` is gone from the secret-scan checkout, so `gitleaks git .` "
        "would walk the single commit actions/checkout fetched. This is the precondition "
        "for a history scan; the invocation is what makes it one."
    )


def test_the_pinned_binary_is_checksum_verified() -> None:
    """A `curl | tar` with no checksum is a supply-chain step, not a security step."""
    text = _ci_code()
    assert "gitleaks_checksums.txt" in text and "sha256sum --check --strict" in text, (
        "the gitleaks binary is downloaded without verifying its published checksum"
    )
