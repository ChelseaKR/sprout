"""``sprout corpus diff``: what changed between two corpus states, and what it moves.

The fixtures build two small corpus roots on disk rather than reusing the repository's
own, so a test can add, remove and edit documents without touching `corpus/`. The eval
impact is exercised against a small suite directory written beside them, with its own
integrity sidecar, because the loader is fail-closed and a missing sidecar is a refusal
rather than a skip.

Four properties get their own tests, because each is a way this tool could quietly lie:

* identical roots produce an empty diff and exit 0;
* an edit to one sentence names the chunk, the eval cases whose answers moved, and the
  smoke questions whose answers moved;
* a removed document that a case still cites is an error and a non-zero exit;
* an analysis that could not run is rendered as not analysed, never as zero affected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from sprout.cli import app
from sprout.config import Config
from sprout.corpus_diff import (
    CorpusDiff,
    CorpusDiffError,
    diff_corpora,
    exit_code_for,
    load_state,
    render_json,
    render_markdown,
)
from sprout.eval.dataset import Dataset, load_cases, write_sidecar

runner = CliRunner()

_POTHOS = """# Pothos care

## Watering

Water Pothos when the top inch of soil has dried out, usually every seven to ten days.
Pothos tolerates a missed watering better than constantly soggy soil.

## Toxicity

The cited reference lists Pothos as toxic to cats and dogs.
Contact a veterinarian if a pet has chewed a Pothos leaf.
"""

_MONSTERA = """# Monstera care

## Watering

Water Monstera when the top two inches of soil have dried out.
Yellowing lower leaves on a Monstera most often indicate overwatering.
"""

_MANIFEST_DEFAULTS = {
    "source_name": "Synthetic Plant-Care Notes",
    "license": "CC0-1.0",
    "fetch_date": "2026-05-01",
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

_CASES: list[dict[str, Any]] = [
    {
        "id": "pothos-watering",
        "question": "How often should I water my Pothos?",
        "language": "en",
        "expected_behavior": "answer",
        "provenance": {"source": "synthetic", "license": "CC0-1.0", "added": "2026-09-06"},
    },
    {
        "id": "monstera-watering",
        "question": "Why are my Monstera leaves yellowing?",
        "language": "en",
        "expected_behavior": "answer",
        "provenance": {"source": "synthetic", "license": "CC0-1.0", "added": "2026-09-06"},
    },
]


def _write_root(root: Path, documents: dict[str, str], *, toxicity: bool = True) -> Path:
    """Write one corpus root: manifest.yaml, processed/, and optionally toxicity.yaml."""
    (root / "processed").mkdir(parents=True, exist_ok=True)
    for name, text in documents.items():
        (root / "processed" / name).write_text(text, encoding="utf-8")
    manifest = {
        "documents": [
            {
                "file": name,
                "title": name.removesuffix(".md").title() + " care",
                "url": f"https://example.invalid/{name.removesuffix('.md')}",
                **_MANIFEST_DEFAULTS,
            }
            for name in sorted(documents)
        ]
    }
    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if toxicity:
        (root / "toxicity.yaml").write_text(
            yaml.safe_dump({"schema_version": 1, "rows": [dict(_TOXICITY_ROW)]}),
            encoding="utf-8",
        )
    return root


def _write_suites(base: Path, cases: list[dict[str, Any]]) -> Path:
    """An eval suite directory plus the integrity sidecar its loader insists on."""
    suites = base / "suites"
    suites.mkdir(parents=True, exist_ok=True)
    (suites / "grounding.yaml").write_text(yaml.safe_dump({"cases": cases}), encoding="utf-8")
    write_sidecar(Dataset.from_items(load_cases(suites / "grounding.yaml")), base / "suites.sha256")
    return suites


@pytest.fixture
def corpora(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(before, after, suites) with `after` a byte-for-byte copy of `before`."""
    before = _write_root(tmp_path / "before", {"pothos.md": _POTHOS, "monstera.md": _MONSTERA})
    after = _write_root(tmp_path / "after", {"pothos.md": _POTHOS, "monstera.md": _MONSTERA})
    suites = _write_suites(tmp_path / "eval", _CASES)
    return before, after, suites


def _diff(
    before: Path,
    after: Path,
    suites: Path,
    *,
    claims_path: str | Path = "does-not-exist.yaml",
    with_impact: bool = True,
) -> CorpusDiff:
    return diff_corpora(
        Config(),
        before,
        after,
        suites_dir=suites,
        claims_path=claims_path,
        with_impact=with_impact,
    )


# --- identical -----------------------------------------------------------------


