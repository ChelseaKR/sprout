"""Sprout's privacy-safe record and sink adapter for the vendored GenAI shim.

Attribute names, the semantic-convention pin, model resolution, and prices are
owned byte-for-byte by ``sprout._vendor.genai_telemetry``. This module contains
only Sprout's provider-response normalization and exporter-neutral record shape.
Prompts, completions, retrieved passages, and user identifiers are never fields.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TextIO

from ._vendor.genai_telemetry import Usage as VendorUsage
from ._vendor.genai_telemetry import cost_usd as vendor_cost_usd
from ._vendor.genai_telemetry.attributes import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_RESPONSE_TIME_TO_FIRST_CHUNK,
    GEN_AI_SYSTEM,
    GEN_AI_TOKEN_TYPE,
    GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    METRIC_OPERATION_DURATION,
    METRIC_TOKEN_USAGE,
    PORTFOLIO_COST_USD,
    SEMCONV_VERSION,
)

ERROR_TYPE = "error.type"


@dataclass(frozen=True)
class Usage:
    """Provider-neutral counts; total input includes both cache token buckets."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    region: str | None = None


def _vendor_usage(model: str, usage: Usage) -> VendorUsage:
    return VendorUsage(
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_creation_input_tokens=usage.cache_creation_input_tokens,
        cache_read_input_tokens=usage.cache_read_input_tokens,
        region=usage.region,
    )


def cost_usd(model: str, usage: Usage) -> float | None:
    """Use the shared pinned price table; unknown models remain visibly unpriced."""

    return vendor_cost_usd(_vendor_usage(model, usage))


def _nonnegative_int(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def usage_from_mapping(value: object, *, region: str | None = None) -> Usage:
    """Normalize Anthropic/Bedrock usage into the shared convention shape.

    Providers return fresh, cache-creation, and cache-read input separately. The
    canonical OTel input count is their sum; the vendored runtime then splits the
    total back into fresh/read/write buckets for pricing.
    """

    if not isinstance(value, Mapping):
        return Usage()
    fresh_input = _nonnegative_int(value.get("input_tokens"))
    cache_creation = _nonnegative_int(value.get("cache_creation_input_tokens"))
    cache_read = _nonnegative_int(value.get("cache_read_input_tokens"))
    return Usage(
        input_tokens=fresh_input + cache_creation + cache_read,
        output_tokens=_nonnegative_int(value.get("output_tokens")),
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
        region=region,
    )


@dataclass(frozen=True)
class GenAiCall:
    """One model operation ready for an OTel exporter or JSON-lines sink."""

    system: str
    model: str
    operation: str
    duration_seconds: float
    usage: Usage = Usage()
    response_model: str | None = None
    finish_reason: str | None = None
    time_to_first_chunk_seconds: float | None = None
    error_type: str | None = None

    def attributes(self) -> dict[str, object]:
        attrs: dict[str, object] = {
            GEN_AI_OPERATION_NAME: self.operation,
            GEN_AI_SYSTEM: self.system,
            GEN_AI_REQUEST_MODEL: self.model,
            GEN_AI_USAGE_INPUT_TOKENS: self.usage.input_tokens,
            GEN_AI_USAGE_OUTPUT_TOKENS: self.usage.output_tokens,
            GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS: (self.usage.cache_creation_input_tokens),
            GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS: self.usage.cache_read_input_tokens,
        }
        if self.response_model:
            attrs[GEN_AI_RESPONSE_MODEL] = self.response_model
        if self.finish_reason:
            attrs[GEN_AI_RESPONSE_FINISH_REASONS] = [self.finish_reason]
        if self.time_to_first_chunk_seconds is not None:
            attrs[GEN_AI_RESPONSE_TIME_TO_FIRST_CHUNK] = self.time_to_first_chunk_seconds
        if self.error_type:
            attrs[ERROR_TYPE] = self.error_type
        return attrs

    def as_record(self) -> dict[str, object]:
        metric_attrs = {
            GEN_AI_OPERATION_NAME: self.operation,
            GEN_AI_SYSTEM: self.system,
            GEN_AI_REQUEST_MODEL: self.model,
        }
        token_metrics = [
            {
                "name": METRIC_TOKEN_USAGE,
                "value": count,
                "unit": "{token}",
                "attributes": {**metric_attrs, GEN_AI_TOKEN_TYPE: direction},
            }
            for direction, count in (
                ("input", self.usage.input_tokens),
                ("output", self.usage.output_tokens),
            )
        ]
        estimate = cost_usd(self.model, self.usage)
        return {
            "semconv_version": SEMCONV_VERSION,
            "span": {
                "name": f"{self.operation} {self.model}",
                "attributes": self.attributes(),
            },
            "metrics": [
                {
                    "name": METRIC_OPERATION_DURATION,
                    "value": max(self.duration_seconds, 0.0),
                    "unit": "s",
                    "attributes": metric_attrs,
                },
                *token_metrics,
            ],
            PORTFOLIO_COST_USD: estimate,
            "unpriced": estimate is None,
            "content_captured": False,
        }


TelemetrySink = Callable[[GenAiCall], None]


def emit_call(call: GenAiCall, *, stream: TextIO | None = None) -> None:
    """Emit compact JSON metadata; sensitive content is structurally absent."""

    target = stream if stream is not None else sys.stderr
    print(
        json.dumps(
            call.as_record(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=target,
    )


def record_safely(sink: TelemetrySink, call: GenAiCall) -> None:
    """Telemetry must never turn a successful model call into an app failure."""

    try:
        sink(call)
    except Exception:
        return
