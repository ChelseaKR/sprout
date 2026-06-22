"""Ingest tests: manifest provenance, chunking by topic, end-to-end index build."""

from __future__ import annotations

from pathlib import Path

import pytest

from sprout.chunk import chunk_document, slugify
from sprout.config import Config
from sprout.ingest import build_chunks, ingest, load_corpus, load_manifest
from sprout.models import Document

_MD = """# Monstera care

## Watering
Yellowing leaves most often indicate overwatering. Let the top 2 inches of soil dry first.

## Light
Monstera prefers bright indirect light near an east window.
"""

_MANIFEST = """documents:
  - file: monstera.md
    title: Monstera care
    source_name: Synthetic Plant-Care Notes
    url: https://example.invalid/monstera
    license: CC0-1.0
    fetch_date: "2026-05-01"
    language: en
    topic: care
"""


@pytest.fixture
def corpus_config(tmp_path: Path) -> Config:
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "monstera.md").write_text(_MD, encoding="utf-8")
    (tmp_path / "manifest.yaml").write_text(_MANIFEST, encoding="utf-8")
    return Config.model_validate(
        {
            "corpus": {"path": str(processed), "manifest": str(tmp_path / "manifest.yaml")},
            "store": {"path": str(tmp_path / "index.json")},
        }
    )


def test_slugify() -> None:
    assert slugify("Toxicity & Pets!") == "toxicity-pets"
    assert slugify("   ") == "general"


def test_chunk_document_splits_by_topic() -> None:
    doc = Document(
        doc_id="d1",
        source="monstera.md",
        title="Monstera care",
        language="en",
        text=_MD,
        source_name="x",
        url="https://example.invalid/m",
        license="CC0-1.0",
        fetch_date="2026-05-01",
    )
    chunks = chunk_document(doc, max_words=120, overlap_words=20)
    topics = {c.topic for c in chunks}
    assert "watering" in topics
    assert "light" in topics
    assert all("#" not in c.text for c in chunks)  # heading markup stripped


def test_load_manifest_and_corpus(corpus_config: Config) -> None:
    manifest = load_manifest(corpus_config.corpus.manifest)
    assert manifest["monstera.md"].license == "CC0-1.0"
    docs = load_corpus(corpus_config)
    assert len(docs) == 1
    assert docs[0].fetch_date == "2026-05-01"


def test_load_manifest_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "absent.yaml")


def test_load_manifest_empty(tmp_path: Path) -> None:
    p = tmp_path / "m.yaml"
    p.write_text("documents: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no 'documents'"):
        load_manifest(p)


def test_corpus_file_without_manifest_entry_fails(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "orphan.md").write_text("## Watering\nWater weekly.\n", encoding="utf-8")
    (tmp_path / "manifest.yaml").write_text(_MANIFEST, encoding="utf-8")
    cfg = Config.model_validate(
        {"corpus": {"path": str(processed), "manifest": str(tmp_path / "manifest.yaml")}}
    )
    with pytest.raises(ValueError, match="no manifest entry"):
        load_corpus(cfg)


def test_empty_corpus_fails(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    (tmp_path / "manifest.yaml").write_text(_MANIFEST, encoding="utf-8")
    cfg = Config.model_validate(
        {"corpus": {"path": str(processed), "manifest": str(tmp_path / "manifest.yaml")}}
    )
    with pytest.raises(ValueError, match="no corpus documents"):
        load_corpus(cfg)


def test_ingest_builds_and_persists_index(corpus_config: Config) -> None:
    store = ingest(corpus_config)
    assert len(store) >= 2
    assert Path(corpus_config.store.path).exists()
    assert len(build_chunks(corpus_config, load_corpus(corpus_config))) == len(store)
