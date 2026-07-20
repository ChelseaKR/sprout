"""Provider factory: config strings -> concrete embedder/generator, lazily imported.

Lazy imports keep the offline default free of heavy dependencies — ``boto3`` is only
imported when ``provider: bedrock`` is actually selected, so ``pip install sprout`` with
no extras still runs end to end.
"""

from __future__ import annotations

from ..config import Config
from .base import EmbeddingProvider, GenerationProvider
from .deterministic import ExtractiveGenerator, HashingEmbedding
from .static_embedding import StaticEmbedding

__all__ = [
    "EmbeddingProvider",
    "ExtractiveGenerator",
    "GenerationProvider",
    "HashingEmbedding",
    "StaticEmbedding",
    "build_embedding",
    "build_generator",
]


def build_embedding(config: Config) -> EmbeddingProvider:
    provider = config.retrieval.embedding_provider
    if provider == "deterministic":
        return HashingEmbedding(dim=config.retrieval.embedding_dim)
    if provider == "static":
        return StaticEmbedding()
    if provider == "bedrock":
        from ..provider_lifecycle import observe_embedding
        from .bedrock import TitanEmbedding

        return observe_embedding(
            TitanEmbedding(dim=config.retrieval.embedding_dim, region=config.generation.region)
        )
    raise ValueError(f"unknown embedding provider: {provider}")  # pragma: no cover


def build_generator(config: Config) -> GenerationProvider:
    provider = config.generation.provider
    if provider == "deterministic":
        return ExtractiveGenerator(relevance_floor=config.generation.relevance_floor)
    if provider == "bedrock":
        from ..provider_lifecycle import observe_generation
        from .bedrock import BedrockGenerator

        model = config.generation.model or "anthropic.claude-3-5-haiku-20241022-v1:0"
        return observe_generation(
            BedrockGenerator(model=model, region=config.generation.region),
            max_cost_usd=config.generation.max_cost_usd,
        )
    if provider == "anthropic":
        from ..provider_lifecycle import observe_generation
        from .anthropic_native import AnthropicGenerator

        model = config.generation.model or "claude-haiku-4-5-20251001"
        return observe_generation(
            AnthropicGenerator(model=model),
            max_cost_usd=config.generation.max_cost_usd,
        )
    raise ValueError(f"unknown generation provider: {provider}")  # pragma: no cover