def test_identical_corpora_produce_an_empty_diff(corpora: tuple[Path, Path, Path]) -> None:
    before, after, suites = corpora
    diff = _diff(before, after, suites)
    assert diff.identical
    assert diff.empty
    assert diff.before_fingerprint == diff.after_fingerprint
    assert not diff.errors
    assert exit_code_for(diff, fail_on_toxicity_change=True) == 0
    assert "nothing to compare" in render_markdown(diff)


def test_the_fingerprint_is_stable_across_runs(corpora: tuple[Path, Path, Path]) -> None:
    before, _, _ = corpora
    config = Config()
    assert load_state(config, before).fingerprint == load_state(config, before).fingerprint


def test_output_is_byte_identical_across_runs(corpora: tuple[Path, Path, Path]) -> None:
    before, after, suites = corpora
    (after / "processed" / "pothos.md").write_text(
        _POTHOS.replace("seven to ten days", "nine to twelve days"), encoding="utf-8"
    )
    first = render_markdown(_diff(before, after, suites))
    second = render_markdown(_diff(before, after, suites))
    assert first == second
    assert render_json(_diff(before, after, suites)) == render_json(_diff(before, after, suites))


# --- one edited sentence -------------------------------------------------------


def test_one_edited_sentence_names_the_chunk_the_cases_and_the_smoke_answers(
    corpora: tuple[Path, Path, Path],
) -> None:
    before, after, suites = corpora
    (after / "processed" / "pothos.md").write_text(
        _POTHOS.replace(
            "when the top inch of soil has dried out, usually every seven to ten days",
            "when the top two inches of soil have dried out, usually every ten to fourteen days",
        ),
        encoding="utf-8",
    )
    diff = _diff(before, after, suites)

    assert [(c.source, c.kind) for c in diff.documents] == [("pothos.md", "changed")]
    assert diff.documents[0].text_changed
    assert [(c.source, c.topic, c.kind) for c in diff.chunks] == [
        ("pothos.md", "watering", "changed")
    ]
    # The chunk id is a hash of the chunk's own text, so it must have moved with the edit.
    assert diff.chunks[0].chunk_id_before != diff.chunks[0].chunk_id_after

    assert diff.eval_section.analysed
    assert diff.eval_section.cases_considered == 2
    moved = {case.case_id for case in diff.eval_cases}
    assert "pothos-watering" in moved
    assert "monstera-watering" not in moved, "an unrelated case must not be reported as moved"

    assert diff.smoke_section.analysed
    smoke = {case.case_id for case in diff.smoke_cases}
    assert "pothos:watering:en" in smoke
    assert "monstera:watering:en" not in smoke


