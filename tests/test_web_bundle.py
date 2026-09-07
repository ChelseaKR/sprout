"""Can the published browser bundle say which corpus and which config it is running?

Before this, ``web-static/public/data/config.json`` carried exactly one provenance
field, ``format_version``, and grepping the repository showed **nothing read it** — the
index's own ``format_version`` is checked in ``store.ts``, but the config bundle's was
written by the exporter and looked at by no surface, no test, and no gate. So a bundle
exported from last month's corpus was indistinguishable from a current one, and every
comparison built on top of it (the TS↔Python parity gate in #143, the offline banner in
#149) would have been comparing against an unknown.

The tests below are organised around the ways a staleness check like this lies:

* it passes on a bundle it could not read (missing, unparseable, or from before
  provenance existed) — the version this module was written against;
* it compares the index against itself, so re-exporting without re-ingesting looks
  clean;
* it fingerprints something other than the corpus the index was built from;
* it treats an unmeasurable ``fetch_date`` — absent, malformed, or *in the future* — as
  a real date, and a future date then satisfies "how fresh is this" permanently;
* its "deterministic" claim is tested twice inside one interpreter, where dict and set
  iteration are stable and a missing ``sorted()`` is invisible.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from sprout.cli import app
from sprout.config import Config, load_config
from sprout.corpus_diff import corpus_fingerprint
from sprout.ingest import build_index
from sprout.web_bundle import (
    BUNDLE_FORMAT_VERSION,
    BundleProvenance,
    WebBundleError,
    build_provenance,
    check_bundle,
    corpus_root_for,
    export_bundle,
    index_chunk_ids_digest,
    read_provenance,
    render_bundle,
    settings_digest,
)

runner = CliRunner()

_ROOT = Path(__file__).resolve().parent.parent
_TS_CONFIG = _ROOT / "web-static" / "src" / "config.ts"

# Ten documents, not one. A fingerprint over a single document has no ordering to get
# wrong, so a sorting bug in the payload would be unobservable — the same trap that made
# a determinism test in this portfolio pass over a one-row fixture.
_SPECIES = (
    "pothos",
    "monstera",
    "aloe",
    "calathea",
    "dracaena",
    "orchid",
    "philodendron",
    "snake-plant",
    "spider-plant",
    "zz-plant",
)

_DOC = """# {name} care

## Watering

Water {name} when the top inch of soil has dried out, usually every seven to ten days.
{name} tolerates a missed watering better than constantly soggy soil.

## Toxicity

