"""Toxicity table tests (EXP-09): schema invariants, coverage, table-vs-prose consistency."""

from __future__ import annotations

from pathlib import Path

import pytest

from sprout.models import Document
from sprout.toxicity import (
    ToxicityRow,
    check_consistency,
    coverage_report,
    load_toxicity_table,
    species_animal_pairs,
)

_TOXIC_ROW = """rows:
  - species_slug: aloe
    species_name: Aloe vera (Aloe barbadensis)
    animal: cat
    toxic: true
    principle: saponins and anthraquinones
    severity_class: mild_moderate
    source_name: Synthetic Plant-Care Notes
    url: https://example.invalid/aloe
    license: CC0-1.0
    fetch_date: "2026-05-01"
    synthetic: true
"""

_NONTOXIC_ROW = """rows:
  - species_slug: boston-fern
    species_name: Boston fern (Nephrolepis exaltata)
    animal: cat
    toxic: false
    principle: not listed as toxic by the cited source (non-toxic is not the same as safe)
    severity_class: not_applicable
    source_name: Synthetic Plant-Care Notes
    url: https://example.invalid/boston-fern
    license: CC0-1.0
    fetch_date: "2026-05-01"
    synthetic: true
"""


def _doc(source: str, text: str, language: str = "en") -> Document:
    return Document(
        doc_id=source,
        source=source,
        title=source,
        language=language,
        text=text,
        source_name="Synthetic Plant-Care Notes",
        url=f"https://example.invalid/{source}",
        license="CC0-1.0",
        fetch_date="2026-05-01",
        topic="care",
    )


def test_load_real_corpus_toxicity_table() -> None:
    path = Path(__file__).resolve().parent.parent / "corpus" / "toxicity.yaml"
    rows = load_toxicity_table(path)
    assert len(rows) >= 30
    assert all(row.synthetic for row in rows)
    assert all("example.invalid" in row.url for row in rows)
    # Every species covers at least cat and dog.
    pairs = species_animal_pairs(rows)
    slugs = {slug for slug, _ in pairs}
    for slug in slugs:
        assert (slug, "cat") in pairs
        assert (slug, "dog") in pairs


def test_load_toxicity_table_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_toxicity_table(tmp_path / "absent.yaml")


def test_load_toxicity_table_empty(tmp_path: Path) -> None:
    p = tmp_path / "t.yaml"
    p.write_text("rows: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no 'rows'"):
        load_toxicity_table(p)


def test_load_toxicity_table_parses_rows(tmp_path: Path) -> None:
    p = tmp_path / "t.yaml"
    p.write_text(_TOXIC_ROW, encoding="utf-8")
    rows = load_toxicity_table(p)
    assert len(rows) == 1
    assert rows[0].toxic is True
    assert rows[0].severity_class == "mild_moderate"


def test_toxic_row_requires_non_not_applicable_severity() -> None:
    with pytest.raises(ValueError, match="not_applicable"):
        ToxicityRow(
            species_slug="x",
            species_name="X",
            animal="cat",
            toxic=True,
            principle="p",
            severity_class="not_applicable",
            source_name="s",
            url="https://example.invalid/x",
            license="CC0-1.0",
            fetch_date="2026-05-01",
        )


def test_nontoxic_row_requires_not_applicable_severity() -> None:
    with pytest.raises(ValueError, match="not_applicable"):
        ToxicityRow(
            species_slug="x",
            species_name="X",
            animal="cat",
            toxic=False,
            principle="not listed",
            severity_class="mild",
            source_name="s",
            url="https://example.invalid/x",
            license="CC0-1.0",
            fetch_date="2026-05-01",
        )


def test_unknown_severity_class_rejected() -> None:
    with pytest.raises(ValueError, match="severity_class"):
        ToxicityRow(
            species_slug="x",
            species_name="X",
            animal="cat",
            toxic=True,
            principle="p",
            severity_class="lethal",  # not in the SME-gated vocabulary
            source_name="s",
            url="https://example.invalid/x",
            license="CC0-1.0",
            fetch_date="2026-05-01",
        )


