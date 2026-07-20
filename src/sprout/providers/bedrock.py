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
from typing import Any

from ..models import RetrievedChunk
from ..text import coverage, split_sentences
from .base import context_hint

_PRICING_PER_1K = {"haiku": 0.0013, "sonnet": 0.018, "opus": 0.09}


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

    def __init__(self, dim: int = 512, region: str = "us-west-2", client: Any = None) -> None:
        self._dim = dim
        self._region = region
        self._client = client

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        client = self._client or _client(self._region)
        resp = client.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            body=json.dumps({"inputText": text, "dimensions": self._dim}),
        )
        payload = json.loads(resp["body"].read())
        vec: list[float] = [float(x) for x in payload["embedding"]]
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm else vec


class BedrockGenerator:
    """Claude on Bedrock, constrained to quote the numbered sources."""

    def __init__(
        self,
        model: str = "anthropic.claude-3-5-haiku-20241022-v1:0",
        region: str = "us-west-2",
        client: Any = None,
    ) -> None:
        self._model = model
        self._region = region
        self._client = client

    def _tier(self) -> str:
        for tier in _PRICING_PER_1K:
            if tier in self._model:
                return tier
        return "opus"  # most expensive tier as the conservative default

    def generate(
        self,
        query: str,
        context: list[RetrievedChunk],
        max_sentences: int,
        boost_terms: frozenset[str] = frozenset(),
    ) -> list[tuple[str, str]]:
        if not context:
            return []
        try:
            text = self._invoke(query, context, max_sentences, boost_terms)
        except Exception:
            return []
        out: list[tuple[str, str]] = []
        for sentence in split_sentences(text)[:max_sentences]:
            best = max(context, key=lambda rc: coverage(sentence, rc.chunk.text))
            out.append((sentence.strip(), best.chunk.chunk_id))
        return out

    def _invoke(
        self,
        query: str,
        context: list[RetrievedChunk],
        max_sentences: int,
        boost_terms: frozenset[str] = frozenset(),
    ) -> str:
        client = self._client or _client(self._region)
        sources = "\n".join(
            f"[{i}] (chunk {rc.chunk.chunk_id}) {rc.chunk.text}" for i, rc in enumerate(context)
        )
        prompt = (
            "Answer the question using ONLY the sources above. Quote them faithfully, "
            f"never certify a plant 'safe', and use at most {max_sentences} sentences."
            f"{context_hint(boost_terms)}\n\n"
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
        blocks = payload.get("content", [])
        return "".join(b.get("text", "") for b in blocks)

    def estimated_cost_usd(self, query: str, context: list[RetrievedChunk]) -> float:
        chars = len(query) + sum(len(rc.chunk.text) for rc in context)
        approx_tokens = chars / 4 + 400
        return (approx_tokens / 1000.0) * _PRICING_PER_1K[self._tier()]
