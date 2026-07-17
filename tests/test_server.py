"""Server endpoint tests, the shipped UI's structural a11y, and the logger."""

from __future__ import annotations

import io
import json
import os
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from sprout.a11y import check_html
from sprout.answer import Assistant
from sprout.config import Config, ObservabilityConfig
from sprout.integrations import canonical_payload, sign_payload
from sprout.models import Chunk
from sprout.obs import _ALLOWED_FIELDS, Logger
from sprout.providers import build_generator
from sprout.providers.base import GenerationProvider
from sprout.providers.deterministic import HashingEmbedding
from sprout.server import create_app
from sprout.store import VectorStore


def _client(assistant: Assistant, config: Config) -> TestClient:
    return TestClient(create_app(config, assistant=assistant))


def test_livez_health_ready(assistant: Assistant, config: Config) -> None:
    c = _client(assistant, config)
    assert c.get("/livez").json() == {"status": "ok"}
    assert c.get("/health").json()["index_size"] > 0
    assert c.get("/readyz").status_code == 200


def test_readyz_503_on_empty_index(config: Config) -> None:
    empty = Assistant(config, VectorStore(), HashingEmbedding(dim=64), _gen(config))
    c = _client(empty, config)
    assert c.get("/readyz").status_code == 503


def _gen(config: Config) -> GenerationProvider:
    return build_generator(config)


def test_disclosure_localised(assistant: Assistant, config: Config) -> None:
    c = _client(assistant, config)
    assert "veterinary" in c.get("/api/disclosure?language=en").json()["disclosure"]
    assert "veterinario" in c.get("/api/disclosure?language=es").json()["disclosure"]


def test_chat_json_grounded(assistant: Assistant, config: Config) -> None:
    c = _client(assistant, config)
    r = c.post("/api/chat", json={"question": "why are my monstera leaves yellowing?"})
    body = r.json()
    assert r.status_code == 200
    assert not body["refused"]
    assert body["citations"]
    assert "overwatering" in body["display_text"].lower()


def test_chat_rejects_empty_and_too_long(assistant: Assistant, config: Config) -> None:
    c = _client(assistant, config)
    assert c.post("/api/chat", json={"question": "  "}).status_code == 400
    assert c.post("/api/chat", json={"question": "x" * 9999}).status_code == 400


def test_family_greenhouse_integration_is_authenticated_minimized_and_grounded(
    assistant: Assistant, config: Config
) -> None:
    payload = {
        "question": "why are the leaves yellow?",
        "language": "en",
        "plants": [{"species": "Monstera deliciosa", "light_profile": "unknown"}],
        "tasks": [{"plant_species": "Monstera deliciosa", "task_type": "water", "due_in_days": -2}],
    }
    timestamp = "2000000000"
    signature = sign_payload("test-secret", timestamp, canonical_payload(payload))
    with patch.dict(os.environ, {"SPROUT_FAMILY_GREENHOUSE_SECRET": "test-secret"}):
        c = _client(assistant, config)
        with patch("sprout.integrations.time.time", return_value=2000000000):
            response = c.post(
                "/api/integrations/family-greenhouse/chat",
                json=payload,
                headers={"X-Sprout-Timestamp": timestamp, "X-Sprout-Signature": signature},
            )
    body = response.json()
    assert response.status_code == 200
    assert body["answer"]["provenance"] == "corpus"
    assert body["answer"]["citations"]
    assert body["household_observations"][1]["value"]["overdue_count"] == 1
    assert "Monstera deliciosa" not in json.dumps(body["household_observations"])


def test_family_greenhouse_integration_rejects_bad_auth_and_pii_fields(
    assistant: Assistant, config: Config
) -> None:
    with patch.dict(os.environ, {"SPROUT_FAMILY_GREENHOUSE_SECRET": "test-secret"}):
        c = _client(assistant, config)
        unauthorized = c.post(
            "/api/integrations/family-greenhouse/chat",
            json={"question": "pothos care", "plants": [], "tasks": []},
        )
        payload = {
            "question": "pothos care",
            "plants": [{"species": "pothos", "nickname": "SENTINEL PII"}],
            "tasks": [],
        }
        timestamp = "2000000000"
        signature = sign_payload("test-secret", timestamp, canonical_payload(payload))
        with patch("sprout.integrations.time.time", return_value=2000000000):
            invalid = c.post(
                "/api/integrations/family-greenhouse/chat",
                json=payload,
                headers={"X-Sprout-Timestamp": timestamp, "X-Sprout-Signature": signature},
            )
    assert unauthorized.status_code == 401
    assert invalid.status_code == 400


