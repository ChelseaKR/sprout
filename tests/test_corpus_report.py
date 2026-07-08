"""Corpus workbench tests (EXP-12): completeness matrix, EN/ES parity diff, chunk lint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sprout.cli import app
from sprout.config import Config
from sprout.corpus_report import (
    _name_stems,
    _plant_name,
    build_report,
    render_json,
    render_markdown,
)

runner = CliRunner()

_EN = """# Aloe vera care

## Watering
Aloe vera likes to dry out between waterings. Aloe vera hates soggy soil.

## Toxicity
Aloe vera is toxic to cats and dogs according to the cited source. Keep Aloe vera away from pets.
"""
_ES_GOOD = """# Cuidado del Aloe vera

## Riego
El Aloe vera prefiere secarse entre riegos. El Aloe vera odia el sustrato encharcado.

## Toxicidad
El Aloe vera es tóxico para gatos y perros según la fuente citada.
Mantén el Aloe vera lejos de las mascotas.
"""
_ES_UNTRANSLATED = """# Cuidado del Aloe vera

## Watering
El Aloe vera prefiere secarse entre riegos. El Aloe vera odia el sustrato encharcado.

## Toxicity
El Aloe vera es tóxico para gatos y perros según la fuente citada.
Mantén el Aloe vera lejos de las mascotas.
"""
_ES_MISSING_SECTION = """# Cuidado del Aloe vera

