"""Provider factory: config strings -> concrete embedder/generator, lazily imported.

Lazy imports keep the offline default free of heavy dependencies — ``boto3`` is only
imported when ``provider: bedrock`` is actually selected, so ``pip install sprout`` with
no extras still runs end to end.
"""

from __future__ import annotations

from ..config import Config
from .base import EmbeddingProvider, GenerationProvider
from .deterministic import ExtractiveGenerator, HashingEmbedding

__all__ = [
    "EmbeddingProvider",
    "ExtractiveGenerator",
    "GenerationProvider",
    "HashingEmbedding",
    "build_embedding",
    "build_generator",
]


def build_embedding(config: Config) -> EmbeddingProvider:
    provider = config.retrieval.embedding_provider
    if provider == "deterministic":
        return HashingEmbedding(dim=config.retrieval.embedding_dim)
    if provider == "bedrock":
        from ..genai_telemetry import Usage, cost_usd
        from .bedrock import TITAN_MODEL_ID, TitanEmbedding

        if (
            cost_usd(
                TITAN_MODEL_ID,
                Usage(input_tokens=1_000_000, region=config.generation.region),
            )
            is None
        ):
            raise ValueError(
                f"embedding model {TITAN_MODEL_ID!r} has no pinned shared price for "
                f"region {config.generation.region!r}; refusing an unpriced activation"
            )
        return TitanEmbedding(dim=config.retrieval.embedding_dim, region=config.generation.region)
    raise ValueError(f"unknown embedding provider: {provider}")  # pragma: no cover


def build_generator(config: Config) -> GenerationProvider:
    provider = config.generation.provider
    if provider == "deterministic":
        return ExtractiveGenerator(relevance_floor=config.generation.relevance_floor)
    if provider == "bedrock":
        from .bedrock import BedrockGenerator

        model = config.generation.model or "anthropic.claude-haiku-4-5-20251001-v1:0"
        return BedrockGenerator(model=model, region=config.generation.region)
    if provider == "anthropic":
        from .anthropic_native import AnthropicGenerator

        model = config.generation.model or "claude-haiku-4-5-20251001"
        return AnthropicGenerator(model=model)
    raise ValueError(f"unknown generation provider: {provider}")  # pragma: no cover
