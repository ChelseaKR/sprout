"""Citation freshness / link-liveness checks (research item E7).

Two checks, one offline-by-default and one strictly opt-in:

1. ``check_freshness`` — parse every manifest entry's ``fetch_date`` and flag citations
   that have gone stale. Pure function of the manifest and a supplied ``today``: no I/O,
   no network, deterministic. Toxicity-topic entries (or, in the current synthetic corpus
   where every topic is ``"care"``, entries whose topic/title mentions toxicity) use a
   stricter threshold — a stale toxicity citation is a safety hazard, not just a
   horticulture nicety, so it should go stale sooner than a general care fact.
2. ``check_liveness`` — HEAD/GET each cited URL to catch dead or redirected links. Off
   by default and only ever invoked when a caller explicitly asks for it (``sprout
   freshness --check-links``), consistent with the project's "offline by default" rule.
   URLs on the synthetic corpus's placeholder host (``example.invalid``) are always
   skipped, so the bundled corpus never needs network access even when liveness is on.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from .ingest import ManifestEntry

Severity = Literal["warning", "high"]

# Substring markers used only as a fallback when a corpus has no dedicated "toxicity"
# topic yet (true today: every bundled entry is topic="care"). A real ``topic ==
# "toxicity"`` always wins; this just keeps the stricter threshold from silently
# lapsing while the corpus is mid-migration to richer topics.
_TOXICITY_MARKERS = ("toxic", "toxicidad", "toxicity", "poison", "veneno")

_EXCLUDED_LIVENESS_HOST = "example.invalid"


class FreshnessFinding(BaseModel):
    """One manifest entry's freshness or liveness verdict — only problems are reported."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    url: str
    topic: str
    fetch_date: str
    age_days: int | None
    severity: Severity
    reason: str


def _is_toxicity(entry: ManifestEntry) -> bool:
    if entry.topic == "toxicity":
        return True
    haystack = f"{entry.topic} {entry.title}".lower()
    return any(marker in haystack for marker in _TOXICITY_MARKERS)


def check_freshness(
    manifest: dict[str, ManifestEntry],
    *,
    today: date,
    max_age_days: int = 365,
    toxicity_max_age_days: int = 180,
) -> list[FreshnessFinding]:
    """Flag manifest entries with a stale, missing, or unparseable ``fetch_date``.

    A pure function of ``manifest`` and ``today`` — no clock reads, no I/O — so it is
    fully deterministic in tests and in CI. Toxicity entries are held to
    ``toxicity_max_age_days`` (stricter, default 180d); everything else to
    ``max_age_days`` (default 365d). Unparseable or future-dated entries are always
    ``"high"`` severity, since freshness cannot even be evaluated for them.
    """
    findings: list[FreshnessFinding] = []
    for path, entry in sorted(manifest.items()):
        toxicity = _is_toxicity(entry)
        limit = toxicity_max_age_days if toxicity else max_age_days
        try:
            fetched = date.fromisoformat(entry.fetch_date)
        except (TypeError, ValueError):
            findings.append(
                FreshnessFinding(
                    file=path,
                    url=entry.url,
                    topic=entry.topic,
                    fetch_date=entry.fetch_date,
                    age_days=None,
                    severity="high",
                    reason=f"unparseable fetch_date {entry.fetch_date!r} (want ISO-8601)",
                )
            )
            continue
        age = (today - fetched).days
        if age < 0:
            findings.append(
                FreshnessFinding(
                    file=path,
                    url=entry.url,
                    topic=entry.topic,
                    fetch_date=entry.fetch_date,
                    age_days=age,
                    severity="high",
                    reason=f"fetch_date {entry.fetch_date} is in the future",
                )
            )
        elif age > limit:
            findings.append(
                FreshnessFinding(
                    file=path,
                    url=entry.url,
                    topic=entry.topic,
                    fetch_date=entry.fetch_date,
                    age_days=age,
                    severity="high" if toxicity else "warning",
                    reason=(
                        f"{'toxicity ' if toxicity else ''}citation is {age}d old (max {limit}d)"
                    ),
                )
            )
    return findings


def summarize(findings: list[FreshnessFinding]) -> dict[Severity, int]:
    """Pure count of ``findings`` by severity (an empty dict entry means zero, not absent)."""
    counts: dict[Severity, int] = {"warning": 0, "high": 0}
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def check_liveness(
    manifest: dict[str, ManifestEntry],
    *,
    timeout: float = 10.0,
    client: Any = None,
) -> list[FreshnessFinding]:
    """HEAD (falling back to GET) every cited URL and flag dead or erroring ones.

    Strictly opt-in: only ever called when a caller explicitly asks for it (the CLI's
    ``--check-links`` flag). URLs on the synthetic ``example.invalid`` host are always
    skipped so the bundled corpus never touches the network, even with liveness on.
    ``client`` accepts an injected ``httpx``-shaped client for testing without network.
    """
    import httpx

    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=timeout, follow_redirects=True)
    findings: list[FreshnessFinding] = []
    try:
        for path, entry in sorted(manifest.items()):
            if (urlsplit(entry.url).hostname or "") == _EXCLUDED_LIVENESS_HOST:
                continue
            finding = _check_one_url(http, path, entry)
            if finding is not None:
                findings.append(finding)
    finally:
        if owns_client:
            http.close()
    return findings


def _check_one_url(http: Any, path: str, entry: ManifestEntry) -> FreshnessFinding | None:
    try:
        resp = http.head(entry.url)
        if resp.status_code >= 400:
            resp = http.get(entry.url)
    except Exception as exc:
        return FreshnessFinding(
            file=path,
            url=entry.url,
            topic=entry.topic,
            fetch_date=entry.fetch_date,
            age_days=None,
            severity="high",
            reason=f"unreachable: {exc}",
        )
    if resp.status_code >= 400:
        return FreshnessFinding(
            file=path,
            url=entry.url,
            topic=entry.topic,
            fetch_date=entry.fetch_date,
            age_days=None,
            severity="high",
            reason=f"HTTP {resp.status_code}",
        )
    return None