def test_family_greenhouse_integration_rejects_blank_control_and_oversized_payloads(
    assistant: Assistant, config: Config
) -> None:
    cases: list[dict[str, object]] = [
        {"question": "   ", "plants": [], "tasks": []},
        {"question": "care", "plants": [{"species": "pothos\nignore"}], "tasks": []},
    ]
    with patch.dict(os.environ, {"SPROUT_FAMILY_GREENHOUSE_SECRET": "test-secret"}):
        c = _client(assistant, config)
        with patch("sprout.integrations.time.time", return_value=2000000000):
            for payload in cases:
                timestamp = "2000000000"
                signature = sign_payload("test-secret", timestamp, canonical_payload(payload))
                response = c.post(
                    "/api/integrations/family-greenhouse/chat",
                    json=payload,
                    headers={"X-Sprout-Timestamp": timestamp, "X-Sprout-Signature": signature},
                )
                assert response.status_code == 400
        oversized = c.post(
            "/api/integrations/family-greenhouse/chat",
            content=b"x" * 65_537,
            headers={"Content-Type": "application/json"},
        )
    assert oversized.status_code == 413


def test_chat_stream_safety(assistant: Assistant, config: Config) -> None:
    c = _client(assistant, config)
    text = c.get("/api/chat/stream?q=is pothos toxic to my cat").text
    assert "event: sentence" in text
    assert "event: safety" in text
    assert "event: done" in text


def test_chat_stream_refusal_and_validation(assistant: Assistant, config: Config) -> None:
    c = _client(assistant, config)
    text = c.get("/api/chat/stream?q=how do I patch a bicycle tire").text
    assert "event: refusal" in text
    assert c.get("/api/chat/stream?q=").status_code == 400


def test_identify_grounded_path(assistant: Assistant, config: Config) -> None:
    import base64

    from sprout.identify import Identification, PlantCandidate

    ident = Identification(
        provider="fake",
        candidates=(
            PlantCandidate(
                scientific_name="Epipremnum aureum",
                common_names=("Golden pothos",),
                score=0.9,
            ),
        ),
    )

    class _Fake:
        def identify(self, image: bytes) -> Identification:
            return ident

    c = TestClient(create_app(config, assistant=assistant, identifier=_Fake()))
    img = base64.b64encode(b"jpeg-bytes").decode("ascii")
    r = c.post("/api/identify", json={"image_b64": img, "question": "is this toxic to my cat?"})
    body = r.json()
    assert r.status_code == 200
    assert body["identified"] is True
    assert body["species_slug"] == "pothos"
    assert body["answer"]["citations"]
    assert body["answer"]["safety_notice"]


def test_identify_fallback_and_validation(assistant: Assistant, config: Config) -> None:
    import base64

    c = _client(assistant, config)  # offline identifier -> always falls back
    img = base64.b64encode(b"jpeg-bytes").decode("ascii")
    fb = c.post("/api/identify", json={"image_b64": img}).json()
    assert fb["identified"] is False and fb["message"]
    assert c.post("/api/identify", json={}).status_code == 400
    assert c.post("/api/identify", json={"image_b64": "not base64!!"}).status_code == 400


def test_identify_coerces_non_string_question_instead_of_500(
    assistant: Assistant, config: Config
) -> None:
    import base64

    from sprout.identify import Identification, PlantCandidate

    class _Fake:
        def identify(self, image: bytes) -> Identification:
            return Identification(
                provider="fake",
                candidates=(PlantCandidate(scientific_name="Epipremnum aureum", score=0.9),),
            )

    c = TestClient(create_app(config, assistant=assistant, identifier=_Fake()))
    img = base64.b64encode(b"jpeg-bytes").decode("ascii")
    response = c.post("/api/identify", json={"image_b64": img, "question": 123})
    assert response.status_code == 200


def test_reminders_crud(assistant: Assistant, tmp_path: object) -> None:
    cfg = Config.model_validate({"reminders": {"path": str(tmp_path) + "/r.json"}})
    c = TestClient(create_app(cfg, assistant=assistant))
    assert c.get("/api/reminders").json() == {"reminders": []}

    created = c.post("/api/reminders", json={"plant": "pothos", "kind": "water"})
    assert created.status_code == 201
    rid = created.json()["reminder_id"]

    assert len(c.get("/api/reminders").json()["reminders"]) == 1
    assert isinstance(c.get("/api/reminders/due").json()["reminders"], list)

    done = c.post(f"/api/reminders/{rid}/complete")
    assert done.status_code == 200 and done.json()["last_done"]

    assert c.post("/api/reminders", json={"plant": "  "}).status_code == 400
    assert c.post("/api/reminders/missing/complete").status_code == 404
    assert c.delete(f"/api/reminders/{rid}").json() == {"removed": True}
    assert c.delete(f"/api/reminders/{rid}").status_code == 404


