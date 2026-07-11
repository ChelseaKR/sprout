"""The packaged-data fallback that makes `pipx install sprout` work offline."""

from __future__ import annotations

from pathlib import Path

from sprout import resources
from sprout.config import load_config
from sprout.determinism import sha256_of_obj
from sprout.ingest import build_index

# Repo root: tests/ sits directly under it.
_ROOT = Path(__file__).resolve().parents[1]


def _tree_contents(root: Path) -> dict[str, str]:
    """Sorted map of POSIX relative-path -> UTF-8 text for every file under ``root``."""
    return {
        str(path.relative_to(root).as_posix()): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_packaged_config_and_corpus_exist() -> None:
    assert resources.packaged_config().exists()
    assert (resources.data_dir() / "corpus" / "manifest.yaml").exists()
    assert list((resources.data_dir() / "corpus" / "processed").glob("*.md"))


def test_packaged_corpus_matches_top_level_corpus() -> None:
    """FIX-06: the vendored `src/sprout/data/corpus` copy must never drift from `corpus/`.

    Guards the duplication called out in docs/ideation/02-large-scale-fixes.md (FIX-06):
    without this, a regeneration that only touches the top-level corpus silently ships a
    stale packaged copy to `pipx install sprout` users.
    """
    top_level = _tree_contents(_ROOT / "corpus")
    packaged = _tree_contents(resources.data_dir() / "corpus")
    assert set(top_level) == set(packaged), (
        "corpus/ vs src/sprout/data/corpus/: file lists diverged"
    )
    assert sha256_of_obj(top_level) == sha256_of_obj(packaged), (
        "corpus/ vs src/sprout/data/corpus/: contents diverged"
    )


def test_packaged_config_matches_top_level_config() -> None:
    """FIX-06: `config/sprout.yaml` and its packaged mirror must stay byte-identical."""
    top_level = (_ROOT / "config" / "sprout.yaml").read_bytes()
    packaged = resources.packaged_config().read_bytes()
    assert top_level == packaged, "config/sprout.yaml and src/sprout/data/sprout.yaml diverged"


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
