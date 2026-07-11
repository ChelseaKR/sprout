"""Citation freshness / link-liveness tests (research item E7).

``today`` is fixed throughout for determinism, mirroring ``tests/conftest.py``'s
hermetic, no-disk fixture style.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from sprout.freshness import (
    FreshnessFinding,
    check_freshness,
    check_liveness,
    summarize,
)
from sprout.ingest import ManifestEntry

_TODAY = date(2026, 7, 3)


def _entry(
    file: str = "monstera.md",
    *,
    fetch_date: str = "2026-05-01",
    topic: str = "care",
    title: str = "Monstera care",
    url: str = "https://example.invalid/monstera",
) -> ManifestEntry:
    return ManifestEntry(
        file=file,
        title=title,
        source_name="Synthetic Plant-Care Notes",
        url=url,
        license="CC0-1.0",
        fetch_date=fetch_date,
        topic=topic,
    )


def test_fresh_manifest_yields_no_findings() -> None:
    manifest = {"monstera.md": _entry(fetch_date="2026-05-01")}
    findings = check_freshness(manifest, today=_TODAY, max_age_days=365)
    assert findings == []


def test_old_fetch_date_flags_stale_warning() -> None:
    old = "2024-01-01"  # well over 365d before _TODAY
    manifest = {"monstera.md": _entry(fetch_date=old)}
    findings = check_freshness(manifest, today=_TODAY, max_age_days=365)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "warning"
    assert finding.file == "monstera.md"
    assert finding.age_days is not None and finding.age_days > 365
    assert "citation is" in finding.reason


def test_toxicity_topic_uses_stricter_threshold() -> None:
    # 200 days old: within the general 365d window but past the toxicity 180d window.
    fetch_date = date.fromisoformat("2026-07-03")
    stale_date = fetch_date.toordinal() - 200
    fetch_date_str = date.fromordinal(stale_date).isoformat()
    manifest = {
        "care.md": _entry(file="care.md", fetch_date=fetch_date_str, topic="care"),
        "tox.md": _entry(
            file="tox.md",
            fetch_date=fetch_date_str,
            topic="toxicity",
            title="Pothos toxicity",
        ),
    }
    findings = check_freshness(manifest, today=_TODAY, max_age_days=365, toxicity_max_age_days=180)
    by_file = {f.file: f for f in findings}
    assert "care.md" not in by_file  # 200d < 365d general window: not stale
    assert by_file["tox.md"].severity == "high"
    assert "toxicity" in by_file["tox.md"].reason


def test_toxicity_inferred_from_title_when_topic_is_generic() -> None:
    # The bundled corpus has no dedicated "toxicity" topic yet (everything is "care"),
    # so a toxicity-titled entry must still get the stricter threshold via the title
    # fallback.
    stale_date = date.fromordinal(_TODAY.toordinal() - 200).isoformat()
    manifest = {
        "snake-plant.md": _entry(
            file="snake-plant.md",
            fetch_date=stale_date,
            topic="care",
            title="Snake plant care and toxicity",
        )
    }
    findings = check_freshness(manifest, today=_TODAY, max_age_days=365, toxicity_max_age_days=180)
    assert len(findings) == 1
    assert findings[0].severity == "high"


def test_unparseable_date_flags_error() -> None:
    manifest = {"monstera.md": _entry(fetch_date="not-a-date")}
    findings = check_freshness(manifest, today=_TODAY, max_age_days=365)
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert "unparseable" in findings[0].reason


def test_future_date_flags_error() -> None:
    manifest = {"monstera.md": _entry(fetch_date="2099-01-01")}
    findings = check_freshness(manifest, today=_TODAY, max_age_days=365)
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert "future" in findings[0].reason


def test_summarize_counts_by_severity() -> None:
    findings = [
        FreshnessFinding(
            file="a.md",
            url="https://example.invalid/a",
            topic="care",
            fetch_date="2024-01-01",
            age_days=900,
            severity="warning",
            reason="x",
        ),
        FreshnessFinding(
            file="b.md",
            url="https://example.invalid/b",
            topic="toxicity",
            fetch_date="bad",
            age_days=None,
            severity="high",
            reason="y",
        ),
    ]
    counts = summarize(findings)
    assert counts == {"warning": 1, "high": 1}
    assert summarize([]) == {"warning": 0, "high": 0}


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    """Records every call so tests can assert example.invalid is never touched."""

    def __init__(self, status_codes: dict[str, int] | None = None) -> None:
        self.status_codes = status_codes or {}
        self.calls: list[str] = []

    def head(self, url: str) -> _FakeResponse:
        self.calls.append(url)
        return _FakeResponse(self.status_codes.get(url, 200))

    def get(self, url: str) -> _FakeResponse:
        self.calls.append(url)
        return _FakeResponse(self.status_codes.get(url, 200))

    def close(self) -> None:
        pass


def test_example_invalid_urls_excluded_from_liveness() -> None:
    manifest = {
        "monstera.md": _entry(url="https://example.invalid/monstera"),
        "pothos.md": _entry(file="pothos.md", url="https://example.invalid/pothos"),
    }
    client = _FakeClient()
    findings = check_liveness(manifest, client=client)
    assert findings == []
    assert client.calls == []  # never touched — synthetic corpus stays fully offline


def test_liveness_flags_dead_link_for_non_excluded_host() -> None:
    manifest = {
        "real.md": _entry(file="real.md", url="https://real.example.com/care"),
    }
    client = _FakeClient(status_codes={"https://real.example.com/care": 404})
    findings = check_liveness(manifest, client=client)
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert "404" in findings[0].reason


def test_liveness_ok_link_yields_no_finding() -> None:
    manifest = {
        "real.md": _entry(file="real.md", url="https://real.example.com/care"),
    }
    client = _FakeClient(status_codes={"https://real.example.com/care": 200})
    findings = check_liveness(manifest, client=client)
    assert findings == []


def test_liveness_transport_error_flags_unreachable() -> None:
    class _RaisingClient:
        def head(self, url: str) -> Any:
            raise ConnectionError("boom")

        def close(self) -> None:
            pass

    manifest = {"real.md": _entry(file="real.md", url="https://real.example.com/care")}
    findings = check_liveness(manifest, client=_RaisingClient())
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert "unreachable" in findings[0].reason


def test_check_liveness_owns_and_closes_default_client_when_all_urls_excluded() -> None:
    # No client injected, but every URL is example.invalid, so this must not touch the
    # network and must still succeed (constructs and closes a real httpx.Client).
    manifest = {"monstera.md": _entry(url="https://example.invalid/monstera")}
    findings = check_liveness(manifest)
    assert findings == []


def test_freshness_finding_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        FreshnessFinding(
            file="a.md",
            url="https://example.invalid/a",
            topic="care",
            fetch_date="2026-05-01",
            age_days=0,
            severity="warning",
            reason="x",
            bogus="nope",  # type: ignore[call-arg]
        )
