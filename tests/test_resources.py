"""The packaged-data fallback that makes `pipx install sprout` work offline."""

from __future__ import annotations

from pathlib import Path

from sprout import resources
from sprout.config import load_config
from sprout.ingest import build_index


def test_packaged_config_and_corpus_exist() -> None:
    assert resources.packaged_config().exists()
    assert (resources.data_dir() / "corpus" / "manifest.yaml").exists()
    assert list((resources.data_dir() / "corpus" / "processed").glob("*.md"))


def test_locate_prefers_local_then_packaged(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)  # empty CWD so local files never shadow the test
    local = tmp_path / "here.txt"
    local.write_text("x", encoding="utf-8")
    assert resources.locate("here.txt") == Path("here.txt")  # local wins
    # A path that exists only in the package resolves into the package data dir.
    assert resources.locate("corpus/manifest.yaml") == resources.data_dir() / "corpus/manifest.yaml"
    # A path that exists nowhere is returned unchanged (so the caller raises its own error).
    assert resources.locate("nope/absent.yaml") == Path("nope/absent.yaml")


def test_build_index_from_packaged_corpus(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    # Run from an empty CWD so only the packaged corpus is reachable.
    monkeypatch.chdir(tmp_path)
    cfg = load_config(resources.packaged_config())
    store = build_index(cfg)
    assert len(store) > 100  # the full bundled corpus indexes
