"""Native Anthropic Messages API generator (no SDK, just httpx).

A second cloud seam for adopters who call the Anthropic API directly rather than via
Bedrock. Same fail-closed posture as every generator: any error or malformed response
returns an empty candidate list, so the pipeline refuses rather than inventing. The API
key comes from the ``ANTHROPIC_API_KEY`` environment variable, never config. Excluded
from coverage (requires a live key and network).
"""

from __future__ import annotations

import os
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

_ENDPOINT = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class AnthropicGenerator:
    """Claude via the native Messages API, constrained to quote the numbered sources."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        client: Any = None,
        api_key: str | None = None,
        telemetry: TelemetrySink = emit_call,
    ) -> None:
        self._model = model
        self._client = client
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._telemetry = telemetry

    def generate(
        self, query: str, context: list[RetrievedChunk], max_sentences: int
    ) -> list[tuple[str, str]]:
        if not context or not self._api_key:
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
                import httpx

                # Cache the lazily-built client: constructing a new (never-closed) Client on
                # every call leaks connections/file descriptors in a long-running server.
                self._client = httpx.Client(timeout=60.0)
            client = self._client
            sources = "\n".join(
                f"[{i}] (chunk {rc.chunk.chunk_id}) {rc.chunk.text}" for i, rc in enumerate(context)
            )
            resp = client.post(
                _ENDPOINT,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": _API_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 400,
                    "temperature": 0.0,
                    "system": (
                        "Answer using ONLY the numbered sources. Quote faithfully, never "
                        f"certify a plant 'safe', use at most {max_sentences} sentences."
                    ),
                    "messages": [
                        {"role": "user", "content": f"SOURCES:\n{sources}\n\nQUESTION: {query}"}
                    ],
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise TypeError("Anthropic response must be a JSON object")
            blocks = payload.get("content", [])
            if not isinstance(blocks, list):
                raise TypeError("Anthropic response content must be a list")
            text = "".join(
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            )
        except Exception as exc:
            record_safely(
                self._telemetry,
                GenAiCall(
                    system="anthropic",
                    model=self._model,
                    operation="chat",
                    duration_seconds=time.monotonic() - started,
                    error_type=type(exc).__name__,
                ),
            )
            raise
        usage = usage_from_mapping(payload.get("usage"))
        record_safely(
            self._telemetry,
            GenAiCall(
                system="anthropic",
                model=self._model,
                response_model=(
                    str(payload["model"]) if isinstance(payload.get("model"), str) else None
                ),
                operation="chat",
                duration_seconds=time.monotonic() - started,
                usage=usage,
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
            Usage(input_tokens=int(chars / 4), output_tokens=400),
        )
