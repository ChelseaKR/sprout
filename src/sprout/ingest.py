"""Corpus ingestion: manifest + processed files -> Documents -> Chunks -> index.

The manifest is the source of truth for provenance: every processed file MUST have a
matching manifest entry carrying source, url, license, fetch_date, language, and topic,
or ingestion fails loudly. This is how the "every passage carries source, license, and
fetch date" rule is enforced at the data boundary rather than hoped for downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from . import resources
from .chunk import chunk_document
from .config import Config
from .determinism import sha256_of_text
from .models import Chunk, Document
from .providers import build_embedding
from .store import VectorStore


class ManifestEntry(BaseModel):
    """One row of corpus/manifest.yaml — the dated, licensed provenance of a file."""

    model_config = ConfigDict(extra="forbid")

    file: str
    title: str
    source_name: str
    url: str
    license: str
    fetch_date: str
    language: str = "en"
    topic: str = "general"


def load_manifest(path: str | Path) -> dict[str, ManifestEntry]:
    """Load the manifest into a {file -> entry} map. Missing/empty manifest raises."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"corpus manifest not found: {p}")
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    docs = (raw or {}).get("documents")
    if not docs:
        raise ValueError(f"manifest {p} has no 'documents' list")
    out: dict[str, ManifestEntry] = {}
    for row in docs:
        entry = ManifestEntry.model_validate(row)
        out[entry.file] = entry
    return out


def load_corpus(config: Config) -> list[Document]:
    """Glob the processed corpus, joining each file to its manifest provenance.

    Falls back to the corpus bundled in the installed package when the configured paths
    do not exist in the working directory, so a fresh ``pipx install`` works offline.
    """
    root = resources.locate(config.corpus.path)
    manifest = load_manifest(resources.locate(config.corpus.manifest))
    documents: list[Document] = []
    for path in sorted(root.glob(config.corpus.glob)):
        rel = path.relative_to(root).as_posix()
        entry = manifest.get(rel)
        if entry is None:
            raise ValueError(f"corpus file {rel} has no manifest entry (provenance required)")
        text = path.read_text(encoding="utf-8")
        documents.append(
            Document(
                doc_id=sha256_of_text(rel)[:12],
                source=rel,
                title=entry.title,
                language=entry.language,
                text=text,
                source_name=entry.source_name,
                url=entry.url,
                license=entry.license,
                fetch_date=entry.fetch_date,
                topic=entry.topic,
            )
        )
    if not documents:
        raise ValueError(f"no corpus documents found under {root} matching {config.corpus.glob}")
    return documents


def build_chunks(config: Config, documents: list[Document]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in documents:
        chunks.extend(chunk_document(doc, config.chunk.max_words, config.chunk.overlap_words))
    if not chunks:
        raise ValueError("corpus produced zero chunks; check processed files are non-empty")
    return chunks


def build_index(config: Config) -> VectorStore:
    """Full ingest: load corpus, chunk, embed, and return a populated store."""
    embedder = build_embedding(config)
    store = VectorStore()
    for chunk in build_chunks(config, load_corpus(config)):
        store.add(chunk, embedder.embed(chunk.text))
    return store


def ingest(config: Config) -> VectorStore:
    """Build the index and persist it to ``config.store.path``."""
    store = build_index(config)
    store.save(config.store.path)
    return store