def test_a_manifest_only_change_is_reported_without_a_text_change(
    corpora: tuple[Path, Path, Path],
) -> None:
    before, after, suites = corpora
    manifest = yaml.safe_load((after / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["documents"][0]["fetch_date"] = "2026-08-01"
    (after / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    diff = _diff(before, after, suites)
    change = diff.documents[0]
    assert change.kind == "changed"
    assert not change.text_changed
    assert [(f.field, f.before, f.after) for f in change.manifest_changes] == [
        ("fetch_date", "2026-05-01", "2026-08-01")
    ]
    assert not diff.chunks


# --- removals ------------------------------------------------------------------


def test_a_removed_document_a_case_cites_is_an_error(corpora: tuple[Path, Path, Path]) -> None:
    before, after, suites = corpora
    (after / "processed" / "pothos.md").unlink()
    manifest = yaml.safe_load((after / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["documents"] = [d for d in manifest["documents"] if d["file"] != "pothos.md"]
    (after / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    diff = _diff(before, after, suites)
    assert diff.removed_documents == ("pothos.md",)
    assert any("pothos-watering" in error and "pothos.md" in error for error in diff.errors)
    assert any(case.kind == "grounding_lost" for case in diff.eval_cases)
    assert exit_code_for(diff, fail_on_toxicity_change=False) == 1, (
        "an error must fail whether or not a gate flag was passed"
    )
    assert "## Errors" in render_markdown(diff)


def test_a_removed_document_removes_its_smoke_questions(
    corpora: tuple[Path, Path, Path],
) -> None:
    before, after, suites = corpora
    (after / "processed" / "pothos.md").unlink()
    manifest = yaml.safe_load((after / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["documents"] = [d for d in manifest["documents"] if d["file"] != "pothos.md"]
    (after / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    diff = _diff(before, after, suites)
    removed = {case.case_id for case in diff.smoke_cases if case.kind == "removed"}
    assert "pothos:watering:en" in removed


def test_an_added_document_is_reported_as_added(corpora: tuple[Path, Path, Path]) -> None:
    before, after, suites = corpora
    (after / "processed" / "aloe.md").write_text(
        "# Aloe care\n\n## Watering\n\nWater Aloe sparingly and let it dry fully.\n",
        encoding="utf-8",
    )
    manifest = yaml.safe_load((after / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["documents"].append(
        {
            "file": "aloe.md",
            "title": "Aloe care",
            "url": "https://example.invalid/aloe",
            **_MANIFEST_DEFAULTS,
        }
    )
    (after / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    diff = _diff(before, after, suites)
    assert [(c.source, c.kind) for c in diff.documents] == [("aloe.md", "added")]
    assert [c.kind for c in diff.chunks] == ["added"]
    assert "aloe:watering:en" in {c.case_id for c in diff.smoke_cases if c.kind == "added"}


# --- toxicity ------------------------------------------------------------------


def test_a_toxicity_row_change_is_reported_and_gated(corpora: tuple[Path, Path, Path]) -> None:
    before, after, suites = corpora
    table = yaml.safe_load((after / "toxicity.yaml").read_text(encoding="utf-8"))
    table["rows"][0]["severity_class"] = "moderate"
    (after / "toxicity.yaml").write_text(yaml.safe_dump(table), encoding="utf-8")

    diff = _diff(before, after, suites)
    assert diff.toxicity_analysed
    assert [(c.species_slug, c.animal, c.kind) for c in diff.toxicity] == [
        ("pothos", "cat", "changed")
    ]
    assert [f.field for f in diff.toxicity[0].field_changes] == ["severity_class"]
    assert exit_code_for(diff, fail_on_toxicity_change=False) == 0
    assert exit_code_for(diff, fail_on_toxicity_change=True) == 1


def test_a_missing_toxicity_table_is_not_analysed_rather_than_unchanged(
    tmp_path: Path,
) -> None:
    """The absence-as-a-value trap: no table is not a table with no changes in it."""
    before = _write_root(tmp_path / "before", {"pothos.md": _POTHOS}, toxicity=False)
    after = _write_root(tmp_path / "after", {"pothos.md": _POTHOS}, toxicity=False)
    suites = _write_suites(tmp_path / "eval", _CASES[:1])

    diff = _diff(before, after, suites)
    assert not diff.toxicity_analysed
    assert not diff.toxicity
    assert not diff.toxicity_changed
    assert "toxicity.yaml" in diff.toxicity_not_analysed_reason
    # ...and the gate must not read "no rows changed" off an analysis that never ran.
    assert exit_code_for(diff, fail_on_toxicity_change=True) == 0


# --- analyses that could not run ------------------------------------------------


def test_an_unloadable_eval_dataset_is_not_analysed_rather_than_zero(
    corpora: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    before, after, _ = corpora
    (after / "processed" / "pothos.md").write_text(_POTHOS + "\nExtra sentence.\n", "utf-8")
    diff = _diff(before, after, tmp_path / "no-such-suites")
    assert not diff.eval_section.analysed
    assert not diff.eval_cases
    assert "could not be loaded" in diff.eval_section.not_analysed_reason
    rendered = render_markdown(diff)
    assert "**Not analysed.**" in rendered
    assert "An analysis that did not run is not a result of zero." in rendered


def test_a_missing_claims_registry_is_not_analysed(corpora: tuple[Path, Path, Path]) -> None:
    before, after, suites = corpora
    (after / "processed" / "pothos.md").write_text(_POTHOS + "\nExtra sentence.\n", "utf-8")
    diff = _diff(before, after, suites, claims_path="does-not-exist.yaml")
    assert not diff.claims.analysed
    assert "not a file" in diff.claims.not_analysed_reason


def test_the_committed_registry_has_no_corpus_derived_claim(
    corpora: tuple[Path, Path, Path],
) -> None:
    """Measured, and stated in the report rather than rendered as a reassuring zero.

    If a ``corpus:`` source kind is ever added to ``claims.py`` and used, this test
    fails, and the diff starts naming the entries a corpus change would move.
    """
    before, after, suites = corpora
    (after / "processed" / "pothos.md").write_text(_POTHOS + "\nExtra sentence.\n", "utf-8")
    diff = _diff(before, after, suites, claims_path="docs/claims.yaml")
    assert diff.claims.analysed
    assert diff.claims.entries_read > 0
    assert diff.claims.corpus_derived == ()
    assert "gap in the registry" in render_markdown(diff)


def test_the_markdown_says_a_missing_toxicity_table_was_not_analysed(tmp_path: Path) -> None:
    before = _write_root(tmp_path / "before", {"pothos.md": _POTHOS}, toxicity=False)
    after = _write_root(tmp_path / "after", {"pothos.md": _POTHOS + "\nExtra.\n"}, toxicity=False)
    suites = _write_suites(tmp_path / "eval", _CASES[:1])
    rendered = render_markdown(_diff(before, after, suites))
    assert "A missing table is not a table with no changes in it." in rendered


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("claims: [\n", "is not valid YAML"),
        ("claims: not-a-list\n", "has no 'claims' list"),
        ("something_else: 1\n", "has no 'claims' list"),
    ],
)
def test_an_unreadable_claims_registry_is_not_analysed(
    corpora: tuple[Path, Path, Path], tmp_path: Path, body: str, fragment: str
) -> None:
    before, after, suites = corpora
    (after / "processed" / "pothos.md").write_text(_POTHOS + "\nExtra.\n", "utf-8")
    registry = tmp_path / "claims.yaml"
    registry.write_text(body, encoding="utf-8")
    diff = _diff(before, after, suites, claims_path=registry)
    assert not diff.claims.analysed
    assert fragment in diff.claims.not_analysed_reason


def test_a_corpus_derived_claim_is_named_when_one_exists(
    corpora: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """The branch that turns on the day ``claims.py`` grows a ``corpus:`` source kind."""
    before, after, suites = corpora
    (after / "processed" / "pothos.md").write_text(_POTHOS + "\nExtra.\n", "utf-8")
    registry = tmp_path / "claims.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "claims": [
                    {"id": "doc-species-count", "source": "corpus:species.count"},
                    {"id": "doc-suite-count", "source": "eval-report:suites.count"},
                ]
            }
        ),
        encoding="utf-8",
    )
    diff = _diff(before, after, suites, claims_path=registry)
    assert diff.claims.corpus_derived == ("doc-species-count",)
    assert "`doc-species-count`" in render_markdown(diff)


@pytest.mark.parametrize(
    ("broken", "fragment"),
    [
        ("missing", "corpus root not found"),
        ("no-manifest", "no manifest.yaml"),
        ("no-processed", "no processed/"),
    ],
)
def test_a_bad_corpus_root_fails_closed(tmp_path: Path, broken: str, fragment: str) -> None:
    """Never fall through to the packaged corpus: that would diff it against itself."""
    root = tmp_path / "root"
    if broken != "missing":
        root.mkdir()
    if broken == "no-processed":
        (root / "manifest.yaml").write_text("documents: []\n", encoding="utf-8")
    with pytest.raises(CorpusDiffError, match=fragment):
        load_state(Config(), root)


# --- the CLI --------------------------------------------------------------------


def test_cli_reports_an_edit_and_honours_the_toxicity_gate(
    corpora: tuple[Path, Path, Path],
) -> None:
    before, after, suites = corpora
    table = yaml.safe_load((after / "toxicity.yaml").read_text(encoding="utf-8"))
    table["rows"][0]["principle"] = "insoluble calcium oxalate crystals in the leaf"
    (after / "toxicity.yaml").write_text(yaml.safe_dump(table), encoding="utf-8")

    args = ["corpus", "diff", str(before), str(after), "--suites", str(suites)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "## Toxicity table" in result.output

    gated = runner.invoke(app, [*args, "--fail-on-toxicity-change"])
    assert gated.exit_code == 1


def test_cli_json_and_out_file(corpora: tuple[Path, Path, Path], tmp_path: Path) -> None:
    before, after, suites = corpora
    (after / "processed" / "pothos.md").write_text(_POTHOS + "\nAnother line.\n", "utf-8")
    destination = tmp_path / "reports" / "corpus-diff.json"
    result = runner.invoke(
        app,
        [
            "corpus",
            "diff",
            str(before),
            str(after),
            "--suites",
            str(suites),
            "--json",
            "--out",
            str(destination),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["before_fingerprint"] != payload["after_fingerprint"]
    assert payload["documents"][0]["source"] == "pothos.md"


def test_cli_no_impact_skips_the_reruns(corpora: tuple[Path, Path, Path]) -> None:
    before, after, suites = corpora
    (after / "processed" / "pothos.md").write_text(_POTHOS + "\nAnother line.\n", "utf-8")
    result = runner.invoke(
        app,
        ["corpus", "diff", str(before), str(after), "--suites", str(suites), "--no-impact"],
    )
    assert result.exit_code == 0, result.output
    assert "impact analysis was not requested" in result.output


def test_cli_rejects_a_bad_root_with_exit_two(tmp_path: Path) -> None:
    result = runner.invoke(app, ["corpus", "diff", str(tmp_path / "nope"), str(tmp_path)])
    assert result.exit_code == 2
    assert "cannot diff these corpus roots" in result.output
