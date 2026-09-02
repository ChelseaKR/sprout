"""The security target has to be able to fail, and has to read everything.

Two defects this file exists to keep out, both measured on 2026-08-28:

* The gitleaks step was written ``command -v gitleaks && gitleaks detect || fallback``.
  A gitleaks that finds a secret exits 1 exactly like a gitleaks that is not installed,
  so a real finding took the fallback branch: the recipe printed "gitleaks not installed
  locally" and exited 0. Verified by putting a stub gitleaks on ``PATH`` that reported
  ``leaks found: 1`` and exited 1.

* ``semgrep scan --config p/python --error src`` named one directory. 62 of the
  repository's 142 tracked Python files, including the gate machinery under ``scripts/``,
  had never been read by any SAST pass.

Both are shape properties of the Makefile and the workflow, so both are checked by
reading them. ``sprout ci-parity-check`` already diffs the two sides against each other;
it cannot tell whether the command they agree on is the right one, which is what this
adds.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_MAKEFILE = _ROOT / "Makefile"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"

#: Directories that must be inside the SAST scan, derived from where tracked Python
#: actually lives rather than typed out, so a new source root fails this instead of
#: quietly going unscanned.
_EXCLUDED_FROM_SAST: frozenset[str] = frozenset()


def _tracked_python_roots() -> set[str]:
    listed = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    roots = {line.split("/", 1)[0] for line in listed.stdout.splitlines() if "/" in line}
    return roots - _EXCLUDED_FROM_SAST


def _makefile_sast_paths() -> list[str]:
    match = re.search(r"^SAST_PATHS\s*:=\s*(.+)$", _MAKEFILE.read_text(encoding="utf-8"), re.M)
    assert match, "Makefile no longer declares SAST_PATHS"
    return match.group(1).split()


def _ci_semgrep_paths() -> list[str]:
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    commands = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step.get("run"), str) and "semgrep scan" in step["run"]
    ]
    assert len(commands) == 1, f"expected exactly one semgrep step in ci.yml, found {commands}"
    after = str(commands[0]).split("--error", 1)[1]
    return after.split()


def test_semgrep_reads_every_directory_that_holds_tracked_python() -> None:
    roots = _tracked_python_roots()
    assert roots, "git ls-files found no Python at all; this check would pass vacuously"
    missing = roots - set(_makefile_sast_paths())
    assert not missing, (
        f"{sorted(missing)} hold tracked Python and are not in the Makefile's SAST_PATHS, "
        "so no SAST pass reads them"
    )


def test_the_makefile_and_ci_scan_the_same_paths() -> None:
    assert _makefile_sast_paths() == _ci_semgrep_paths()


def test_the_semgrepignore_does_not_exclude_a_path_the_gate_claims_to_scan() -> None:
    """Naming a directory on the command line is not the same as scanning it.

    semgrep ships a default `.semgrepignore` that excludes `tests/` and `test/`, and a
    repository's own file replaces that default rather than adding to it. Measured on
    2026-08-28: `semgrep scan --config p/python --error tests` reported success having
    scanned **0 files** while the default was in force. So the committed
    `.semgrepignore` is load-bearing, and it must not re-exclude anything SAST_PATHS
    names.
    """
    ignore = _ROOT / ".semgrepignore"
    assert ignore.is_file(), (
        "without a committed .semgrepignore, semgrep's default excludes tests/ and the "
        "gate scans none of it while reporting success"
    )
    patterns = [
        line.strip()
        for line in ignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert patterns, ".semgrepignore has no patterns; delete it rather than shadowing the default"
    for path in _makefile_sast_paths():
        for pattern in patterns:
            head = pattern.rstrip("/").split("/", 1)[0]
            assert head != path, f".semgrepignore excludes {pattern!r}, which SAST_PATHS scans"


def test_the_gitleaks_step_does_not_route_a_finding_into_the_fallback() -> None:
    """A finding and a missing binary must not share an exit path.

    The specific shape banned here is `command -v gitleaks && gitleaks ... || <fallback>`,
    where the fallback claims the tool is absent. Any construct that decides on the
    install check alone is fine; deciding on the *combined* status is not.
    """
    recipe = _security_recipe()
    joined = " ".join(recipe.split())
    assert "gitleaks detect" in joined, "the security target no longer runs gitleaks"
    assert not re.search(r"command -v gitleaks[^\n]*&&[^\n]*gitleaks detect[^\n]*\|\|", joined), (
        "the gitleaks scan and the install check share one `&& ... ||` chain again: a "
        "gitleaks that finds a secret exits 1, takes the fallback branch, and the target "
        "goes green while announcing that gitleaks is not installed"
    )


def test_the_security_target_carries_no_blanket_bypass() -> None:
    recipe = _security_recipe()
    for bypass in ("|| true", "|| :", "- gitleaks", "--exit-zero"):
        assert bypass not in recipe, f"{bypass!r} would make the security target unfailable"


def _security_recipe() -> str:
    text = _MAKEFILE.read_text(encoding="utf-8")
    start = text.index("\nsecurity:")
    rest = text[start + 1 :]
    end = re.search(r"\n(?=[A-Za-z_-]+:)", rest)
    return rest[: end.start()] if end else rest


def test_make_parses_the_makefile_without_overriding_a_target() -> None:
    """A target defined twice silently loses one recipe.

    ``corpus-report`` was defined twice; make kept the second and discarded the first,
    which was the one carrying ``--config $(CONFIG)``. The warning was printed on every
    invocation of every target, including inside ``make verify``, and read as noise.
    """
    completed = subprocess.run(
        ["make", "-n", "--warn-undefined-variables", "help"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "overriding commands for target" not in completed.stderr, completed.stderr
    assert "ignoring old commands for target" not in completed.stderr, completed.stderr