## Riego
El Aloe vera prefiere secarse entre riegos. El Aloe vera odia el sustrato encharcado.
"""

_MANIFEST_ROW = {
    "source_name": "Synthetic Plant-Care Notes",
    "url": "https://example.invalid/aloe",
    "license": "CC0-1.0",
    "fetch_date": "2026-05-01",
    "topic": "care",
}


def _write_corpus(tmp_path: Path, es_text: str, *, extra_species: bool = False) -> Config:
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "aloe.md").write_text(_EN, encoding="utf-8")
    (processed / "aloe.es.md").write_text(es_text, encoding="utf-8")
    docs = [
        {"file": "aloe.md", "title": "Aloe vera care", "language": "en", **_MANIFEST_ROW},
        {"file": "aloe.es.md", "title": "Cuidado del Aloe vera", "language": "es", **_MANIFEST_ROW},
    ]
    if extra_species:
        (processed / "pothos.md").write_text(
            "# Pothos care\n\n## Watering\nPothos likes to dry out. Pothos is easy to grow.\n",
            encoding="utf-8",
        )
        docs.append(
            {"file": "pothos.md", "title": "Pothos care", "language": "en", **_MANIFEST_ROW}
        )
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump({"documents": docs}), encoding="utf-8")
    return Config.model_validate(
        {
            "corpus": {"path": str(processed), "manifest": str(tmp_path / "manifest.yaml")},
            "store": {"path": str(tmp_path / "index.json")},
        }
    )


def test_clean_corpus_reports_no_issues(tmp_path: Path) -> None:
    cfg = _write_corpus(tmp_path, _ES_GOOD)
    report = build_report(cfg)
    assert report.clean
    assert report.species_count == 1
    assert report.document_count == 2
    assert report.parity_issues == ()
    assert report.lint_issues == ()
    assert all(row.complete for row in report.completeness)


def test_untranslated_heading_is_flagged(tmp_path: Path) -> None:
    cfg = _write_corpus(tmp_path, _ES_UNTRANSLATED)
    report = build_report(cfg)
    assert not report.clean
    kinds = {i.kind for i in report.parity_issues}
    assert "untranslated-heading" in kinds
    assert sum(1 for i in report.parity_issues if i.kind == "untranslated-heading") == 2


def test_missing_section_is_flagged_as_count_mismatch_and_gap(tmp_path: Path) -> None:
    cfg = _write_corpus(tmp_path, _ES_MISSING_SECTION)
    report = build_report(cfg)
    assert not report.clean
    kinds = {i.kind for i in report.parity_issues}
    assert "section-count-mismatch" in kinds
    es_row = next(r for r in report.completeness if r.language == "es")
    assert "toxicity" in es_row.missing_topics
    assert not es_row.complete


def test_missing_document_for_a_species_is_flagged(tmp_path: Path) -> None:
    cfg = _write_corpus(tmp_path, _ES_GOOD, extra_species=True)
    report = build_report(cfg)
    assert report.species_count == 2
    missing = [i for i in report.parity_issues if i.kind == "missing-document"]
    assert len(missing) == 1
    assert missing[0].species == "pothos"


def test_over_length_chunk_is_linted(tmp_path: Path) -> None:
    cfg = _write_corpus(tmp_path, _ES_GOOD)
    cfg = cfg.model_copy(update={"chunk": cfg.chunk.model_copy(update={"max_words": 5})})
    report = build_report(cfg)
    assert any(i.kind == "over-length-chunk" for i in report.lint_issues)


def test_low_plant_name_coverage_is_linted(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    text = (
        "# Aloe vera care\n\n## Watering\n"
        "Aloe vera likes to dry out. This plant is otherwise low maintenance. "
        "Do not overwater it. Check the soil weekly. Repot every two years.\n"
    )
    (processed / "aloe.md").write_text(text, encoding="utf-8")
    (processed / "aloe.es.md").write_text(_ES_GOOD, encoding="utf-8")
    docs = [
        {"file": "aloe.md", "title": "Aloe vera care", "language": "en", **_MANIFEST_ROW},
        {"file": "aloe.es.md", "title": "Cuidado del Aloe vera", "language": "es", **_MANIFEST_ROW},
    ]
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump({"documents": docs}), encoding="utf-8")
    cfg = Config.model_validate(
        {
            "corpus": {"path": str(processed), "manifest": str(tmp_path / "manifest.yaml")},
            "store": {"path": str(tmp_path / "index.json")},
        }
    )
    report = build_report(cfg)
    low = [
        i for i in report.lint_issues if i.kind == "low-plant-name-coverage" and i.file == "aloe.md"
    ]
    assert low, report.lint_issues


@pytest.mark.parametrize(
    ("title", "language", "expected"),
    [
        ("Aloe vera care", "en", "Aloe vera"),
        ("Snake plant care and toxicity", "en", "Snake plant"),
        ("Cuidado del Aloe vera", "es", "Aloe vera"),
        ("Cuidado y toxicidad de la lengua de suegra", "es", "lengua de suegra"),
        ("Cuidado de la Planta ZZ", "es", "Planta ZZ"),
    ],
)
def test_plant_name_extraction(title: str, language: str, expected: str) -> None:
    assert _plant_name(title, language) == expected


def test_name_stems_keeps_short_acronyms_whole() -> None:
    assert "zz" in _name_stems("ZZ plant")


def test_render_markdown_and_json_round_trip(tmp_path: Path) -> None:
    cfg = _write_corpus(tmp_path, _ES_UNTRANSLATED)
    report = build_report(cfg)
    md = render_markdown(report)
    assert "# Sprout Corpus Report" in md
    assert "needs review" in md
    payload = json.loads(render_json(report))
    assert payload["species_count"] == 1
    assert len(payload["parity_issues"]) == len(report.parity_issues)


def test_cli_corpus_report_writes_artifacts_and_is_advisory_by_default(tmp_path: Path) -> None:
    cfg_path = tmp_path / "sprout.yaml"
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "aloe.md").write_text(_EN, encoding="utf-8")
    (processed / "aloe.es.md").write_text(_ES_UNTRANSLATED, encoding="utf-8")
    docs = [
        {"file": "aloe.md", "title": "Aloe vera care", "language": "en", **_MANIFEST_ROW},
        {"file": "aloe.es.md", "title": "Cuidado del Aloe vera", "language": "es", **_MANIFEST_ROW},
    ]
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump({"documents": docs}), encoding="utf-8")
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "corpus": {"path": str(processed), "manifest": str(tmp_path / "manifest.yaml")},
                "store": {"path": str(tmp_path / "index.json")},
            }
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "audits"
    result = runner.invoke(
        app,
        ["corpus-report", "--config", str(cfg_path), "--out", str(out_dir)],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "corpus-report.md").exists()
    assert (out_dir / "corpus-report.json").exists()

    gated = runner.invoke(
        app,
        ["corpus-report", "--config", str(cfg_path), "--out", str(out_dir), "--gate"],
    )
    assert gated.exit_code == 1
