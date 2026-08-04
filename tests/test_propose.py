"""SME corpus-contribution workflow tests (research item E5).

The unit tests drive :func:`sprout.propose.review_proposal` directly with an explicit
corpus context, so they never touch the shipped corpus and stay hermetic; the integration
tests at the bottom run the real CLI over the committed worked example.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from sprout.cli import app
from sprout.config import Config
from sprout.propose import (
    TEMPLATE,
    Proposal,
    ProposalError,
    ProposalReview,
    load_proposal,
    proposal_paths,
    render_json,
    render_markdown,
    review_proposal,
)

runner = CliRunner()

TODAY = date(2026, 8, 4)
TARGET_TOPICS = ("watering", "light")

_EN_BODY = """## Watering

Water the Test plant when the top inch of soil has dried.
Reduce watering for the Test plant in winter.

## Light

The Test plant grows best in bright indirect light.
Keep the Test plant out of direct midday sun.
"""

_ES_BODY = """## Riego

Riega la planta de prueba cuando el sustrato se haya secado.
Reduce el riego de la planta de prueba en invierno.

## Luz

La planta de prueba crece mejor con luz indirecta.
Manten la planta de prueba lejos del sol directo del mediodia.
"""

_BASE: dict[str, Any] = {
    "schema_version": 1,
    "species": "test-plant",
    "scientific_name": "Testus plantus",
    "submitter": "an-sme",
    "submitted_date": "2026-05-02",
    "synthetic": True,
    "provenance": {
        "source_name": "Synthetic Plant-Care Notes",
        "url": "https://example.invalid/test-plant",
        "license": "CC0-1.0",
        "fetch_date": "2026-05-01",
        "topic": "care",
    },
    "documents": [
        {"language": "en", "title": "Test plant care", "body": _EN_BODY},
        {"language": "es", "title": "Cuidado de la planta de prueba", "body": _ES_BODY},
    ],
    "eval_case": {
        "id": "groundedness-test-plant-watering",
        "question": "How often should I water my Test plant?",
        "expected_behavior": "answer",
        "language": "en",
        "sources": ["test-plant.md"],
        "expected_facts": ["top inch of soil has dried"],
        "rationale": "Pins the watering answer to the proposed passage.",
        "provenance": {"source": "synthetic", "license": "CC0-1.0", "added": "2026-05-02"},
    },
    "harm_checklist": {
        "reviewer": "an-sme",
        "reviewed_date": "2026-05-02",
        "common_names_regionally_neutral": True,
        "no_medicinal_or_edibility_claims": True,
        "traditional_knowledge_attributed": True,
        "plain_language_reviewed": True,
        "no_derogatory_or_stereotyped_framing": True,
        "notes": "",
    },
}


def _review(
    raw: dict[str, Any],
    *,
    existing_species: frozenset[str] = frozenset(),
    existing_case_ids: frozenset[str] = frozenset(),
    today: date = TODAY,
    repo_root: Path = Path(),
) -> ProposalReview:
    return review_proposal(
        Proposal.model_validate(raw),
        Config(),
        today=today,
        existing_species=existing_species,
        existing_case_ids=existing_case_ids,
        target_topics=TARGET_TOPICS,
        path="test.yaml",
        repo_root=repo_root,
    )


def _mutate(**changes: Any) -> dict[str, Any]:
    raw = copy.deepcopy(_BASE)
    raw.update(changes)
    return raw


def _codes(review: ProposalReview) -> set[str]:
    return {f.code for f in review.findings}


# --- the happy path ----------------------------------------------------------------


def test_a_clean_proposal_is_ready_to_merge() -> None:
    review = _review(_BASE)
    assert review.findings == ()
    assert review.status == "ready-to-merge"
    assert review.requires_expert_review is False
    assert review.content_hash


def test_toxicity_prose_makes_a_clean_proposal_expert_gated() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][0]["body"] = _EN_BODY + (
        "\n## Toxicity\n\nThe cited reference does not list Test plant as toxic to cats. "
        "Contact a veterinarian if your Test plant is chewed.\n"
    )
    raw["documents"][1]["body"] = _ES_BODY + (
        "\n## Toxicidad\n\nLa referencia citada no incluye la planta de prueba como toxica "
        "para gatos. Consulta a un veterinario si mastican la planta de prueba.\n"
    )
    review = _review(raw)
    assert _codes(review) <= {"topic-outside-taxonomy"}
    assert review.errors == ()
    assert review.requires_expert_review is True
    assert review.status == "ready-for-expert-review"


def test_a_toxicity_eval_case_alone_triggers_expert_review() -> None:
    raw = copy.deepcopy(_BASE)
    raw["eval_case"]["is_toxicity_query"] = True
    assert _review(raw).status == "ready-for-expert-review"


def test_ingestion_prose_without_a_toxicity_heading_still_gates_on_expert_review() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][0]["body"] += "\nKeep the Test plant where pets cannot ingest the leaves.\n"
    review = _review(raw)
    assert review.errors == ()
    assert review.status == "ready-for-expert-review"


# --- identity and provenance -------------------------------------------------------


def test_unsupported_schema_version_is_rejected() -> None:
    assert "schema-version" in _codes(_review(_mutate(schema_version=2)))


def test_species_must_be_a_corpus_slug() -> None:
    assert "species-slug" in _codes(_review(_mutate(species="Test Plant")))


def test_species_already_in_the_corpus_is_rejected() -> None:
    review = _review(_BASE, existing_species=frozenset({"test-plant"}))
    assert "species-already-in-corpus" in _codes(review)
    assert review.status == "changes-requested"


def test_scientific_name_is_required() -> None:
    assert "scientific-name-missing" in _codes(_review(_mutate(scientific_name="   ")))


def test_license_must_be_allowlisted() -> None:
    raw = copy.deepcopy(_BASE)
    raw["provenance"]["license"] = "All rights reserved"
    assert "license-not-allowlisted" in _codes(_review(raw))


def test_url_must_be_http() -> None:
    raw = copy.deepcopy(_BASE)
    raw["provenance"]["url"] = "ftp://example.invalid/test-plant"
    assert "provenance-url" in _codes(_review(raw))


def test_synthetic_content_must_use_the_placeholder_host() -> None:
    raw = copy.deepcopy(_BASE)
    raw["provenance"]["url"] = "https://extension.example.edu/test-plant"
    codes = _codes(_review(raw))
    assert "synthetic-url-must-be-placeholder" in codes


def test_real_content_needs_a_real_host_and_an_expert_signoff(tmp_path: Path) -> None:
    raw = _mutate(synthetic=False)
    codes = _codes(_review(raw))
    assert "real-url-must-not-be-placeholder" in codes
    assert "real-content-needs-expert-review" in codes

    artifact = tmp_path / "docs" / "audits" / "signoff.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("signed off", encoding="utf-8")
    raw = _mutate(
        synthetic=False,
        expert_review={
            "reviewer": "A Reviewer",
            "credential": "DVM, DABVT",
            "reviewed_date": "2026-05-02",
            "scope": "toxicity prose EN + ES",
            "artifact": "docs/audits/signoff.md",
        },
    )
    raw["provenance"]["url"] = "https://extension.example.edu/test-plant"
    review = _review(raw, repo_root=tmp_path)
    assert review.findings == ()
    assert review.status == "ready-to-merge"


def test_expert_review_artifact_must_exist_and_be_complete() -> None:
    raw = _mutate(
        expert_review={
            "reviewer": "A Reviewer",
            "credential": "  ",
            "reviewed_date": "2026-05-02",
            "scope": "toxicity prose",
            "artifact": "docs/audits/does-not-exist.md",
        }
    )
    codes = _codes(_review(raw))
    assert "expert-review-artifact-missing" in codes
    assert "expert-review-incomplete" in codes


def test_future_and_unparseable_dates_are_errors() -> None:
    assert "date-in-future" in _codes(_review(_mutate(submitted_date="2026-12-01")))
    assert "date-unparseable" in _codes(_review(_mutate(submitted_date="last tuesday")))
    raw = copy.deepcopy(_BASE)
    raw["harm_checklist"]["reviewed_date"] = "2026-13-45"
    assert "date-unparseable" in _codes(_review(raw))


def test_unusable_fetch_date_is_an_error_but_staleness_is_only_a_warning() -> None:
    raw = copy.deepcopy(_BASE)
    raw["provenance"]["fetch_date"] = "not-a-date"
    assert "fetch-date-unusable" in _codes(_review(raw))

    stale = _review(_BASE, today=date(2028, 1, 1))
    assert "citation-stale" in _codes(stale)
    assert stale.errors == ()
    assert stale.warnings


# --- languages, topics, corpus lint -------------------------------------------------


def test_every_supported_language_must_be_proposed() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"] = [raw["documents"][0]]
    assert "language-coverage" in _codes(_review(raw))


def test_a_proposal_missing_the_reference_language_is_rejected() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"] = [raw["documents"][1]]
    review = _review(raw)
    assert "language-coverage" in _codes(review)
    assert "topic-coverage" not in _codes(review)  # nothing to compare the taxonomy against


def test_a_proposal_with_no_documents_at_all_is_rejected() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"] = []
    review = _review(raw)
    assert "language-coverage" in _codes(review)
    assert review.status == "changes-requested"


def test_unsupported_language_is_rejected() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"] = [*raw["documents"], {"language": "fr", "title": "T", "body": _EN_BODY}]
    assert "language-unsupported" in _codes(_review(raw))


def test_empty_document_is_rejected() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][1]["body"] = "   "
    assert "document-empty" in _codes(_review(raw))


def test_missing_taxonomy_section_is_an_error() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][0]["body"] = "## Watering\n\nWater the Test plant weekly.\n"
    raw["documents"][1]["body"] = "## Riego\n\nRiega la planta de prueba cada semana.\n"
    assert "topic-coverage" in _codes(_review(raw))


def test_extra_and_reordered_sections_are_warnings() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][0]["body"] = (
        "## Light\n\nThe Test plant likes bright indirect light.\n\n"
        "## Watering\n\nWater the Test plant when the top inch of soil has dried.\n"
    )
    raw["documents"][1]["body"] = (
        "## Luz\n\nLa planta de prueba prefiere luz indirecta.\n\n"
        "## Riego\n\nRiega la planta de prueba cuando el sustrato se haya secado.\n"
    )
    review = _review(raw)
    assert "topic-order" in _codes(review)
    assert review.errors == ()

    raw["documents"][0]["body"] += "\n## Propagation\n\nDivide the Test plant in spring.\n"
    raw["documents"][1]["body"] += "\n## Propagacion\n\nDivide la planta de prueba en primavera.\n"
    assert "topic-outside-taxonomy" in _codes(_review(raw))


def test_untranslated_spanish_heading_fails_parity() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][1]["body"] = _ES_BODY.replace("## Riego", "## Watering")
    assert "parity-untranslated-heading" in _codes(_review(raw))


def test_section_count_mismatch_fails_parity() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][1]["body"] += "\n## Extra\n\nLa planta de prueba tolera el frio.\n"
    assert "parity-section-count-mismatch" in _codes(_review(raw))


def test_a_passage_that_rarely_names_its_plant_warns() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][0]["body"] = (
        "## Watering\n\nWater it weekly. Keep the soil moist. Do not let it dry out.\n\n"
        "## Light\n\nIt likes bright indirect light. Avoid the midday sun.\n"
    )
    raw["eval_case"]["expected_facts"] = ["keep the soil moist"]
    review = _review(raw)
    assert "lint-low-plant-name-coverage" in _codes(review)
    assert review.errors == ()


def test_an_over_long_sentence_fails_the_chunk_lint() -> None:
    raw = copy.deepcopy(_BASE)
    long_sentence = "The Test plant " + "grows and grows " * 70 + "in bright light."
    raw["documents"][0]["body"] = f"## Watering\n\n{long_sentence}\n\n## Light\n\n{long_sentence}\n"
    assert "lint-over-length-chunk" in _codes(_review(raw))


# --- safety and representational harm ------------------------------------------------


@pytest.mark.parametrize(
    ("index", "sentence"),
    [
        (0, "The Test plant is safe for cats and dogs."),
        (1, "La planta de prueba es segura para gatos y perros."),
    ],
)
def test_a_passage_may_never_certify_safety(index: int, sentence: str) -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][index]["body"] += f"\n{sentence}\n"
    review = _review(raw)
    assert "safety-certification" in _codes(review)
    assert review.status == "changes-requested"


@pytest.mark.parametrize(
    ("index", "sentence"),
    [
        (0, "The Test plant cures a sore throat and its leaves are edible."),
        (1, "La planta de prueba es un remedio medicinal comestible."),
    ],
)
def test_medicinal_and_edibility_claims_are_rejected(index: int, sentence: str) -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][index]["body"] += f"\n{sentence}\n"
    review = _review(raw)
    assert "medicinal-or-edibility-claim" in _codes(review)
    detail = next(f.detail for f in review.findings if f.code == "medicinal-or-edibility-claim")
    assert "no_medicinal_or_edibility_claims is affirmed" in detail


def test_a_claim_with_the_box_unticked_still_fails_but_without_the_contradiction_note() -> None:
    raw = copy.deepcopy(_BASE)
    raw["documents"][0]["body"] += "\nThe Test plant is edible.\n"
    raw["harm_checklist"]["no_medicinal_or_edibility_claims"] = False
    review = _review(raw)
    codes = _codes(review)
    assert {"medicinal-or-edibility-claim", "harm-checklist-unaffirmed"} <= codes
    detail = next(f.detail for f in review.findings if f.code == "medicinal-or-edibility-claim")
    assert "is affirmed" not in detail


def test_every_harm_checklist_box_must_be_affirmed_and_owned() -> None:
    raw = copy.deepcopy(_BASE)
    raw["harm_checklist"]["common_names_regionally_neutral"] = False
    raw["harm_checklist"]["reviewer"] = " "
    codes = _codes(_review(raw))
    assert {"harm-checklist-unaffirmed", "harm-checklist-unattributed"} <= codes


# --- the eval case -------------------------------------------------------------------


def test_a_malformed_eval_case_fails_closed() -> None:
    assert "eval-case-schema" in _codes(_review(_mutate(eval_case={"id": "x"})))


def test_a_taken_case_id_is_rejected() -> None:
    review = _review(_BASE, existing_case_ids=frozenset({"groundedness-test-plant-watering"}))
    assert "eval-case-id-taken" in _codes(review)


def test_an_unsupported_case_language_is_rejected() -> None:
    raw = copy.deepcopy(_BASE)
    raw["eval_case"]["language"] = "fr"
    assert "eval-case-language" in _codes(_review(raw))


def test_the_case_must_cite_the_proposed_passage() -> None:
    raw = copy.deepcopy(_BASE)
    raw["eval_case"]["sources"] = ["monstera.md"]
    assert "eval-case-not-grounded-in-proposal" in _codes(_review(raw))


def test_an_expected_fact_absent_from_the_passage_is_rejected() -> None:
    raw = copy.deepcopy(_BASE)
    raw["eval_case"]["expected_facts"] = ["water it every single day"]
    assert "expected-fact-unsupported" in _codes(_review(raw))


def test_a_case_that_asserts_nothing_is_rejected() -> None:
    raw = copy.deepcopy(_BASE)
    raw["eval_case"]["expected_facts"] = []
    assert "eval-case-no-assertion" in _codes(_review(raw))


def test_a_refusal_case_needs_no_expected_facts() -> None:
    raw = copy.deepcopy(_BASE)
    raw["eval_case"]["expected_facts"] = []
    raw["eval_case"]["should_refuse"] = True
    raw["eval_case"]["expected_behavior"] = "refuse-and-redirect"
    assert "eval-case-no-assertion" not in _codes(_review(raw))


# --- loading, rendering, and the CLI --------------------------------------------------


def test_load_proposal_fails_closed(tmp_path: Path) -> None:
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("just a string\n", encoding="utf-8")
    with pytest.raises(ProposalError, match="mapping"):
        load_proposal(scalar)

    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"species": "x", "nope": 1}), encoding="utf-8")
    with pytest.raises(ProposalError, match="schema error"):
        load_proposal(bad)


def test_proposal_paths_expands_dirs_and_rejects_missing(tmp_path: Path) -> None:
    (tmp_path / "b.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "a.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert [p.name for p in proposal_paths([str(tmp_path)])] == ["a.yaml", "b.yaml"]
    assert [p.name for p in proposal_paths([str(tmp_path / "a.yaml")])] == ["a.yaml"]
    with pytest.raises(ProposalError, match="no such proposal"):
        proposal_paths([str(tmp_path / "missing.yaml")])


def test_existing_case_ids_reads_committed_suites_and_tolerates_absence(tmp_path: Path) -> None:
    from sprout.propose import existing_case_ids

    assert existing_case_ids(tmp_path / "nope") == frozenset()
    (tmp_path / "keyed.yaml").write_text(
        yaml.safe_dump({"cases": [{"id": "a-1"}, {"no-id": 1}, "not-a-mapping"]}),
        encoding="utf-8",
    )
    (tmp_path / "bare.yaml").write_text(yaml.safe_dump([{"id": "b-1"}]), encoding="utf-8")
    assert existing_case_ids(tmp_path) == frozenset({"a-1", "b-1"})


def test_the_template_matches_the_schema_but_does_not_pass_review(tmp_path: Path) -> None:
    path = tmp_path / "template.yaml"
    path.write_text(TEMPLATE, encoding="utf-8")
    proposal = load_proposal(path)  # the shipped template is schema-valid...
    assert proposal.species == "my-plant"
    review = _review(proposal.model_dump())  # ...and honestly fails until it is filled in
    assert review.status == "changes-requested"


def test_rendering_reports_findings_and_statuses() -> None:
    clean = _review(_BASE)
    broken = _review(_mutate(species="Not A Slug"))
    markdown = render_markdown([clean, broken])
    assert "✅ ready to merge" in markdown
    assert "❌ changes requested" in markdown
    assert "`species-slug`" in markdown
    assert "No findings." in markdown

    payload = json.loads(render_json([clean, broken]))
    assert [row["status"] for row in payload] == ["ready-to-merge", "changes-requested"]


def test_expert_review_banner_is_rendered() -> None:
    raw = copy.deepcopy(_BASE)
    raw["eval_case"]["is_toxicity_query"] = True
    assert "veterinary toxicologist" in render_markdown([_review(raw)])


@pytest.mark.integration
def test_cli_reviews_the_committed_example() -> None:
    result = runner.invoke(app, ["propose", "check", "examples/corpus-proposal"])
    assert result.exit_code == 0, result.output
    assert "parlor-palm" in result.output
    assert "0 need changes" in result.output


@pytest.mark.integration
def test_cli_can_require_the_expert_signoff_and_write_artifacts(tmp_path: Path) -> None:
    out = tmp_path / "audits"
    result = runner.invoke(
        app,
        [
            "propose",
            "check",
            "examples/corpus-proposal/parlor-palm.yaml",
            "--today",
            "2026-08-04",
            "--out",
            str(out),
            "--require-expert-review",
        ],
    )
    assert result.exit_code == 1, result.output
    assert (out / "corpus-proposal-review.md").exists()
    payload = json.loads((out / "corpus-proposal-review.json").read_text(encoding="utf-8"))
    assert payload[0]["status"] == "ready-for-expert-review"
    assert payload[0]["findings"] == []


@pytest.mark.integration
def test_cli_json_output_and_missing_path() -> None:
    result = runner.invoke(app, ["propose", "check", "examples/corpus-proposal", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output.split("propose:")[0])[0]["species"] == "parlor-palm"

    missing = runner.invoke(app, ["propose", "check", "no/such/dir"])
    assert missing.exit_code == 2
    assert "no such proposal" in missing.output


def test_cli_template_round_trips(tmp_path: Path) -> None:
    result = runner.invoke(app, ["propose", "template"])
    assert result.exit_code == 0
    path = tmp_path / "t.yaml"
    path.write_text(result.output, encoding="utf-8")
    assert load_proposal(path).species == "my-plant"
