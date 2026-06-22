"""Shared fixtures: a tiny in-memory corpus and a wired Assistant.

The fixtures build the store directly from synthetic chunks (no files), so the RAG and
guard tests are fast, hermetic, and never touch disk. Ingest-from-files is exercised
separately in ``test_ingest.py``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sprout.answer import Assistant
from sprout.config import Config
from sprout.models import Chunk
from sprout.providers import build_generator
from sprout.providers.deterministic import HashingEmbedding
from sprout.store import VectorStore


def make_chunk(
    chunk_id: str,
    source: str,
    title: str,
    text: str,
    topic: str = "general",
    language: str = "en",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=source.split(".")[0],
        title=title,
        source=source,
        text=text,
        language=language,
        topic=topic,
        source_name="Synthetic Plant-Care Notes",
        url=f"https://example.invalid/{source}",
        license="CC0-1.0",
        fetch_date="2026-05-01",
    )


TINY_CHUNKS: list[Chunk] = [
    make_chunk(
        "mon-water",
        "monstera.md",
        "Monstera care",
        "Yellowing Monstera leaves most often indicate overwatering. "
        "Let the top 2 inches of soil dry before watering again.",
        topic="watering",
    ),
    make_chunk(
        "mon-light",
        "monstera.md",
        "Monstera care",
        "Monstera prefers bright indirect light near an east or north window.",
        topic="light",
    ),
    make_chunk(
        "pothos-tox",
        "pothos.md",
        "Pothos toxicity",
        "The cited source lists Pothos as toxic to cats and dogs; "
        "ingestion can cause oral irritation and drooling.",
        topic="toxicity",
    ),
    make_chunk(
        "spider-tox",
        "spider-plant.md",
        "Spider plant toxicity",
        "The cited source does not list Spider plant as toxic to cats or dogs.",
        topic="toxicity",
    ),
    make_chunk(
        "mon-water-es",
        "monstera.es.md",
        "Cuidado de la Monstera",
        "Las hojas amarillas de la Monstera suelen indicar exceso de riego. "
        "Deja secar las primeras 5 centimetros de tierra antes de regar.",
        topic="watering",
        language="es",
    ),
    make_chunk(
        "pothos-tox-es",
        "pothos.es.md",
        "Toxicidad del potho",
        "La fuente citada indica que el potho es toxico para gatos y perros; "
        "la ingestion puede causar irritacion bucal.",
        topic="toxicity",
        language="es",
    ),
]


@pytest.fixture
def config() -> Config:
    return Config()


def build_assistant(config: Config, chunks: list[Chunk]) -> Assistant:
    embedder = HashingEmbedding(dim=config.retrieval.embedding_dim)
    store = VectorStore()
    for chunk in chunks:
        store.add(chunk, embedder.embed(chunk.text))
    return Assistant(config, store, embedder, build_generator(config))


@pytest.fixture
def assistant(config: Config) -> Assistant:
    return build_assistant(config, TINY_CHUNKS)


@pytest.fixture
def tiny_chunks() -> list[Chunk]:
    return list(TINY_CHUNKS)


@pytest.fixture
def assistant_factory() -> Callable[..., Assistant]:
    def _factory(cfg: Config, chunks: list[Chunk] | None = None) -> Assistant:
        return build_assistant(cfg, chunks if chunks is not None else list(TINY_CHUNKS))

    return _factory
