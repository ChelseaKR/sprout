"""Native Anthropic Messages API generator (no SDK, just httpx).

A second cloud seam for adopters who call the Anthropic API directly rather than via
Bedrock. Same fail-closed posture as every generator: any error or malformed response
returns an empty candidate list, so the pipeline refuses rather than inventing. The API
key comes from the ``ANTHROPIC_API_KEY`` environment variable, never config. Excluded
from coverage (requires a live key and network).
"""

from __future__ import annotations

import os
from typing import Any

from ..models import RetrievedChunk
from ..text import coverage, split_sentences

_ENDPOINT = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
# Pricing per 1K output-equivalent tokens, conservative.
_PRICING_PER_1K = {"haiku": 0.004, "sonnet": 0.015, "opus": 0.075}


class AnthropicGenerator:
    """Claude via the native Messages API, constrained to quote the numbered sources."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        client: Any = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._client = client
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def _tier(self) -> str:
        for tier in _PRICING_PER_1K:
            if tier in self._model:
                return tier
        return "opus"

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
        blocks = payload.get("content", [])
        return "".join(b.get("text", "") for b in blocks)

    def estimated_cost_usd(self, query: str, context: list[RetrievedChunk]) -> float:
        chars = len(query) + sum(len(rc.chunk.text) for rc in context)
        approx_tokens = chars / 4 + 400
        return (approx_tokens / 1000.0) * _PRICING_PER_1K[self._tier()]