The cited reference lists {name} as toxic to cats and dogs.
Contact a veterinarian if a pet has chewed a {name} leaf.
"""

_MANIFEST_DEFAULTS = {
    "source_name": "Synthetic Plant-Care Notes",
    "license": "CC0-1.0",
    "language": "en",
    "topic": "care",
}

_TOXICITY_ROW = {
    "species_slug": "pothos",
    "species_name": "Pothos (Epipremnum aureum)",
    "animal": "cat",
    "toxic": True,
    "principle": "insoluble calcium oxalate crystals",
    "severity_class": "mild_moderate",
    "source_name": "Synthetic Plant-Care Notes",
    "url": "https://example.invalid/pothos",
    "license": "CC0-1.0",
    "fetch_date": "2026-05-01",
    "synthetic": True,
}

# Enough aliases that the exported mapping's ordering is observable, for the same reason
# the corpus has ten documents rather than one.
_ALIASES = {
    "potos": "pothos",
    "sansevieria": "snake-plant",
    "serpiente": "snake-plant",
    "filodendro": "philodendron",
    "dracena": "dracaena",
    "orquidea": "orchid",
    "calatea": "calathea",
    "cinta": "spider-plant",
    "malamadre": "spider-plant",
    "zamioculca": "zz-plant",
    "sabila": "aloe",
    "costilla": "monstera",
}


def _write_corpus(root: Path, *, dates: dict[str, str] | None = None) -> Path:
    """A corpus root: manifest.yaml beside processed/ and toxicity.yaml."""
    dates = dates or {}
    (root / "processed").mkdir(parents=True, exist_ok=True)
    for slug in _SPECIES:
        (root / "processed" / f"{slug}.md").write_text(
            _DOC.format(name=slug.replace("-", " ").title()), encoding="utf-8"
        )
    manifest = {
        "documents": [
            {
                "file": f"{slug}.md",
                "title": f"{slug} care",
                "url": f"https://example.invalid/{slug}",
                "fetch_date": dates.get(slug, "2026-05-01"),
                **_MANIFEST_DEFAULTS,
            }
            for slug in sorted(_SPECIES)
        ]
    }
    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (root / "toxicity.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "rows": [dict(_TOXICITY_ROW)]}), encoding="utf-8"
    )
    return root


def _config_for(root: Path) -> Config:
    return Config.model_validate(_config_dict(root))


def _config_dict(root: Path) -> dict[str, Any]:
    """A config pinned to ``root``, including ``store.path``.

    ``store.path`` is set deliberately. ``ingest()`` persists to it, and leaving it at the
    default made every run of this file overwrite the repository's own ``var/index.json``
    with a ten-document fixture index — which is how these tests came to poison the real
    conformance fixtures. Tests do not write outside ``tmp_path``.
    """
    return {
        "corpus": {"path": str(root / "processed"), "manifest": str(root / "manifest.yaml")},
        "store": {"path": str(root.parent / "var" / "index.json")},
        "retrieval": {"species_aliases": dict(_ALIASES)},
    }


def _write_config_yaml(path: Path, root: Path) -> Path:
    path.write_text(yaml.safe_dump(_config_dict(root)), encoding="utf-8")
    return path


def _build_index(cfg: Config, index_path: Path) -> Path:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    build_index(cfg).save(index_path)
    return index_path


@pytest.fixture
def bundle(tmp_path: Path) -> tuple[Path, Config, Path, Path]:
    """``(corpus_root, config, index_path, bundle_dir)`` with a freshly exported bundle."""
    root = _write_corpus(tmp_path / "corpus")
    cfg = _config_for(root)
    index = _build_index(cfg, tmp_path / "var" / "index.json")
    out = tmp_path / "data"
    config_yaml = _write_config_yaml(tmp_path / "sprout.yaml", root)
    export_bundle(config_yaml, index, out)
    return root, cfg, index, out


def _read_bundle(out: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((out / "config.json").read_text(encoding="utf-8"))
    return document


# --- what the bundle now records ------------------------------------------------


def test_the_bundle_records_which_corpus_config_and_index_produced_it(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    _, _, _, out = bundle
    document = _read_bundle(out)
    assert document["format_version"] == BUNDLE_FORMAT_VERSION
    provenance = BundleProvenance.model_validate(document["provenance"])
    assert provenance.corpus_fingerprint.startswith("sha256:")
    assert provenance.corpus_documents == len(_SPECIES)
    assert provenance.config_sha256.startswith("sha256:")
    assert provenance.index_sha256.startswith("sha256:")
    assert provenance.index_chunks > 0
    assert provenance.corpus_as_of_earliest == "2026-05-01"
    assert provenance.corpus_dates_unmeasurable == 0
    # The settings the port runs on are still there, unchanged in shape.
    assert document["retrieval"]["species_aliases"] == _ALIASES
    assert document["confidence"]["abstain_threshold"] == Config().confidence.abstain_threshold


def test_the_recorded_fingerprint_is_the_value_corpus_diff_reports(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    """The only reason to record a fingerprint is to compare it against a diff report.

    If these two strings were computed by separate implementations they could disagree
    while both being "correct", and a bundle's fingerprint could not be read beside
    ``sprout corpus diff`` output — which is its entire purpose.
    """
    root, cfg, _, out = bundle
    recorded = read_provenance(out).corpus_fingerprint
    assert recorded == corpus_fingerprint(cfg, corpus_root_for(cfg))
    assert recorded == corpus_fingerprint(cfg, root)


# --- the check catches a stale bundle -------------------------------------------


def test_a_fresh_export_checks_clean(bundle: tuple[Path, Config, Path, Path]) -> None:
    _, cfg, index, out = bundle
    assert check_bundle(out, cfg, index) == []


def test_editing_the_corpus_makes_the_bundle_stale(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    root, cfg, index, out = bundle
    document = root / "processed" / "pothos.md"
    document.write_text(
        document.read_text(encoding="utf-8").replace("seven to ten days", "nine to twelve days"),
        encoding="utf-8",
    )
    _build_index(cfg, index)  # the corpus was re-ingested; the bundle was not re-exported
    problems = check_bundle(out, cfg, index)
    fields = {problem.split(":", 1)[0] for problem in problems}
    assert "corpus_fingerprint" in fields
    assert "index_chunk_ids_sha256" in fields
    assert "index_sha256" in fields


def test_changing_a_threshold_in_the_config_makes_the_bundle_stale(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    """#143's "changing abstain_threshold in Python only fails" case, at bundle level."""
    root, _, index, out = bundle
    moved = Config.model_validate(
        {
            "corpus": {"path": str(root / "processed"), "manifest": str(root / "manifest.yaml")},
            "retrieval": {"species_aliases": dict(_ALIASES)},
            "confidence": {"abstain_threshold": 0.61},
        }
    )
    problems = check_bundle(out, moved, index)
    assert any(problem.startswith("config_sha256:") for problem in problems)
    assert all("corpus_fingerprint" not in problem for problem in problems)


