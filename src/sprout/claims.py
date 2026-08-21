"""Claims-integrity gate: every numeric/policy doc claim checked against its code/config
source of truth.

Docs drift from the systems they describe. ``docs/claims.yaml`` registers each claim (a doc
site, an ``expected`` value, and where that value truly comes from); :func:`check` resolves
the live source of truth and greps the doc near an explicit ``<!-- claim:ID -->`` marker for
the expected text. Markers keep extraction robust to prose rewording — the check never parses
English, only confirms a pinned marker's neighborhood still contains the value it claims.
Mirrors the ``check_html`` / ``sprout a11y-check`` pattern in :mod:`sprout.a11y`: a pure
function that returns a list of problem strings, wired to a CLI command and a CI/Makefile gate.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import Config, load_config
from .eval.calibration import MIN_AGREEMENT, MIN_KAPPA
from .eval.suites.refusal import RefusalSuite

_DEFAULT_CLAIMS = "docs/claims.yaml"
_DEFAULT_CONFIG = "config/sprout.yaml"
_DEFAULT_EVAL_REPORT = "docs/audits/eval-report.json"
_DEFAULT_PYPROJECT = "pyproject.toml"

_CONTEXT_LINES = 1  # how many lines above/below the marker line the value may appear on


class ClaimsError(ValueError):
    """Raised for a malformed claims registry or an unresolvable claim source."""


@dataclass(frozen=True)
class Claim:
    """One registered doc claim: a doc site, its marker, and its source of truth."""

    id: str
    file: str
    source: str
    expected: str
    marker: str


def _load_claims(path: str | Path) -> list[Claim]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"claims registry not found: {p}")
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("claims"), list):
        raise ClaimsError(f"{p}: expected a top-level 'claims' list")
    claims: list[Claim] = []
    for i, entry in enumerate(raw["claims"]):
        if not isinstance(entry, dict):
            raise ClaimsError(f"{p}: claims[{i}] is not a mapping")
        try:
            claim_id = str(entry["id"])
            claims.append(
                Claim(
                    id=claim_id,
                    file=str(entry["file"]),
                    source=str(entry["source"]),
                    expected=str(entry["expected"]),
                    marker=str(entry.get("marker", f"<!-- claim:{claim_id} -->")),
                )
            )
        except KeyError as exc:
            raise ClaimsError(f"{p}: claims[{i}] missing required key {exc}") from exc
    return claims


def _fmt(value: Any) -> str:
    """Render a resolved value the way the docs write it (0.90, not 0.9; AA, not 'AA')."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _resolve_config(dotted: str, config_path: str | Path) -> str:
    p = Path(config_path)
    cfg: Config = load_config(p) if p.exists() else Config()
    obj: Any = cfg
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return _fmt(obj)


def _resolve_suite(name: str) -> str:
    if name == "refusal.threshold":
        return _fmt(RefusalSuite().metric.threshold)
    if name == "calibration.min_agreement":
        return _fmt(MIN_AGREEMENT)
    if name == "calibration.min_kappa":
        return _fmt(MIN_KAPPA)
    raise ClaimsError(f"unknown suite claim source: {name!r}")