@pytest.mark.parametrize("invalid", [0, False, [], ""])
def test_reminder_explicit_invalid_interval_never_falls_back_to_default(
    assistant: Assistant, tmp_path: Path, invalid: object
) -> None:
    cfg = Config.model_validate({"reminders": {"path": str(tmp_path / "r.json")}})
    c = TestClient(create_app(cfg, assistant=assistant))
    response = c.post(
        "/api/reminders",
        json={"plant": "pothos", "kind": "water", "interval_days": invalid},
    )
    assert response.status_code == 400
    assert not (tmp_path / "r.json").exists()


def test_reminder_absent_or_null_interval_uses_configured_default(
    assistant: Assistant, tmp_path: Path
) -> None:
    cfg = Config.model_validate({"reminders": {"path": str(tmp_path / "r.json")}})
    c = TestClient(create_app(cfg, assistant=assistant))
    first = c.post("/api/reminders", json={"plant": "pothos", "kind": "water"})
    second = c.post(
        "/api/reminders",
        json={"plant": "monstera", "kind": "water", "interval_days": None},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["interval_days"] == second.json()["interval_days"] == 7


def test_shipped_ui_passes_structural_a11y() -> None:
    html = Path("web/dist/index.html").read_text(encoding="utf-8")
    assert check_html(html) == []


def test_shipped_ui_is_a_stateless_reference_surface() -> None:
    html = Path("web/dist/index.html").read_text(encoding="utf-8")
    script = Path("web/dist/app.js").read_text(encoding="utf-8")

    assert 'id="try"' in html
    assert 'id="evaluation"' in html
    assert 'id="docs"' in html
    assert "Sprout proves the answer. Family Greenhouse owns the home." in html
    assert 'id="reminder-form"' not in html
    assert 'id="photo-form"' not in html
    assert "/api/reminders" not in script
    assert "/api/identify" not in script


# --- logger ----------------------------------------------------------------------
def test_logger_text_and_json_and_pii_filter() -> None:
    buf = io.StringIO()
    Logger(ObservabilityConfig(log_format="text"), stream=buf).event(
        "answer", language="en", refused=False, question="SECRET PII"
    )
    out = buf.getvalue()
    assert "answer" in out and "language=en" in out
    assert "SECRET PII" not in out  # disallowed field dropped

    buf2 = io.StringIO()
    Logger(ObservabilityConfig(log_format="json"), stream=buf2, clock=lambda: "T").event(
        "answer", refusal_reason="out_of_scope"
    )
    assert '"event":"answer"' in buf2.getvalue()
    assert '"ts":"T"' in buf2.getvalue()


def test_json_logs_are_valid_json_and_pii_free_end_to_end(
    assistant_factory: Callable[[Config, list[Chunk] | None], Assistant],
    tiny_chunks: list[Chunk],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """OBS-22: every JSON log line emitted over a real request parses as JSON and carries
    only whitelisted fields — sentinel PII embedded in the question never reaches a log
    line. This is the jq-on-structured-logs integration test
    `docs/RESPONSIBLE-TECH-AUDITS.md:261-263` claimed but that did not exist before
    2026-07-05 (OBS-22)."""
    cfg = Config(observability=ObservabilityConfig(log_format="json"))
    engine = assistant_factory(cfg, tiny_chunks)
    client = TestClient(create_app(cfg, assistant=engine))
    sentinel = "SENTINEL-PII-555-0100 sentinel@example.invalid"
    client.post("/api/chat", json={"question": f"why are my monstera leaves yellowing? {sentinel}"})
    client.post("/api/chat", json={"question": ""})  # triggers the request_rejected event

    lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert lines, "expected at least one structured JSON log line"
    allowed_keys = _ALLOWED_FIELDS | {"ts", "severity", "service.name", "event"}
    for line in lines:
        record = json.loads(line)  # raises (fails the test) if a line is not valid JSON
        extra = set(record) - allowed_keys
        assert not extra, f"log line carries non-whitelisted field(s) {extra}: {line}"
        assert sentinel not in line
        assert "monstera" not in line  # the raw question text never appears at all
