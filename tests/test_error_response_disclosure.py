"""No handler may return exception text to a remote caller (CWE-209).

Regression tests for the three error-severity ``py/stack-trace-exposure`` findings CodeQL
surfaced on 2026-08-01 at ``src/sprout/server.py`` lines 201, 469 and 478 — the first day the
shared SARIF gate was capable of failing at all. Each of those handlers interpolated
``str(exc)`` into its JSON response, so a remote caller received pydantic's rendering of the
request model (class name, field paths, echoed input, and a versioned errors.pydantic.dev
URL), CPython's own ``int() argument must be …`` text, the configured reminder cap, the
on-disk reminders format version, or its own id reflected back.

Every test in this file fails against the pre-fix tree.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from sprout.answer import Assistant
from sprout.config import Config, ObservabilityConfig
from sprout.integrations import canonical_payload, sign_payload
from sprout.server import create_app

# Strings that may never appear in a response body. Each is a real leak from the pre-fix code.
_INTERNALS = (
    "pydantic",  # dependency identity + version, via the errors.pydantic.dev URL
    "FamilyGreenhouseRequest",  # internal model class name
    "validation error",  # pydantic's rendering, incl. field paths and echoed input
    "int() argument",  # CPython's own message, exposing the coercion being attempted
    "reminder limit reached",  # the configured cap
    "unsupported reminders format",  # the on-disk storage format version
    "Traceback",
    "/sprout/",  # a filesystem path
)


def _assert_no_internals(response: Response) -> None:
    body = response.text
    for needle in _INTERNALS:
        assert needle.lower() not in body.lower(), f"{needle!r} leaked to the client: {body}"


class TestFamilyGreenhouseIntegration:
    """Two of the three raise sites here run *before* the HMAC check, so this is reachable
    without any credential."""

    def _client(self, assistant: Assistant, config: Config) -> TestClient:
        return TestClient(create_app(config, assistant=assistant))

    def test_unauthenticated_malformed_json_returns_a_fixed_message(
        self, assistant: Assistant, config: Config
    ) -> None:
        with patch.dict(os.environ, {"SPROUT_FAMILY_GREENHOUSE_SECRET": "test-secret"}):
            response = self._client(assistant, config).post(
                "/api/integrations/family-greenhouse/chat",
                content=b"{not json",
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 400
        assert response.json() == {"error": "invalid integration payload"}
        _assert_no_internals(response)

    def test_unauthenticated_non_object_payload_returns_a_fixed_message(
        self, assistant: Assistant, config: Config
    ) -> None:
        with patch.dict(os.environ, {"SPROUT_FAMILY_GREENHOUSE_SECRET": "test-secret"}):
            response = self._client(assistant, config).post(
                "/api/integrations/family-greenhouse/chat",
                content=b'["not", "an", "object"]',
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 400
        assert response.json() == {"error": "invalid integration payload"}
        _assert_no_internals(response)

    def test_authenticated_schema_violation_does_not_expose_the_model(
        self, assistant: Assistant, config: Config
    ) -> None:
        """Even a *signed* caller gets no pydantic rendering — this is a first-party
        integration, not a debugging console, and the body echoes its own input back."""
        payload: dict[str, object] = {"question": "care", "plants": [{"species": 12345}]}
        with patch.dict(os.environ, {"SPROUT_FAMILY_GREENHOUSE_SECRET": "test-secret"}):
            client = self._client(assistant, config)
            with patch("sprout.integrations.time.time", return_value=2000000000):
                timestamp = "2000000000"
                response = client.post(
                    "/api/integrations/family-greenhouse/chat",
                    json=payload,
                    headers={
                        "X-Sprout-Timestamp": timestamp,
                        "X-Sprout-Signature": sign_payload(
                            "test-secret", timestamp, canonical_payload(payload)
                        ),
                    },
                )
        assert response.status_code == 400
        assert response.json() == {"error": "invalid integration payload"}
        _assert_no_internals(response)


class TestReminders:
    """``/api/reminders`` carries no authentication at all."""

    def _client(self, assistant: Assistant, tmp_path: Path) -> TestClient:
        cfg = Config.model_validate({"reminders": {"path": str(tmp_path / "r.json")}})
        return TestClient(create_app(cfg, assistant=assistant))

    @pytest.mark.parametrize("interval", [[], {}, "not-a-number", object])
    def test_uncoercible_interval_returns_a_fixed_message(
        self, assistant: Assistant, tmp_path: Path, interval: object
    ) -> None:
        response = self._client(assistant, tmp_path).post(
            "/api/reminders",
            json={"plant": "pothos", "kind": "water", "interval_days": str(interval)}
            if interval is object
            else {"plant": "pothos", "kind": "water", "interval_days": interval},
        )
        assert response.status_code == 400
        assert response.json() == {"error": "invalid reminder request"}
        _assert_no_internals(response)

    def test_capacity_limit_does_not_disclose_the_configured_cap(
        self, assistant: Assistant, tmp_path: Path
    ) -> None:
        cfg = Config.model_validate(
            {"reminders": {"path": str(tmp_path / "r.json"), "max_reminders": 2}}
        )
        client = TestClient(create_app(cfg, assistant=assistant))
        for plant in ("pothos", "monstera"):
            assert client.post("/api/reminders", json={"plant": plant}).status_code == 201
        response = client.post("/api/reminders", json={"plant": "fern"})
        assert response.status_code == 400
        assert response.json() == {"error": "invalid reminder request"}
        assert "2" not in response.json()["error"]
        _assert_no_internals(response)

    def test_completing_a_missing_reminder_does_not_reflect_the_id(
        self, assistant: Assistant, tmp_path: Path
    ) -> None:
        sentinel = "SENTINEL-ID-%3Cscript%3Ealert(1)%3C-script%3E"
        response = self._client(assistant, tmp_path).post(f"/api/reminders/{sentinel}/complete")
        assert response.status_code == 404
        assert response.json() == {"error": "reminder not found"}
        # Reflecting the caller's id back is how a "harmless" 404 body becomes an injection
        # surface for whatever renders it.
        assert "SENTINEL-ID" not in response.text
        assert "<script" not in response.text
        _assert_no_internals(response)

    def test_corrupt_store_does_not_disclose_the_storage_format(
        self, assistant: Assistant, tmp_path: Path
    ) -> None:
        store = tmp_path / "r.json"
        store.write_text(json.dumps({"format_version": "SENTINEL-FORMAT-99", "reminders": []}))
        response = self._client(assistant, tmp_path).post("/api/reminders/anything/complete")
        assert response.status_code == 404
        assert "SENTINEL-FORMAT-99" not in response.text
        _assert_no_internals(response)


def test_rejections_are_still_triageable_from_the_logs(
    assistant: Assistant, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Genericising the response must not make the failure invisible to the operator.

    ``obs.Logger`` is PII-free by construction, so the exception *message* — free text that
    routinely echoes caller input — is deliberately not logged either. The exception class is,
    which is low-cardinality and enough to tell a malformed body from a capacity limit.
    """
    cfg = Config.model_validate(
        {
            "reminders": {"path": str(tmp_path / "r.json")},
            "observability": ObservabilityConfig(log_format="json").model_dump(),
        }
    )
    client = TestClient(create_app(cfg, assistant=assistant))
    client.post("/api/reminders", json={"plant": "pothos", "interval_days": []})
    client.post("/api/reminders/SENTINEL-MISSING/complete")

    records = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.strip()]
    rejected = [r for r in records if r.get("event") == "request_rejected"]
    assert len(rejected) == 2, records
    assert {r["route"] for r in rejected} == {"reminders_create", "reminders_complete"}
    assert {r["error_kind"] for r in rejected} == {"TypeError", "ReminderError"}
    for record in records:
        assert "SENTINEL-MISSING" not in json.dumps(record)
