"""Mechanical invocation-diff between ``make verify`` and the required ``ci-gate`` checks.

``CONTRIBUTING.md`` asserts that ``make verify`` gives "tool-for-tool parity" with the CI jobs
that back the single required ``ci-gate`` status check: CI runs the same commands, just inlined
into workflow steps instead of shelled out through ``make``. Until this module existed that claim
was checked by hand (a human re-reading both files side by side) — nothing caught it if a command
was added to one side and forgotten on the other. `ROADMAP.md` tracked the gap as
``ci-parity-no-mechanical-diff``.

This module parses ``.github/workflows/ci.yml`` and the ``Makefile``, normalizes each side's
shell commands to a comparable form, and reports any command present on one side with no
counterpart on the other — except for a short, explicitly documented allowlist of intentional
one-sided steps (a packaging smoke-build, environment-sync steps, and gitleaks, which CI runs
as a GitHub Action rather than a shell command).

Wired in two places so drift is caught automatically rather than re-relying on a human noticing:

- ``make ci-parity-check`` (also a prerequisite of ``make verify``, so it runs locally too).
- the ``ci-parity`` job in ``.github/workflows/ci.yml``, itself a dependency of ``ci-gate``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# CI jobs that back the required `ci-gate` check and are expected to have a `make verify`
# counterpart, mapped to the Makefile target(s) whose recipe should cover the same commands.
# `pa11y` and `lighthouse` are excluded on purpose: they are browser-based a11y jobs (Node +
# headless Chrome — `npx pa11y-ci` / `npx lighthouse`) that are merge-blocking in CI but have no
# `make verify` counterpart; the local structural equivalent is `make a11y` (`sprout a11y-check`),
# and CONTRIBUTING.md documents this as the one deliberate parity exception. `zizmor` has no
# mapping here because it is
# compared separately (see `ZIZMOR_JOB` / `ZIZMOR_TARGET` below) — its only step is a `uses:`
# action-adjacent CLI invocation with no per-job Makefile split.
JOB_TO_MAKE_TARGETS: dict[str, tuple[str, ...]] = {
    "test": ("lint", "type", "test"),
    "security": ("security",),
    "eval-a11y": ("ingest", "eval", "a11y", "claims", "calibrate", "gate-inventory", "slo", "corpus-report"),
    "smoke": ("ingest", "smoke"),
    "docs": ("docs",),
}

ZIZMOR_JOB = "zizmor"
ZIZMOR_TARGET = "workflow-lint"

# Commands that legitimately exist only in CI, with the reason it is not also required locally.
ALLOWED_CI_ONLY = {
    # CQ-10 packaging regression check: proves the sdist/wheel build, not a code-quality gate;
    # redundant to run on every local `make verify` invocation.
    "uv build",
}

# Commands (by prefix) that legitimately exist only in the Makefile.
ALLOWED_MAKE_ONLY_PREFIXES = (
    # `gitleaks` runs as a GitHub Action in CI (`gitleaks/gitleaks-action`), not a shell command,
    # so it never appears as a `run:` step to diff against. The Makefile recipe documents the
    # same fallback inline (see CONTRIBUTING.md's "CI parity" note).
    "command -v gitleaks",
)

# Environment-setup commands are not "tools/thresholds" in the CONTRIBUTING.md sense — both
# sides install dependencies before running the gates, but with different flags (CI uses
# `--frozen` for reproducibility; local dev does not need to). Excluded from the diff entirely.
_SETUP_PREFIXES = ("uv sync",)


@dataclass(frozen=True)
class ParityReport:
    """One group's (CI job vs. Makefile target set) invocation diff."""

    group: str
    ci_only: tuple[str, ...] = field(default_factory=tuple)
    make_only: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.ci_only and not self.make_only


def _resolve_make_vars(text: str) -> dict[str, str]:
    """Pull the handful of Makefile variables our commands reference."""
    variables: dict[str, str] = {}
    py_match = re.search(r"^PY\s*:=\s*(.+)$", text, re.MULTILINE)
    variables["PY"] = py_match.group(1).strip() if py_match else "uv run"
    config_match = re.search(r"^CONFIG\s*\?=\s*(.+)$", text, re.MULTILINE)
    variables["CONFIG"] = config_match.group(1).strip() if config_match else "config/sprout.yaml"
    return variables


def _make_target_recipes(makefile_text: str) -> dict[str, list[str]]:
    """Map each Makefile target name to its raw (still tab-indented-stripped) recipe lines."""
    recipes: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in makefile_text.splitlines():
        if raw_line.startswith("\t"):
            if current is not None:
                recipes.setdefault(current, []).append(raw_line[1:])
            continue
        header = re.match(r"^([A-Za-z0-9_-]+)\s*:(?!=)", raw_line)
        current = header.group(1) if header else None
    return recipes


