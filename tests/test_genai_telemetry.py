"""Lifecycle telemetry: semconv shim, cost accounting, and provider wiring."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from sprout._vendor.genai_telemetry import price_for_model
from sprout._vendor.genai_telemetry.attributes import (
    GEN_AI_REQUEST_MODEL,
    GEN_AI_TOKEN_TYPE,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    PORTFOLIO_COST_USD,
)
from sprout.eval.llm_judge import AnthropicJudge
from sprout.genai_telemetry import (
    GenAiCall,
    Usage,
    cost_usd,
    emit_call,
    usage_from_mapping,
)
from sprout.models import Chunk, RetrievedChunk
from sprout.provider_lifecycle import observe_embedding, observe_generation
from sprout.providers.anthropic_native import AnthropicGenerator
from sprout.providers.bedrock import BedrockGenerator, TitanEmbedding

_ROOT = Path(__file__).parents[1]
_VENDOR_COMMIT = "e8150c82fc35267f022af46ac71fe5a851e2d042"
_BEDROCK_MODEL = "anthropic.claude-haiku-4-5-20251001-v1:0"


class _Response:
    def raise_for_status(self) -> None:
        return

    def json(self) -> dict[str, object]:
        return {
            "model": "claude-haiku-4-5-20251001",
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_creation_input_tokens": 30,
                "cache_read_input_tokens": 40,
            },
            "content": [{"text": "Water when the top inch is dry."}],
        }


class _Client:
    def post(self, *_args: object, **_kwargs: object) -> _Response:
        return _Response()


class _CountingClient(_Client):
    def __init__(self) -> None:
        self.calls = 0

    def post(self, *_args: object, **_kwargs: object) -> _Response:
        self.calls += 1
        return super().post(*_args, **_kwargs)


class _Body:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


class _BedrockClient:
    def invoke_model(self, *, modelId: str, body: str) -> dict[str, _Body]:
        request = json.loads(body)
        if modelId.startswith("amazon.titan"):
            assert "inputText" in request
            return {"body": _Body({"embedding": [3.0, 4.0], "inputTextTokenCount": 1_000_000})}
        assert request["messages"][0]["role"] == "user"
        return {
            "body": _Body(
                {
                    "model": modelId,
                    "stop_reason": "end_turn",
                    "usage": {
                        "input_tokens": 50,
                        "output_tokens": 8,
                        "cache_creation_input_tokens": 5,
                        "cache_read_input_tokens": 10,
                    },
                    "content": [{"text": "Water when the top inch is dry."}],
                }
            )
        }


def _context() -> list[RetrievedChunk]:
    chunk = Chunk(
        chunk_id="c1",
        doc_id="d1",
        title="Plant guide",
        source="plant.md",
        text="Water when the top inch is dry.",
        language="en",
        topic="watering",
        source_name="Example",
        url="https://example.org/plant",
        license="CC0-1.0",
        fetch_date="2026-01-01",
    )
    return [RetrievedChunk(chunk=chunk, score=1.0)]


def test_cost_does_not_double_count_cache_reads() -> None:
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=500_000,
    )
    # Haiku 4.5: 0.5M fresh x $1 + 0.5M cache-read x $0.10 + 1M output x $5.
    assert cost_usd("claude-haiku-4-5-20251001", usage) == 5.55


def test_cost_splits_fresh_cache_creation_and_cache_read_tokens() -> None:
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=200_000,
        cache_read_input_tokens=300_000,
    )
    # 0.5M fresh x $1 + 0.2M writes x $1.25 + 0.3M reads x $0.10 + 1M output x $5.
    assert cost_usd("claude-haiku-4-5-20251001", usage) == 5.78


def test_semconv_names_and_prices_are_owned_by_the_pinned_vendor_package() -> None:
    vendor = _ROOT / "src/sprout/_vendor/genai_telemetry"
    assert (vendor / ".standards-version").read_text().strip() == _VENDOR_COMMIT
    marker = "gen" + "_ai."
    violations = [
        str(path.relative_to(_ROOT))
        for path in (_ROOT / "src/sprout").rglob("*.py")
        if "_vendor" not in path.parts and marker in path.read_text()
    ]
    assert violations == []
    assert GEN_AI_TOKEN_TYPE == "gen" + "_ai.token.type"


@pytest.mark.parametrize(
    ("prefix", "input_rate"),
    [("us", 1.1), ("eu", 1.1), ("au", 1.1), ("jp", 1.1), ("global", 1.0)],
)
def test_declared_bedrock_inference_profile_prefixes_are_priced(
    prefix: str, input_rate: float
) -> None:
    model = f"{prefix}.anthropic.claude-haiku-4-5-20251001-v1:0"
    row = price_for_model(model)
    assert row is not None
    assert row["input"] == input_rate


@pytest.mark.parametrize(
    "model",
    [
        "apac.anthropic.claude-haiku-4-5-20251001-v1:0",
        "anthropic.claude-haiku-4-5-20251001-v1:0:future",
        "arn:aws:bedrock:us-west-2:123456789012:foundation-model/anthropic.claude-haiku",
    ],
)
def test_undeclared_bedrock_ids_fail_closed(model: str) -> None:
    assert price_for_model(model) is None


def test_provider_usage_is_normalized_and_malformed_values_are_zero() -> None:
    assert usage_from_mapping(
        {
            "input_tokens": 10,
            "output_tokens": 2,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 4,
        }
    ) == Usage(
        input_tokens=17,
        output_tokens=2,
        cache_creation_input_tokens=3,
        cache_read_input_tokens=4,
    )
    assert usage_from_mapping({"input_tokens": "10", "output_tokens": -1}) == Usage()


def test_json_record_uses_shim_names_and_never_captures_content() -> None:
    buf = io.StringIO()
    emit_call(
        GenAiCall(
            system="anthropic",
            model="claude-haiku-4-5-20251001",
            operation="chat",
            duration_seconds=0.25,
            usage=Usage(input_tokens=10, output_tokens=2, cache_read_input_tokens=4),
        ),
        stream=buf,
    )
    record = json.loads(buf.getvalue())
    attrs = record["span"]["attributes"]
    assert attrs[GEN_AI_REQUEST_MODEL] == "claude-haiku-4-5-20251001"
    assert attrs[GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS] == 4
    assert record["content_captured"] is False
    assert "prompt" not in buf.getvalue().lower()
    assert "completion" not in buf.getvalue().lower()


def test_anthropic_provider_emits_actual_usage_without_query_content() -> None:
    calls: list[GenAiCall] = []
    generator = observe_generation(
        AnthropicGenerator(client=_Client(), api_key="test-key"),
        max_cost_usd=1.0,
        telemetry=calls.append,
    )
    query = "SENTINEL private plant question"
    answer = generator.generate(query, _context(), 2)

    assert answer
    assert len(calls) == 1
    assert calls[0].usage == Usage(
        input_tokens=170,
        output_tokens=20,
        cache_creation_input_tokens=30,
        cache_read_input_tokens=40,
    )
    assert query not in json.dumps(calls[0].as_record())


def test_cost_ceiling_blocks_transport_and_allowed_calls_forward_unchanged() -> None:
    blocked_client = _CountingClient()
    blocked = observe_generation(
        AnthropicGenerator(client=blocked_client, api_key="test-key"),
        max_cost_usd=0.0,
        telemetry=lambda _call: None,
    )
    assert blocked.generate("private question", _context(), 2) == []
    assert blocked_client.calls == 0

    allowed_client = _CountingClient()
    allowed = observe_generation(
        AnthropicGenerator(client=allowed_client, api_key="test-key"),
        max_cost_usd=1.0,
        telemetry=lambda _call: None,
    )
    assert allowed.generate("private question", _context(), 2)
    assert allowed_client.calls == 1


def test_bedrock_chat_and_embedding_calls_emit_telemetry() -> None:
    calls: list[GenAiCall] = []
    client = _BedrockClient()
    generator = observe_generation(
        BedrockGenerator(model=_BEDROCK_MODEL, client=client),
        max_cost_usd=1.0,
        telemetry=calls.append,
    )
    assert generator.generate("How much water?", _context(), 2)

    embedding = observe_embedding(TitanEmbedding(dim=2, client=client), telemetry=calls.append)
    assert embedding.embed("private input") == pytest.approx([0.6, 0.8])

    assert [call.operation for call in calls] == ["chat", "embeddings"]
    assert calls[0].usage == Usage(
        input_tokens=65,
        output_tokens=8,
        cache_creation_input_tokens=5,
        cache_read_input_tokens=10,
        region="us-west-2",
    )
    assert calls[1].usage == Usage(input_tokens=1_000_000, region="us-west-2")
    titan_record = calls[1].as_record()
    assert titan_record[PORTFOLIO_COST_USD] == 0.02
    assert titan_record["unpriced"] is False
    assert "private input" not in json.dumps([call.as_record() for call in calls])


def test_default_judge_call_emits_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _JudgeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict[str, Any]:
            return {
                "model": "claude-sonnet-4-6",
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 21,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 3,
                    "cache_read_input_tokens": 4,
                },
                "content": [{"text": '{"score": 0.9, "reason": "grounded"}'}],
            }

    monkeypatch.setattr("httpx.post", lambda *_args, **_kwargs: _JudgeResponse())
    calls: list[GenAiCall] = []
    decision = AnthropicJudge(telemetry=calls.append).entails("claim", ["source"])

    assert decision.passed
    assert len(calls) == 1
    assert calls[0].usage == Usage(
        input_tokens=28,
        output_tokens=5,
        cache_creation_input_tokens=3,
        cache_read_input_tokens=4,
    )


class _FailingClient:
    def post(self, *_args: object, **_kwargs: object) -> None:
        raise TimeoutError("provider unavailable")


class _FailingBedrockClient:
    def invoke_model(self, **_kwargs: object) -> None:
        raise ConnectionError("provider unavailable")


def test_anthropic_failure_emits_error_metadata() -> None:
    calls: list[GenAiCall] = []
    generator = observe_generation(
        AnthropicGenerator(client=_FailingClient(), api_key="test-key"),
        max_cost_usd=1.0,
        telemetry=calls.append,
    )

    assert generator.generate("private question", _context(), 2) == []
    assert len(calls) == 1
    assert calls[0].error_type == "TimeoutError"
    assert "private question" not in json.dumps(calls[0].as_record())


def test_bedrock_chat_failure_emits_error_metadata() -> None:
    calls: list[GenAiCall] = []
    generator = observe_generation(
        BedrockGenerator(model=_BEDROCK_MODEL, client=_FailingBedrockClient()),
        max_cost_usd=1.0,
        telemetry=calls.append,
    )

    assert generator.generate("private question", _context(), 2) == []
    assert len(calls) == 1
    assert calls[0].operation == "chat"
    assert calls[0].error_type == "ConnectionError"


def test_titan_failure_emits_error_metadata() -> None:
    calls: list[GenAiCall] = []
    embedding = observe_embedding(
        TitanEmbedding(dim=2, client=_FailingBedrockClient()),
        telemetry=calls.append,
    )

    with pytest.raises(ConnectionError, match="provider unavailable"):
        embedding.embed("private input")
    assert len(calls) == 1
    assert calls[0].operation == "embeddings"
    assert calls[0].error_type == "ConnectionError"


def test_lazy_client_construction_failures_emit_error_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_httpx(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("http client construction failed")

    monkeypatch.setattr("httpx.Client", fail_httpx)
    anthropic_calls: list[GenAiCall] = []
    anthropic = observe_generation(
        AnthropicGenerator(api_key="test-key"),
        max_cost_usd=1.0,
        telemetry=anthropic_calls.append,
    )
    assert anthropic.generate("private question", _context(), 2) == []
    assert anthropic_calls[0].error_type == "RuntimeError"

    def fail_bedrock(_region: str) -> None:
        raise RuntimeError("AWS client construction failed")

    monkeypatch.setattr("sprout.providers.bedrock._client", fail_bedrock)
    chat_calls: list[GenAiCall] = []
    bedrock = observe_generation(
        BedrockGenerator(model=_BEDROCK_MODEL),
        max_cost_usd=1.0,
        telemetry=chat_calls.append,
    )
    assert bedrock.generate("private question", _context(), 2) == []
    assert chat_calls[0].error_type == "RuntimeError"

    embedding_calls: list[GenAiCall] = []
    titan = observe_embedding(TitanEmbedding(dim=2), telemetry=embedding_calls.append)
    with pytest.raises(RuntimeError, match="construction failed"):
        titan.embed("private input")
    assert embedding_calls[0].error_type == "RuntimeError"


def test_lazy_anthropic_and_bedrock_clients_are_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anthropic_constructions = 0

    def anthropic_client(*_args: object, **_kwargs: object) -> _Client:
        nonlocal anthropic_constructions
        anthropic_constructions += 1
        return _Client()

    monkeypatch.setattr("httpx.Client", anthropic_client)
    native = observe_generation(
        AnthropicGenerator(api_key="test-key"),
        max_cost_usd=1.0,
        telemetry=lambda _call: None,
    )
    assert native.generate("water?", _context(), 1)
    assert native.generate("water?", _context(), 1)
    assert anthropic_constructions == 1

    bedrock_constructions = 0

    def bedrock_client(_region: str) -> _BedrockClient:
        nonlocal bedrock_constructions
        bedrock_constructions += 1
        return _BedrockClient()

    monkeypatch.setattr("sprout.providers.bedrock._client", bedrock_client)
    bedrock = observe_generation(
        BedrockGenerator(model=_BEDROCK_MODEL),
        max_cost_usd=1.0,
        telemetry=lambda _call: None,
    )
    assert bedrock.generate("water?", _context(), 1)
    assert bedrock.generate("water?", _context(), 1)
    assert bedrock_constructions == 1

    titan = observe_embedding(TitanEmbedding(dim=2), telemetry=lambda _call: None)
    assert titan.embed("one")
    assert titan.embed("two")
    assert bedrock_constructions == 2


def test_judge_failure_emits_error_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError("provider unavailable")

    monkeypatch.setattr("httpx.post", fail)
    calls: list[GenAiCall] = []
    judge = AnthropicJudge(telemetry=calls.append)

    with pytest.raises(TimeoutError, match="provider unavailable"):
        judge.entails("private claim", ["private source"])
    assert len(calls) == 1
    assert calls[0].error_type == "TimeoutError"
    assert "private claim" not in json.dumps(calls[0].as_record())


def test_telemetry_sink_failure_never_breaks_a_successful_model_call() -> None:
    def broken_sink(_call: GenAiCall) -> None:
        raise RuntimeError("exporter unavailable")

    generator = observe_generation(
        AnthropicGenerator(client=_Client(), api_key="test-key"),
        max_cost_usd=1.0,
        telemetry=broken_sink,
    )
    assert generator.generate("How much water?", _context(), 2)


@pytest.mark.parametrize(
    "generator",
    [
        AnthropicGenerator(model="claude-future-unpriced-model", api_key="test-key"),
        BedrockGenerator(model="anthropic.future-unpriced-model"),
    ],
)
def test_unpriced_provider_activation_fails_closed(
    generator: AnthropicGenerator | BedrockGenerator,
) -> None:
    with pytest.raises(ValueError, match="no pinned price"):
        observe_generation(generator, max_cost_usd=1.0, telemetry=lambda _call: None)


def test_titan_price_requires_an_exact_supported_region() -> None:
    model = "amazon.titan-embed-text-v2:0"
    assert cost_usd(model, Usage(input_tokens=1_000_000)) is None
    assert cost_usd(model, Usage(input_tokens=1_000_000, region="moon-1")) is None
    assert cost_usd(model, Usage(input_tokens=1_000_000, region="us-west-2")) == 0.02
    assert (
        cost_usd(
            model,
            Usage(input_tokens=1_000_000, output_tokens=1, region="us-west-2"),
        )
        is None
    )
