"""Server endpoint tests, the shipped UI's structural a11y, and the logger."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from sprout.a11y import check_html
from sprout.answer import Assistant
from sprout.config import Config, ObservabilityConfig
from sprout.obs import Logger
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


def test_shipped_ui_passes_structural_a11y() -> None:
    html = Path("web/dist/index.html").read_text(encoding="utf-8")
    assert check_html(html) == []


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