def _join_continuations(lines: list[str]) -> list[str]:
    """Join Makefile recipe lines split across `\\`-continuations into single logical commands."""
    joined: list[str] = []
    buf: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n")
        if stripped.endswith("\\"):
            buf.append(stripped[:-1].strip())
        else:
            buf.append(stripped.strip())
            joined.append(" ".join(part for part in buf if part))
            buf = []
    if buf:
        joined.append(" ".join(part for part in buf if part))
    return joined


def _normalize(cmd: str, make_vars: dict[str, str] | None = None) -> str:
    """Canonicalize one shell command so equivalent CI/Makefile invocations compare equal."""
    text = cmd.strip()
    if text.startswith("@"):
        text = text[1:].strip()
    if make_vars:
        text = text.replace("$(PY)", make_vars["PY"]).replace("$(CONFIG)", make_vars["CONFIG"])
        # `--config <default>` is equivalent to omitting `--config` (the CLI default matches the
        # Makefile default; see `test_cli_default_config_matches_makefile_default`), so a run
        # with the explicit default flag reads the same as a run without it.
        text = re.sub(rf"\s+--config\s+{re.escape(make_vars['CONFIG'])}\b", "", text)
        # The release-only trend-ledger flag (EXP-13) is appended through a make
        # conditional that expands to *nothing* unless RELEASE_TAG is set, and only the
        # release workflow sets it. Parity compares the per-PR/per-push invocation, where
        # both sides run without the flag, so the unexpanded conditional is erased here.
        text = text.replace("$(if $(RELEASE_TAG),--release '$(RELEASE_TAG)')", "")
    return re.sub(r"\s+", " ", text).strip()


def make_target_commands(makefile_text: str, target: str) -> set[str]:
    """The normalized command set for one Makefile target's own recipe (no prereq expansion)."""
    make_vars = _resolve_make_vars(makefile_text)
    recipes = _make_target_recipes(makefile_text)
    lines = _join_continuations(recipes.get(target, []))
    commands = {_normalize(line, make_vars) for line in lines if line.strip()}
    return {c for c in commands if c and not c.startswith("echo") and not _is_setup(c)}


def _is_setup(cmd: str) -> bool:
    return any(cmd.startswith(prefix) for prefix in _SETUP_PREFIXES)


def ci_job_commands(ci_yaml: dict[str, object], job: str) -> set[str]:
    """The normalized command set for one CI job's `run:` steps."""
    jobs = ci_yaml.get("jobs", {})
    assert isinstance(jobs, dict)
    job_def = jobs.get(job, {})
    assert isinstance(job_def, dict)
    steps = job_def.get("steps", [])
    assert isinstance(steps, list)
    commands: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        run = step.get("run")
        if not isinstance(run, str):
            continue
        for line in run.splitlines():
            norm = _normalize(line)
            if norm and not _is_setup(norm):
                commands.add(norm)
    return commands


def diff_group(group: str, ci_commands: set[str], make_commands: set[str]) -> ParityReport:
    ci_only = {c for c in (ci_commands - make_commands) if c not in ALLOWED_CI_ONLY}
    make_only = {
        c
        for c in (make_commands - ci_commands)
        if not any(c.startswith(p) for p in ALLOWED_MAKE_ONLY_PREFIXES)
    }
    return ParityReport(
        group=group, ci_only=tuple(sorted(ci_only)), make_only=tuple(sorted(make_only))
    )


def check_parity(workflow_path: Path, makefile_path: Path) -> list[ParityReport]:
    """Diff every mapped CI job against its Makefile target(s); one report per job."""
    ci_yaml = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    makefile_text = makefile_path.read_text(encoding="utf-8")

    reports: list[ParityReport] = []
    for job, targets in JOB_TO_MAKE_TARGETS.items():
        make_commands: set[str] = set()
        for target in targets:
            make_commands |= make_target_commands(makefile_text, target)
        reports.append(diff_group(job, ci_job_commands(ci_yaml, job), make_commands))

    reports.append(
        diff_group(
            ZIZMOR_JOB,
            ci_job_commands(ci_yaml, ZIZMOR_JOB),
            make_target_commands(makefile_text, ZIZMOR_TARGET),
        )
    )
    return reports


def format_reports(reports: list[ParityReport]) -> str:
    lines: list[str] = []
    for report in reports:
        if report.ok:
            lines.append(f"OK    {report.group}")
            continue
        lines.append(f"DRIFT {report.group}")
        for c in report.ci_only:
            lines.append(f"      CI runs, `make verify` does not:      {c}")
        for c in report.make_only:
            lines.append(f"      `make verify` runs, CI does not:      {c}")
    return "\n".join(lines)