def test_re_exporting_without_re_ingesting_is_refused(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    """The stale bundle a bytes-only check cannot see.

    ``export_web_bundle`` copies whatever ``var/index.json`` holds, so editing the corpus
    and re-exporting without ``make ingest`` writes a *fresh* config.json beside an index
    built from the older passages. Hashing the index file alone would compare that stale
    index against itself and report a clean bundle; the browser would then retrieve text
    the corpus no longer contains, and a parity run would blame the port.
    """
    root, cfg, index, _ = bundle
    document = root / "processed" / "monstera.md"
    document.write_text(document.read_text(encoding="utf-8") + "\nAn added sentence.\n", "utf-8")
    with pytest.raises(WebBundleError) as excinfo:
        build_provenance(cfg, index)
    assert "was not built from the corpus" in str(excinfo.value)


def test_the_chunk_id_digest_does_not_depend_on_the_order_chunks_appear_in(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    """The digest identifies a *set* of passages, not a serialisation of one.

    Written after a measured negative control: dropping the ``sorted()`` from both sides
    of the chunk-id comparison left the whole suite green, because the index writer emits
    chunks in the order the chunker built them and both sides therefore agreed on an
    order neither had chosen. Nothing in the suite reached the sorting, so nothing tested
    it. Permuting the index makes the claim observable, and makes ``sorted()`` a line the
    tests hold rather than a line that happens to be there.
    """
    _, _, index, _ = bundle
    before_count, before_digest = index_chunk_ids_digest(index)

    raw = json.loads(index.read_text(encoding="utf-8"))
    assert len(raw["chunks"]) > 1, "a one-chunk index has no order to permute"
    raw["chunks"] = list(reversed(raw["chunks"]))
    raw["vectors"] = list(reversed(raw["vectors"]))
    shuffled = index.parent / "reversed-index.json"
    shuffled.write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    assert index_chunk_ids_digest(shuffled) == (before_count, before_digest)


# --- the check refuses to pass on what it cannot read ---------------------------


def test_a_bundle_from_before_provenance_existed_is_not_a_pass(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    """The case this module exists for: a version-1 bundle records nothing to compare.

    Silently skipping it would leave a check that exits zero on precisely the artifact
    it was written to catch.
    """
    _, cfg, index, out = bundle
    document = _read_bundle(out)
    del document["provenance"]
    document["format_version"] = 1
    (out / "config.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    with pytest.raises(WebBundleError) as excinfo:
        check_bundle(out, cfg, index)
    assert "format_version 1" in str(excinfo.value)


def test_a_bundle_with_an_empty_provenance_block_is_not_a_pass(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    _, cfg, index, out = bundle
    document = _read_bundle(out)
    document["provenance"] = {}
    (out / "config.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    with pytest.raises(WebBundleError, match="no provenance block"):
        check_bundle(out, cfg, index)


def test_a_partial_provenance_block_is_not_a_pass(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    """A block missing a field must not be read as "that field agrees"."""
    _, cfg, index, out = bundle
    document = _read_bundle(out)
    del document["provenance"]["corpus_fingerprint"]
    (out / "config.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    with pytest.raises(WebBundleError, match="not usable"):
        check_bundle(out, cfg, index)


def test_a_missing_bundle_is_not_a_pass(bundle: tuple[Path, Config, Path, Path]) -> None:
    _, cfg, index, out = bundle
    (out / "config.json").unlink()
    with pytest.raises(WebBundleError, match="does not exist"):
        check_bundle(out, cfg, index)


def test_an_unparseable_bundle_is_not_a_pass(bundle: tuple[Path, Config, Path, Path]) -> None:
    _, cfg, index, out = bundle
    (out / "config.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(WebBundleError, match="not valid JSON"):
        check_bundle(out, cfg, index)


def test_an_index_missing_beside_the_config_is_reported(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    _, cfg, index, out = bundle
    (out / "index.json").unlink()
    problems = check_bundle(out, cfg, index)
    assert any("does not exist" in problem for problem in problems)


def test_an_index_swapped_after_the_export_is_reported(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    """config.json and the index beside it must have been written by the same export."""
    _, cfg, index, out = bundle
    shipped = out / "index.json"
    shipped.write_text(shipped.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    problems = check_bundle(out, cfg, index)
    assert any("not written by the same export" in problem for problem in problems)


def test_an_index_with_no_chunks_is_refused_rather_than_hashed(tmp_path: Path) -> None:
    """An empty index would make every chunk-id comparison vacuously true."""
    root = _write_corpus(tmp_path / "corpus")
    cfg = _config_for(root)
    empty = tmp_path / "var" / "index.json"
    empty.parent.mkdir(parents=True)
    empty.write_text(json.dumps({"format_version": 1, "chunks": [], "vectors": []}), "utf-8")
    with pytest.raises(WebBundleError, match="carries no chunks"):
        build_provenance(cfg, empty)


def test_a_config_whose_halves_point_at_different_trees_fails_closed(tmp_path: Path) -> None:
    """``load_corpus`` falls back to the packaged corpus when a path is absent.

    That fallback is right for ``sprout ask`` on a fresh install and would be silently
    wrong here: a mistyped path would fingerprint the corpus inside the installed wheel
    and record it as this checkout's.
    """
    root = _write_corpus(tmp_path / "corpus")
    (tmp_path / "elsewhere" / "processed").mkdir(parents=True)
    cfg = Config.model_validate(
        {
            "corpus": {
                "path": str(tmp_path / "elsewhere" / "processed"),
                "manifest": str(root / "manifest.yaml"),
            }
        }
    )
    with pytest.raises(WebBundleError, match="two different corpora"):
        corpus_root_for(cfg)


def test_an_absent_corpus_is_an_error_not_an_empty_fingerprint(tmp_path: Path) -> None:
    cfg = Config.model_validate(
        {
            "corpus": {
                "path": str(tmp_path / "nope" / "processed"),
                "manifest": str(tmp_path / "nope" / "manifest.yaml"),
            }
        }
    )
    with pytest.raises(WebBundleError, match="corpus manifest not found"):
        corpus_root_for(cfg)


# --- dates: three states, not two ------------------------------------------------


def test_a_future_fetch_date_is_unmeasurable_not_the_latest_date(tmp_path: Path) -> None:
    """A future timestamp is a broken record, not the freshest data in the corpus.

    Folded into the range it would set ``latest``, and the offline banner would advertise
    a snapshot taken on a date that has not arrived — and would keep doing so for as long
    as the date stayed ahead of the clock.
    """
    root = _write_corpus(tmp_path / "corpus", dates={"pothos": "2099-01-01"})
    cfg = _config_for(root)
    index = _build_index(cfg, tmp_path / "var" / "index.json")
    provenance = build_provenance(cfg, index)
    assert provenance.corpus_as_of_latest == "2026-05-01"
    assert provenance.corpus_dates_unmeasurable == 1
    assert provenance.as_of_display == "2026-05-01"


def test_a_malformed_fetch_date_is_unmeasurable(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path / "corpus", dates={"aloe": "sometime in May"})
    cfg = _config_for(root)
    index = _build_index(cfg, tmp_path / "var" / "index.json")
    provenance = build_provenance(cfg, index)
    assert provenance.corpus_dates_unmeasurable == 1
    assert provenance.corpus_as_of_earliest == "2026-05-01"


def test_a_corpus_with_no_measurable_date_renders_as_unknown(tmp_path: Path) -> None:
    """ "as of " with nothing after it is a rendering bug; "as of today" is a lie."""
    root = _write_corpus(tmp_path / "corpus", dates=dict.fromkeys(_SPECIES, "2099-01-01"))
    cfg = _config_for(root)
    index = _build_index(cfg, tmp_path / "var" / "index.json")
    provenance = build_provenance(cfg, index)
    assert provenance.corpus_as_of_earliest == ""
    assert provenance.corpus_as_of_latest == ""
    assert provenance.corpus_dates_unmeasurable == len(_SPECIES)
    assert provenance.as_of_display == "unknown"


def test_a_date_range_is_rendered_as_a_range(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path / "corpus", dates={"aloe": "2026-01-15"})
    cfg = _config_for(root)
    index = _build_index(cfg, tmp_path / "var" / "index.json")
    assert build_provenance(cfg, index).as_of_display == "2026-01-15 to 2026-05-01"


# --- determinism -----------------------------------------------------------------


def test_the_bundle_is_byte_identical_across_processes(tmp_path: Path) -> None:
    """Across interpreters with ``PYTHONHASHSEED`` varied, not twice inside one.

    Rendering twice in a single process proves nothing about ordering: dict and set
    iteration over the same strings is stable within an interpreter, so a dropped
    ``sorted()`` would be invisible. The fixture is ten documents and a twelve-entry
    alias map for the same reason — one row is always in order.
    """
    root = _write_corpus(tmp_path / "corpus")
    cfg = _config_for(root)
    index = _build_index(cfg, tmp_path / "var" / "index.json")
    config_yaml = _write_config_yaml(tmp_path / "sprout.yaml", root)

    script = (
        "import sys;"
        "from sprout.config import load_config;"
        "from sprout.web_bundle import render_bundle;"
        "sys.stdout.write(render_bundle(load_config(sys.argv[1]), sys.argv[2]))"
    )
    renders = []
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(  # fixed argv, no shell
            [sys.executable, "-c", script, str(config_yaml), str(index)],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        renders.append(result.stdout)
    assert renders[0] == renders[1] == renders[2]
    assert renders[0] == render_bundle(load_config(config_yaml), index)


def test_the_settings_digest_does_not_hash_the_provenance_block(
    bundle: tuple[Path, Config, Path, Path],
) -> None:
    """Otherwise it would be self-referential and could never be recomputed."""
    _, cfg, _, out = bundle
    document = _read_bundle(out)
    assert "provenance" not in json.dumps(settings_digest(cfg))
    recomputed_from_bundle = {
        k: v for k, v in document.items() if k not in {"format_version", "provenance"}
    }
    assert set(recomputed_from_bundle) == {
        "retrieval",
        "generation",
        "confidence",
        "guards",
        "languages",
        "prompts",
    }


# --- the two surfaces agree -------------------------------------------------------


def test_the_typescript_port_expects_the_same_bundle_format_version() -> None:
    """A version the reader does not check is a comment, not a compatibility guard."""
    source = _TS_CONFIG.read_text(encoding="utf-8")
    match = re.search(r"export const BUNDLE_FORMAT_VERSION\s*=\s*(\d+)", source)
    assert match, "web-static/src/config.ts does not export BUNDLE_FORMAT_VERSION"
    assert int(match.group(1)) == BUNDLE_FORMAT_VERSION


def test_the_typescript_port_rejects_a_bundle_with_no_fingerprint() -> None:
    source = _TS_CONFIG.read_text(encoding="utf-8")
    assert "export function assertBundleIsCurrent" in source
    assert "corpus_fingerprint" in source


# --- the CLI ----------------------------------------------------------------------


def test_bundle_check_exits_zero_on_a_fresh_export(
    bundle: tuple[Path, Config, Path, Path], tmp_path: Path
) -> None:
    _, _, index, out = bundle
    result = runner.invoke(
        app,
        [
            "bundle-check",
            str(out),
            "--config",
            str(tmp_path / "sprout.yaml"),
            "--index",
            str(index),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "matches this checkout" in result.output


def test_bundle_check_exits_one_on_a_bundle_it_cannot_read(
    bundle: tuple[Path, Config, Path, Path], tmp_path: Path
) -> None:
    _, _, index, out = bundle
    (out / "config.json").unlink()
    result = runner.invoke(
        app,
        [
            "bundle-check",
            str(out),
            "--config",
            str(tmp_path / "sprout.yaml"),
            "--index",
            str(index),
        ],
    )
    assert result.exit_code == 1, result.output


def test_bundle_check_show_prints_the_recorded_provenance(
    bundle: tuple[Path, Config, Path, Path], tmp_path: Path
) -> None:
    _, _, _, out = bundle
    result = runner.invoke(app, ["bundle-check", str(out), "--show"])
    assert result.exit_code == 0, result.output
    assert read_provenance(out).corpus_fingerprint in result.output
    assert "2026-05-01" in result.output
