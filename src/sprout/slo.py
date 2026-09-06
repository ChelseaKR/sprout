"""Schema validation for the Tier-A SLO and burn-rate-alert files.

``STANDARDS/OBSERVABILITY-STANDARD.md`` §4 requires ``slos/*.yaml`` to "pass JSON-Schema
(name, sli_query, target_percentage, window_days, error_budget_policy)"; §5 requires
``alerts/*.yml`` to pass `promtool check rules` and to define **both** a critical
(14.4x, 1h+5m) and a high (6x, 6h+30m) burn-rate tier per SLO. `promtool` is a Go binary
this Python repo doesn't otherwise depend on, so this module is the mechanical,
CI-runnable stand-in for the schema half of that gate (structural YAML/shape checks); it
does not replace `promtool`'s full PromQL parse — see ``sprout slo-check --help``.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


class SLOSchemaError(Exception):
    """A ``slos/*.yaml`` or ``alerts/*.yml`` file fails its required shape."""


class SLODefinition(BaseModel):
    """The five required keys from STANDARDS/OBSERVABILITY-STANDARD.md §4. Extra keys are
    rejected the same way every other config model in this repo rejects them — a typo'd
    key should fail loudly, not be silently ignored."""

    model_config = ConfigDict(extra="forbid")

    name: str
    sli_query: str
    target_percentage: float
    window_days: int
    error_budget_policy: str


def validate_slo_file(path: Path) -> SLODefinition:
    """Parse and schema-check one ``slos/*.yaml`` file. Raises ``SLOSchemaError`` on any
    missing/extra/mistyped field."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SLOSchemaError(f"{path}: not valid YAML ({exc})") from exc
    try:
        return SLODefinition.model_validate(data)
    except ValidationError as exc:
        raise SLOSchemaError(f"{path}: {exc}") from exc


RuleGroup = dict[str, object]
Rule = dict[str, object]


def _load_rule_groups(path: Path) -> list[RuleGroup]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SLOSchemaError(f"{path}: not valid YAML ({exc})") from exc
    groups = (data or {}).get("groups")
    if not isinstance(groups, list) or not groups:
        raise SLOSchemaError(f"{path}: no rule groups (expected a top-level 'groups' list)")
    return list(groups)


def _rules_of(path: Path, group: RuleGroup) -> list[Rule]:
    if "name" not in group or "rules" not in group:
        raise SLOSchemaError(f"{path}: group missing 'name' or 'rules': {group}")
    rules = group["rules"]
    if not isinstance(rules, list):
        raise SLOSchemaError(f"{path}: group '{group.get('name')}' rules is not a list")
    return list(rules)


def validate_alert_rules_file(path: Path) -> None:
    """Structural check on a Prometheus rule file: every group has a name and rules; every
    rule is exactly one of ``record``/``alert`` and has a non-empty ``expr``."""
    for group in _load_rule_groups(path):
        for rule in _rules_of(path, group):
            has_record = "record" in rule
            has_alert = "alert" in rule
            if has_record == has_alert:  # both or neither
                raise SLOSchemaError(
                    f"{path}: rule must be exactly one of 'record'/'alert': {rule}"
                )
            if not str(rule.get("expr", "")).strip():
                raise SLOSchemaError(f"{path}: rule missing non-empty 'expr': {rule}")


def validate_burn_rate_tiers(path: Path) -> None:
    """STANDARDS/OBSERVABILITY-STANDARD.md §5: a critical (14.4x) **and** a high (6x)
    burn-rate alert must both be present. Detected by the literal multiplier in each
    alert's ``expr`` (the standard's own worked example expresses burn rate this way:
    ``ratio > (14.4 * budget)`` / ``ratio > (6 * budget)``), not by alert name, so a
    differently-named-but-correctly-shaped alert still passes."""
    exprs = [
        str(rule["expr"])
        for group in _load_rule_groups(path)
        for rule in _rules_of(path, group)
        if "alert" in rule
    ]
    has_critical = any("14.4" in expr for expr in exprs)
    has_high = any("6 *" in expr or "6*" in expr for expr in exprs)
    if not (has_critical and has_high):
        raise SLOSchemaError(
            f"{path}: must define both a critical (>14.4x) and a high (>6x) burn-rate alert"
        )


def covered_files(slo_dir: Path, alerts_dir: Path) -> tuple[list[Path], list[Path]]:
    """The files :func:`check_all` would actually validate, in the order it reads them.

    Exists so a caller can tell "every file passed" apart from "there were no files". A
    schema gate over zero files reports the same empty problem list either way, and an
    empty problem list printed as a pass is how a deleted `slos/` directory would read as
    compliance. ``sprout slo-check`` uses this to refuse a vacuous run; the library keeps
    its tolerant contract for a repo that has not opted into Tier A at all.
    """
    slo_files = sorted(slo_dir.glob("*.yaml")) if slo_dir.is_dir() else []
    alert_files = sorted(alerts_dir.glob("*.yml")) if alerts_dir.is_dir() else []
    return slo_files, alert_files


def check_all(slo_dir: Path, alerts_dir: Path) -> list[str]:
    """Validate every ``slos/*.yaml`` and ``alerts/*.yml`` file. Returns problem strings
    (empty means everything passed); never raises for a missing/empty directory — a repo
    that hasn't opted into Tier A yet has no such directories, which is Tier A's absence,
    not a schema error.

    An empty list from this function therefore means "nothing failed", which is not the
    same as "something passed". A caller running this as a gate must ask
    :func:`covered_files` what was actually read before reporting success.
    """
    slo_files, alert_files = covered_files(slo_dir, alerts_dir)
    problems: list[str] = []
    for slo_path in slo_files:
        try:
            validate_slo_file(slo_path)
        except SLOSchemaError as exc:
            problems.append(str(exc))
    for alert_path in alert_files:
        try:
            validate_alert_rules_file(alert_path)
            validate_burn_rate_tiers(alert_path)
        except SLOSchemaError as exc:
            problems.append(str(exc))
    return problems
