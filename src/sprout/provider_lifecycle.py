"""Operational wrappers for cloud-client lifecycle, cost bounds, and telemetry.

This module deliberately does not assemble prompts, choose models, alter decoding
parameters, rank retrieval results, or rewrite generated text. The wrappers here cache
lazy clients, forward provider arguments unchanged, validate response envelopes, emit
content-free lifecycle metadata, and suppress calls above the configured cost ceiling.
Because that last decision can affect whether output exists, this file itself remains
inside the tuning-scope gate; only its exact reviewed bootstrap digest is admitted once.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .genai_telemetry import (
    GenAiCall,
    TelemetrySink,
    Usage,
    cost_usd,
    emit_call,
    record_safely,
    usage_from_mapping,
)
from .models import RetrievedChunk
from .providers.base import EmbeddingProvider, GenerationProvider

_TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"
_FINISH_REASONS = frozenset(
    {"end_turn", "max_tokens", "pause_turn", "refusal", "stop_sequence", "tool_use"}
)


def _finish_reason(value: object) -> str | None:
    return value if type(value) is str and value in _FINISH_REASONS else None


def _validate_chat_payload(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError("model response must be a JSON object")
    blocks = value.get("content")
    if type(blocks) is not list:
        raise TypeError("model response content must be a list")
    for block in blocks:
        if type(block) is not dict or type(block.get("text")) is not str:
            raise TypeError("model response content blocks must contain string text")
    return value


def _validate_embedding_payload(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError("embedding response must be a JSON object")
    embedding = value.get("embedding")
    if type(embedding) is not list or any(
        type(item) not in (int, float) or not math.isfinite(item) for item in embedding
    ):
        raise TypeError("embedding response must contain a finite numeric vector")
    return value


@dataclass
class _PendingCall:
    system: str
    model: str
    operation: str
    region: str | None
    sink: TelemetrySink
    started: float
    recorded: bool = False

    def success(self, payload: Mapping[str, object]) -> None:
        if self.recorded:
            return
        self.recorded = True
        usage_value: object
        if self.operation == "embeddings":
            usage_value = {"input_tokens": payload.get("inputTextTokenCount")}
        else:
            usage_value = payload.get("usage")
        record_safely(
            self.sink,
            GenAiCall(
                system=self.system,
                model=self.model,
                operation=self.operation,
                duration_seconds=time.monotonic() - self.started,
                usage=usage_from_mapping(usage_value, region=self.region),
                finish_reason=_finish_reason(payload.get("stop_reason")),
            ),
        )

    def failure(self, exc: BaseException) -> None:
        if self.recorded:
            return
        self.recorded = True
        record_safely(
            self.sink,
            GenAiCall(
                system=self.system,
                model=self.model,
                operation=self.operation,
                duration_seconds=time.monotonic() - self.started,
                error_type=type(exc).__name__,
            ),
        )


class _AnthropicResponse:
    def __init__(self, response: Any, pending: _PendingCall) -> None:
        self._response = response
        self._pending = pending
        self._loaded = False
        self._payload: dict[str, object] | None = None

    def raise_for_status(self) -> None:
        try:
            self._response.raise_for_status()
        except Exception as exc:
            self._pending.failure(exc)
            raise

    def json(self) -> dict[str, object]:
        if self._loaded:
            if self._payload is None:  # pragma: no cover - defensive invariant
                raise RuntimeError("response payload was not retained")
            return self._payload
        try:
            payload = _validate_chat_payload(self._response.json())
        except Exception as exc:
            self._pending.failure(exc)
            raise
        self._loaded = True
        self._payload = payload
        self._pending.success(payload)
        return payload


class _AnthropicClient:
    def __init__(self, client: Any, model: str, sink: TelemetrySink) -> None:
        self._client = client
        self._model = model
        self._sink = sink

    def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=60.0)
        return self._client

    def post(self, *args: object, **kwargs: object) -> _AnthropicResponse:
        pending = _PendingCall(
            system="anthropic",
            model=self._model,
            operation="chat",
            region=None,
            sink=self._sink,
            started=time.monotonic(),
        )
        try:
            response = self._get_client().post(*args, **kwargs)
        except Exception as exc:
            pending.failure(exc)
            raise
        return _AnthropicResponse(response, pending)


class _BedrockBody:
    def __init__(self, body: Any, pending: _PendingCall) -> None:
        self._body = body
        self._pending = pending
        self._loaded = False
        self._raw: Any = None

    def read(self, *args: object, **kwargs: object) -> Any:
        if self._loaded:
            return self._raw
        try:
            raw = self._body.read(*args, **kwargs)
            payload_value = json.loads(raw)
            payload = (
                _validate_embedding_payload(payload_value)
                if self._pending.operation == "embeddings"
                else _validate_chat_payload(payload_value)
            )
        except Exception as exc:
            self._pending.failure(exc)
            raise
        self._loaded = True
        self._raw = raw
        self._pending.success(payload)
        return raw


class _BedrockClient:
    def __init__(self, client: Any, region: str, sink: TelemetrySink) -> None:
        self._client = client
        self._region = region
        self._sink = sink

    def _get_client(self) -> Any:
        if self._client is None:
            from .providers.bedrock import _client

            self._client = _client(self._region)
        return self._client

    def invoke_model(self, *, modelId: str, body: str) -> dict[str, object]:
        operation = "embeddings" if modelId.startswith("amazon.titan") else "chat"
        pending = _PendingCall(
            system="aws.bedrock",
            model=modelId,
            operation=operation,
            region=self._region,
            sink=self._sink,
            started=time.monotonic(),
        )
        try:
            price_probe = Usage(
                input_tokens=1,
                output_tokens=0 if operation == "embeddings" else 1,
                region=self._region,
            )
            if cost_usd(modelId, price_probe) is None:
                raise ValueError(
                    f"model {modelId!r} has no pinned price for region {self._region!r}"
                )
            response = self._get_client().invoke_model(modelId=modelId, body=body)
            if type(response) is not dict or not hasattr(response.get("body"), "read"):
                raise TypeError("Bedrock response must contain a readable body")
        except Exception as exc:
            pending.failure(exc)
            raise
        wrapped = dict(response)
        wrapped["body"] = _BedrockBody(response["body"], pending)
        return wrapped


class _BudgetedGenerator:
    def __init__(
        self,
        provider: GenerationProvider,
        *,
        model: str,
        region: str | None,
        max_cost_usd: float,
    ) -> None:
        if type(max_cost_usd) not in (int, float) or not math.isfinite(max_cost_usd):
            raise ValueError("max_cost_usd must be a finite nonnegative number")
        if max_cost_usd < 0:
            raise ValueError("max_cost_usd must be a finite nonnegative number")
        self._provider = provider
        self._model = model
        self._region = region
        self._max_cost_usd = float(max_cost_usd)
        # Fail at activation, not after a paid call, when the selected model is unknown.
        self._estimate("", [])

    def _estimate(self, query: str, context: list[RetrievedChunk]) -> float:
        chars = len(query) + sum(len(item.chunk.text) for item in context)
        estimate = cost_usd(
            self._model,
            Usage(input_tokens=int(chars / 4), output_tokens=400, region=self._region),
        )
        if estimate is None:
            raise ValueError(
                f"model {self._model!r} has no pinned price for region {self._region!r}"
            )
        return estimate

    def generate(
        self,
        query: str,
        context: list[RetrievedChunk],
        max_sentences: int,
        boost_terms: frozenset[str] = frozenset(),
    ) -> list[tuple[str, str]]:
        if self._estimate(query, context) > self._max_cost_usd:
            return []
        # The behavior-bearing provider receives the original arguments byte-for-byte.
        return self._provider.generate(query, context, max_sentences, boost_terms)

    def estimated_cost_usd(self, query: str, context: list[RetrievedChunk]) -> float:
        return self._estimate(query, context)


def observe_generation(
    provider: GenerationProvider,
    *,
    max_cost_usd: float,
    telemetry: TelemetrySink = emit_call,
) -> GenerationProvider:
    """Wrap a known cloud generator without changing its model or request contract."""

    from .providers.anthropic_native import AnthropicGenerator
    from .providers.bedrock import BedrockGenerator

    if isinstance(provider, AnthropicGenerator):
        model = provider._model
        if not model.startswith("claude-"):
            raise ValueError("native Anthropic model must start with 'claude-'")
        provider._client = _AnthropicClient(provider._client, model, telemetry)
        return _BudgetedGenerator(provider, model=model, region=None, max_cost_usd=max_cost_usd)
    if isinstance(provider, BedrockGenerator):
        model = provider._model
        region = provider._region
        if not (
            model.startswith("anthropic.")
            or ".anthropic." in model
            or model.startswith("arn:aws:bedrock:")
        ):
            raise ValueError("Bedrock model must be an Anthropic model id, profile, or ARN")
        provider._client = _BedrockClient(provider._client, region, telemetry)
        return _BudgetedGenerator(provider, model=model, region=region, max_cost_usd=max_cost_usd)
    raise TypeError(f"unsupported observed generator: {type(provider).__name__}")


def observe_embedding(
    provider: EmbeddingProvider,
    *,
    telemetry: TelemetrySink = emit_call,
) -> EmbeddingProvider:
    """Wrap the known Bedrock embedder with cached transport and response telemetry."""

    from .providers.bedrock import TitanEmbedding

    if not isinstance(provider, TitanEmbedding):
        raise TypeError(f"unsupported observed embedder: {type(provider).__name__}")
    region = provider._region
    if cost_usd(_TITAN_MODEL_ID, Usage(input_tokens=1, region=region)) is None:
        raise ValueError(
            f"embedding model {_TITAN_MODEL_ID!r} has no pinned price for region {region!r}"
        )
    provider._client = _BedrockClient(provider._client, region, telemetry)
    return provider


class CachedHttpClient:
    """Lazy, reusable HTTP client for the non-GenAI Pl@ntNet transport."""

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._client: Any = None

    def post(self, *args: object, **kwargs: object) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self._timeout)
        return self._client.post(*args, **kwargs)
