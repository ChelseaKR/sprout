"""Claude-on-Bedrock generator + Titan embedder — the production seam.

This is the optional cloud path behind ``generation.provider: bedrock``. It mirrors the
offline stack's failure posture exactly: any exception, timeout, or malformed/empty
model response logs and returns an *empty* candidate list, so a provider outage degrades
to a refusal — never an ungrounded answer. Generated sentences are attributed to their
best-overlap retrieved chunk and then independently re-verified by the citation guard,
so a wrong attribution is dropped rather than shown. Excluded from coverage because it
requires live AWS credentials; exercised via the injectable client in integration only.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..genai_telemetry import (
    GenAiCall,
    TelemetrySink,
    Usage,
    cost_usd,
    emit_call,
    record_safely,
    usage_from_mapping,
)
from ..models import RetrievedChunk
from ..text import coverage, split_sentences

TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"


def _client(region: str) -> Any:
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=BotoConfig(
            connect_timeout=5,
            read_timeout=60,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


class TitanEmbedding:
    """Amazon Titan text embeddings (returns an L2-normalised vector)."""

    def __init__(
        self,
        dim: int = 512,
        region: str = "us-west-2",
        client: Any = None,
        telemetry: TelemetrySink = emit_call,
    ) -> None:
        self._dim = dim
        self._region = region
        self._client = client
        self._telemetry = telemetry

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        started = time.monotonic()
        model = TITAN_MODEL_ID
        try:
            if self._client is None:
                # Cache the lazily-built client: ingest calls embed() once per chunk, and a
                # fresh boto3 client (with its own connection pool) per call is a leak.
                self._client = _client(self._region)
            client = self._client
            resp = client.invoke_model(
                modelId=model,
                body=json.dumps({"inputText": text, "dimensions": self._dim}),
            )
            payload = json.loads(resp["body"].read())
            if not isinstance(payload, dict):
                raise TypeError("Titan response must be a JSON object")
            raw_embedding = payload.get("embedding")
            if not isinstance(raw_embedding, list):
                raise TypeError("Titan response embedding must be a list")
            vec = [float(x) for x in raw_embedding]
            norm = sum(v * v for v in vec) ** 0.5
        except Exception as exc:
            record_safely(
                self._telemetry,
                GenAiCall(
                    system="aws.bedrock",
                    model=model,
                    operation="embeddings",
                    duration_seconds=time.monotonic() - started,
                    error_type=type(exc).__name__,
                ),
            )
            raise
        record_safely(
            self._telemetry,
            GenAiCall(
                system="aws.bedrock",
                model=model,
                operation="embeddings",
                duration_seconds=time.monotonic() - started,
                usage=usage_from_mapping(
                    {
                        "input_tokens": (
                            payload.get("inputTextTokenCount")
                            if isinstance(payload, dict)
                            else None
                        )
                    },
                    region=self._region,
                ),
            ),
        )
        return [v / norm for v in vec] if norm else vec


class BedrockGenerator:
    """Claude on Bedrock, constrained to quote the numbered sources."""

    def __init__(
        self,
        model: str = "anthropic.claude-haiku-4-5-20251001-v1:0",
        region: str = "us-west-2",
        client: Any = None,
        telemetry: TelemetrySink = emit_call,
    ) -> None:
        self._model = model
        self._region = region
        self._client = client
        self._telemetry = telemetry

    def generate(
        self, query: str, context: list[RetrievedChunk], max_sentences: int
    ) -> list[tuple[str, str]]:
        if not context:
            return []
        try:
            text = self._invoke(query, context, max_sentences)
        except Exception:
            return []
        out: list[tuple[str, str]] = []
        for sentence in split_sentences(text)[:max_sentences]:
            best = max(context, key=lambda rc: coverage(sentence, rc.chunk.text))
            out.append((sentence.strip(), best.chunk.chunk_id))
        return out

    def _invoke(self, query: str, context: list[RetrievedChunk], max_sentences: int) -> str:
        started = time.monotonic()
        try:
            if self._client is None:
                # Cache the lazily-built client (see TitanEmbedding.embed) rather than
                # constructing a fresh one per generation call.
                self._client = _client(self._region)
            client = self._client
            sources = "\n".join(
                f"[{i}] (chunk {rc.chunk.chunk_id}) {rc.chunk.text}" for i, rc in enumerate(context)
            )
            prompt = (
                "Answer the question using ONLY the sources above. Quote them faithfully, "
                f"never certify a plant 'safe', and use at most {max_sentences} sentences.\n\n"
                f"SOURCES:\n{sources}\n\nQUESTION: {query}"
            )
            resp = client.invoke_model(
                modelId=self._model,
                body=json.dumps(
                    {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 400,
                        "temperature": 0.0,
                        "messages": [{"role": "user", "content": prompt}],
                    }
                ),
            )
            payload = json.loads(resp["body"].read())
            if not isinstance(payload, dict):
                raise TypeError("Bedrock response must be a JSON object")
            blocks = payload.get("content", [])
            if not isinstance(blocks, list):
                raise TypeError("Bedrock response content must be a list")
            text = "".join(
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            )
        except Exception as exc:
            record_safely(
                self._telemetry,
                GenAiCall(
                    system="aws.bedrock",
                    model=self._model,
                    operation="chat",
                    duration_seconds=time.monotonic() - started,
                    error_type=type(exc).__name__,
                ),
            )
            raise
        record_safely(
            self._telemetry,
            GenAiCall(
                system="aws.bedrock",
                model=self._model,
                response_model=(
                    str(payload["model"]) if isinstance(payload.get("model"), str) else None
                ),
                operation="chat",
                duration_seconds=time.monotonic() - started,
                usage=usage_from_mapping(payload.get("usage"), region=self._region),
                finish_reason=(
                    str(payload["stop_reason"])
                    if isinstance(payload.get("stop_reason"), str)
                    else None
                ),
            ),
        )
        return text

    def estimated_cost_usd(self, query: str, context: list[RetrievedChunk]) -> float | None:
        chars = len(query) + sum(len(rc.chunk.text) for rc in context)
        return cost_usd(
            self._model,
            Usage(input_tokens=int(chars / 4), output_tokens=400, region=self._region),
        )