def test_synthetic_row_cannot_point_at_a_real_domain() -> None:
    """A synthetic=true row with a non-placeholder URL would silently defeat the SME gate."""
    with pytest.raises(ValueError, match="non-placeholder"):
        ToxicityRow(
            species_slug="x",
            species_name="X",
            animal="cat",
            toxic=True,
            principle="p",
            severity_class="mild",
            source_name="s",
            url="https://aspca.org/toxic-plants/x",
            license="CC0-1.0",
            fetch_date="2026-05-01",
            synthetic=True,
        )


def test_non_synthetic_row_cannot_keep_the_placeholder_domain() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        ToxicityRow(
            species_slug="x",
            species_name="X",
            animal="cat",
            toxic=True,
            principle="p",
            severity_class="mild",
            source_name="s",
            url="https://example.invalid/x",
            license="CC0-1.0",
            fetch_date="2026-05-01",
            synthetic=False,
        )


def test_coverage_report_groups_by_species_and_animal() -> None:
    rows = load_toxicity_table_from_text(_TOXIC_ROW + _NONTOXIC_ROW.removeprefix("rows:\n"))
    report = coverage_report(rows)
    assert set(report) == {"aloe", "boston-fern"}
    assert report["aloe"]["cat"].toxic is True
    assert report["boston-fern"]["cat"].toxic is False


def load_toxicity_table_from_text(text: str) -> list[ToxicityRow]:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.yaml"
        p.write_text(text, encoding="utf-8")
        return load_toxicity_table(p)


def test_check_consistency_passes_when_table_matches_prose() -> None:
    rows = load_toxicity_table_from_text(_TOXIC_ROW)
    doc = _doc(
        "aloe.md",
        "## Toxicity\nThe cited reference lists Aloe vera as toxic to cats and dogs.\n",
    )
    assert check_consistency(rows, [doc]) == []


def test_check_consistency_flags_a_contradiction() -> None:
    rows = load_toxicity_table_from_text(_TOXIC_ROW)  # says toxic=true
    doc = _doc(
        "aloe.md",
        "## Toxicity\nThe cited reference does not list Aloe vera as toxic to cats or dogs.\n",
    )
    problems = check_consistency(rows, [doc])
    assert len(problems) == 1
    assert "aloe/cat" in problems[0]
    assert "aloe/dog" not in "".join(problems)  # only the cat row was in this table


def test_check_consistency_ignores_non_cat_dog_animals() -> None:
    rows = load_toxicity_table_from_text(
        """rows:
  - species_slug: orchid
    species_name: Orchid (Phalaenopsis)
    animal: horse
    toxic: false
    principle: not listed as toxic by the cited source (non-toxic is not the same as safe)
    severity_class: not_applicable
    source_name: Synthetic Plant-Care Notes
    url: https://example.invalid/orchid
    license: CC0-1.0
    fetch_date: "2026-05-01"
    synthetic: true
"""
    )
    # No documents at all -- a horse row must not be flagged as missing prose.
    assert check_consistency(rows, []) == []


def test_check_consistency_flags_missing_document() -> None:
    rows = load_toxicity_table_from_text(_TOXIC_ROW)
    assert check_consistency(rows, []) == [
        "aloe/cat: table row has no matching English document with a Toxicity "
        "section to check against"
    ]


def test_real_corpus_table_is_consistent_with_real_corpus_prose() -> None:
    """End-to-end: the committed table agrees with the committed prose for every species."""
    from sprout.config import Config
    from sprout.ingest import load_corpus

    root = Path(__file__).resolve().parent.parent
    rows = load_toxicity_table(root / "corpus" / "toxicity.yaml")
    cfg = Config.model_validate(
        {
            "corpus": {
                "path": str(root / "corpus" / "processed"),
                "manifest": str(root / "corpus" / "manifest.yaml"),
            }
        }
    )
    documents = load_corpus(cfg)
    assert check_consistency(rows, documents) == []