def _load_eval_report(report_path: str | Path) -> Any:
    p = Path(report_path)
    if not p.exists():
        raise FileNotFoundError(f"eval report not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _resolve_eval_report(dotted: str, report_path: str | Path) -> str:
    report = _load_eval_report(report_path)
    suite_name, _, rest = dotted.partition(".")
    suites = report.get("suite_results", [])
    match = next((s for s in suites if s.get("suite") == suite_name), None)
    if match is None:
        raise ClaimsError(f"no suite_results entry for suite {suite_name!r} in {report_path}")
    obj: Any = match
    for part in rest.split("."):
        obj = obj[part]
    return _fmt(obj)


def _resolve_eval_report_suite_names(report_path: str | Path) -> str:
    """Comma-joined suite names, in report order — e.g. the eval-report.md header line."""
    report = _load_eval_report(report_path)
    names = [s.get("suite") for s in report.get("suite_results", [])]
    return ", ".join(str(n) for n in names)


def _resolve_eval_report_suite_count(report_path: str | Path) -> str:
    report = _load_eval_report(report_path)
    return _fmt(len(report.get("suite_results", [])))


def _resolve_pytest_cov_fail_under(pyproject_path: str | Path) -> str:
    p = Path(pyproject_path)
    if not p.exists():
        raise FileNotFoundError(f"pyproject.toml not found: {p}")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    addopts = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("addopts", "")
    match = re.search(r"--cov-fail-under=(\d+)", addopts)
    if match is None:
        raise ClaimsError(f"no --cov-fail-under found in {pyproject_path}'s pytest addopts")
    return _fmt(int(match.group(1)))


def _resolve(
    source: str,
    config_path: str | Path,
    eval_report_path: str | Path,
    pyproject_path: str | Path = _DEFAULT_PYPROJECT,
) -> str:
    if source.startswith("config:"):
        return _resolve_config(source.removeprefix("config:"), config_path)
    if source.startswith("suite:"):
        return _resolve_suite(source.removeprefix("suite:"))
    if source == "eval-report:suites.names":
        return _resolve_eval_report_suite_names(eval_report_path)
    if source == "eval-report:suites.count":
        return _resolve_eval_report_suite_count(eval_report_path)
    if source.startswith("eval-report:"):
        return _resolve_eval_report(source.removeprefix("eval-report:"), eval_report_path)
    if source == "pytest:cov-fail-under":
        return _resolve_pytest_cov_fail_under(pyproject_path)
    raise ClaimsError(f"unknown claim source kind: {source!r}")


def _window_near_marker(text: str, marker: str, context_lines: int = _CONTEXT_LINES) -> str | None:
    """Return the lines around ``marker`` (or None if the marker is absent)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if marker in line:
            lo = max(0, i - context_lines)
            hi = min(len(lines), i + context_lines + 1)
            return "\n".join(lines[lo:hi])
    return None


def _values_match(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except ValueError:
        return a.strip() == b.strip()


def check(
    claims_path: str | Path = _DEFAULT_CLAIMS,
    config_path: str | Path = _DEFAULT_CONFIG,
    eval_report_path: str | Path = _DEFAULT_EVAL_REPORT,
    pyproject_path: str | Path = _DEFAULT_PYPROJECT,
) -> list[str]:
    """Check every claim in ``claims_path`` against its source of truth.

    Returns a list of mismatch strings (empty = every claim reconciled). Two independent checks
    run per claim: (1) the registry's ``expected`` value must equal the value ``source`` resolves
    to today — a mismatch here means the registry itself is stale (code/config moved on); a
    ``policy:`` source has no independent code value and always passes this half, since the
    registry entry *is* the source of truth for a fixed policy decision. (2) the doc named by
    ``file`` must contain ``expected`` on or adjacent to the line carrying ``marker`` — a
    mismatch here means the doc text drifted from a registry that is otherwise correct.
    """
    claims = _load_claims(claims_path)
    problems: list[str] = []
    for claim in claims:
        if not claim.source.startswith("policy:"):
            try:
                resolved = _resolve(claim.source, config_path, eval_report_path, pyproject_path)
            except Exception as exc:  # surfaced as a reported problem, not a crash
                problems.append(f"{claim.id}: could not resolve source {claim.source!r}: {exc}")
                continue
            if not _values_match(resolved, claim.expected):
                problems.append(
                    f"{claim.id}: docs/claims.yaml says {claim.expected!r} but source "
                    f"{claim.source!r} resolves to {resolved!r} — the registry is stale"
                )
                continue

        doc_path = Path(claim.file)
        if not doc_path.exists():
            problems.append(f"{claim.id}: doc file not found: {doc_path}")
            continue
        window = _window_near_marker(doc_path.read_text(encoding="utf-8"), claim.marker)
        if window is None:
            problems.append(f"{claim.id}: marker {claim.marker!r} not found in {claim.file}")
            continue
        if claim.expected not in window:
            problems.append(
                f"{claim.id}: {claim.file} near {claim.marker!r} does not contain the "
                f"expected value {claim.expected!r}"
            )
    return problems
