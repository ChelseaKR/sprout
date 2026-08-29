"""The secret scanner has to be able to find a secret.

gitleaks treats a ``.gitleaks.toml`` it finds as the *whole* configuration. A file
that declares only an ``[allowlist]``, with no ``[extend] useDefault = true``, leaves
the scanner with no rules at all: it reports "no leaks found" on every input, in
``make security``, in the ``gitleaks/gitleaks-action`` CI job, and in the pre-commit
hook, because there is nothing it can match. That is what this repository shipped
until 2026-08-28, and nothing noticed, because a scanner with no rules and a clean
repository produce identical output.

These tests are the difference. One reads the committed config; the other plants a
synthetic credential and asserts the committed config finds it. Where gitleaks is not
installed the second is skipped, never passed: a machine that cannot run the scanner
has not proved the scanner works.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = _ROOT / ".gitleaks.toml"

#: A syntactically valid, entirely synthetic GitHub personal access token: the literal
#: prefix plus 36 characters, which is the shape gitleaks' default `github-pat` rule
#: matches. It authenticates nothing and never existed.
_SYNTHETIC_TOKEN = "ghp_" + "S9kQ2mVx7Tb4LpZ0nHf6WdRj1CyG8AuEoI3M"


def test_the_gitleaks_config_extends_the_default_rule_set() -> None:
    """Without this, the config below is the entire rule set, and it has no rules."""
    config = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))
    assert config.get("extend", {}).get("useDefault") is True, (
        "`.gitleaks.toml` must set `[extend] useDefault = true`; a config without it "
        "replaces gitleaks' default rules rather than adding to them, leaving the "
        "scanner with zero detectors and a permanently green secret gate"
    )


def test_the_allowlist_names_paths_and_not_whole_rules() -> None:
    """An allowlist is a claim that specific files are not credentials.

    Allowlisting by path keeps the claim narrow and reviewable. Disabling a rule, or
    allowlisting a regex, would suppress that detector everywhere including in files
    nobody has looked at, which is the failure mode this file exists to prevent.
    """
    config = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))
    allowlist = config.get("allowlist", {})
    assert set(allowlist) <= {"description", "paths"}, sorted(allowlist)
    assert allowlist["paths"], "an empty allowlist should be removed, not left in place"
    for entry in allowlist["paths"]:
        assert (_ROOT / entry).exists(), f"allowlisted path no longer exists: {entry}"


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_the_committed_config_finds_a_planted_credential(tmp_path: Path) -> None:
    """The proof, run against the config this repository actually ships.

    A scanner is only trusted after it has been shown finding something. This plants a
    synthetic token in a scratch directory, points gitleaks at it with the committed
    config, and asserts a nonzero exit and a report naming the file.
    """
    shutil.copy(_CONFIG, tmp_path / ".gitleaks.toml")
    (tmp_path / "planted.txt").write_text(f"token = {_SYNTHETIC_TOKEN}\n", encoding="utf-8")
    report = tmp_path / "report.json"

    completed = subprocess.run(
        [
            "gitleaks",
            "detect",
            "--no-git",
            "--no-banner",
            "--source",
            str(tmp_path),
            "--config",
            str(tmp_path / ".gitleaks.toml"),
            "--report-format",
            "json",
            "--report-path",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0, (
        "gitleaks exited 0 on a directory holding a well-formed GitHub token: the "
        f"committed config is not loading any rules.\n{completed.stderr}"
    )
    findings = json.loads(report.read_text(encoding="utf-8"))
    assert [Path(f["File"]).name for f in findings] == ["planted.txt"], findings
    assert [f["RuleID"] for f in findings] == ["github-pat"], findings


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_a_directory_with_no_credential_is_reported_clean(tmp_path: Path) -> None:
    """The other direction, so the test above cannot pass against a scanner that
    fails on everything it is pointed at."""
    shutil.copy(_CONFIG, tmp_path / ".gitleaks.toml")
    (tmp_path / "ordinary.txt").write_text("water the monstera weekly\n", encoding="utf-8")
    completed = subprocess.run(
        [
            "gitleaks",
            "detect",
            "--no-git",
            "--no-banner",
            "--source",
            str(tmp_path),
            "--config",
            str(tmp_path / ".gitleaks.toml"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
