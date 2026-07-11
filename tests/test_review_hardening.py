"""Regression tests for the adversarial-review hardening pass.

Each test pins a specific verified finding so it cannot silently regress: the cloud-path
citation-guard polarity/empty-needle gates, the negation-aware never-certify-safe guard
(with the source-attribution exemption CLAUDE.md requires), PII redaction wiring,
fail-closed dataset integrity, and the multilingual parity rigor checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sprout.config import Config
from sprout.eval.dataset import (
    Dataset,
    DatasetError,
    DatasetItem,
    Provenance,
    TargetResponse,
    load_suite_dir,
)
from sprout.eval.judge import DeterministicJudge
from sprout.eval.runner import run_evaluation
from sprout.eval.suite import Verdict, resolve_suites
from sprout.guards import asserts_safety, citation_guard, redact_pii
from sprout.models import Chunk, RetrievedChunk
from sprout.providers.deterministic import HashingEmbedding

GUARDS = Config().guards
PROV = Provenance(source="synthetic", license="CC0-1.0", added="2026-06-22")


def _make_chunk(text: str, source: str = "pothos.md", topic: str = "toxicity") -> Chunk:
    return Chunk(
        chunk_id="c1",
        doc_id=source.split(".")[0],
        title="Pothos",
        source=source,
        text=text,
        language="en",
        topic=topic,
        source_name="Synthetic",
        url=f"https://example.invalid/{source}",
        license="CC0-1.0",
        fetch_date="2026-05-01",
    )


# --- citation guard: polarity + empty-needle (cloud-path hardening) --------------
def _chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(chunk=_make_chunk(text), score=0.6)


def test_citation_guard_rejects_polarity_inversion() -> None:
    rc = _chunk("Pothos is toxic to cats and dogs and causes oral irritation.")
    # A free-text cloud sentence that inverts polarity must NOT pass on token coverage.
    out = citation_guard([("Pothos is not toxic to cats.", "c1")], [rc], 0.66)
    assert out == []


def test_citation_guard_rejects_antonym_flip_without_negation() -> None:
    """ "Safe" vs "toxic" carries no explicit negation marker, but it is still a flat
    polarity contradiction the citation guard must reject (not just high-coverage-passes)."""
    rc = _chunk("Aloe vera is toxic to dogs and cats.")
    out = citation_guard([("Aloe vera is safe for dogs and cats.", "c1")], [rc], 0.66)
    assert out == []


def test_citation_guard_rejects_contentless_fragment() -> None:
    rc = _chunk("Pothos is toxic to cats and dogs.")
    out = citation_guard([("No, it is not.", "c1")], [rc], 0.66)
    assert out == []


def test_citation_guard_still_accepts_verbatim_grounded() -> None:
    rc = _chunk("Pothos is toxic to cats and dogs.")
    out = citation_guard([("Pothos is toxic to cats and dogs.", "c1")], [rc], 0.66)
    assert len(out) == 1


# --- never-certify-safe: negation-aware, source-attribution exempt ---------------
@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Spider plant is not toxic to cats.", True),  # bare negated-harm certification
        ("It poses no risk to your dog.", True),
        ("It is pet-safe and pet friendly.", True),  # hyphen-folded deny-list
        ("This plant is considered safe to keep.", True),
        ("No es tóxico para los gatos.", True),  # Spanish, accent + negation
        ("no es tóxíca", True),  # accent-noise variant must still fold
        # Source-attributed reports of silence are permitted (CLAUDE.md: state the source).
        ("The cited reference does not list Spider plant as toxic to cats or dogs.", False),
        ("La fuente citada no indica que sea tóxica.", False),
        # Genuine toxicity statements and the routing line are not certifications.
        ("The cited source lists Pothos as toxic to cats.", False),
        ("I can't certify any plant safe; contact your vet.", False),
    ],
)
def test_asserts_safety(text: str, flagged: bool) -> None:
    lang = "es" if any(c in text for c in "ñáéíóú") else "en"
    assert asserts_safety(text, lang, GUARDS) is flagged


# --- PII redaction wiring --------------------------------------------------------
class _CapturingGenerator:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def generate(
        self, query: str, context: list[RetrievedChunk], max_sentences: int
    ) -> list[tuple[str, str]]:
        self.seen.append(query)
        return []

    def estimated_cost_usd(self, query: str, context: list[RetrievedChunk]) -> float:
        return 0.0


def test_redact_query_pii_flag_is_wired() -> None:
    from sprout.answer import Assistant
    from sprout.store import VectorStore

    cfg = Config.model_validate({"generation": {"redact_query_pii": True}})
    emb = HashingEmbedding(dim=64)
    store = VectorStore()
    chunk = _make_chunk("Yellow leaves mean overwatering.", "monstera.md", "watering")
    store.add(chunk, emb.embed(chunk.text))
    gen = _CapturingGenerator()
    a = Assistant(cfg, store, emb, gen)
    a.answer("monstera yellow leaves email me at a@b.com")
    assert gen.seen, "generator should have been called"
    assert "a@b.com" not in gen.seen[0]
    assert "[email]" in gen.seen[0]


def test_redact_pii_email_is_redos_bounded() -> None:
    # Bounded quantifiers: a pathological near-email must return quickly, not hang.
    redact_pii("a@" + "x" * 6000)


# --- fail-closed dataset integrity -----------------------------------------------
def test_missing_sidecar_fails_closed(tmp_path: Path) -> None:
    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "g.yaml").write_text(
        "cases:\n  - id: g1\n    question: q\n"
        '    provenance: {source: s, license: CC0-1.0, added: "2026-06-22"}\n',
        encoding="utf-8",
    )
    with pytest.raises(DatasetError, match="sidecar"):
        load_suite_dir(suites, verify_hash=True)  # no suites.sha256 present
    # The explicit baseline path still bypasses (verify_hash=False).
    assert load_suite_dir(suites, verify_hash=False).items


# --- multilingual parity rigor ---------------------------------------------------
def _mk(**kw: object) -> DatasetItem:
    return DatasetItem.model_validate({"provenance": PROV, **kw})


def _ml_run(items: list[DatasetItem]) -> Verdict:
    result = run_evaluation(
        Dataset.from_items(items),
        DeterministicJudge(),
        resolve_suites("multilingual"),
        target="t",
    )
    return result.suite_results[0].verdict


def test_multilingual_fails_same_language_pair() -> None:
    cite = ["Monstera care — monstera.md (as of 2026-05-01)"]
    en = _mk(
        id="p-en",
        question="why yellow?",
        pair_id="p",
        is_reference=True,
        language="en",
        target_response=TargetResponse(
            text="Yellowing means overwatering.", citations=cite, language="en"
        ),
    )
    # Same language as the reference -> not actually a translation -> must fail.
    fake = _mk(
        id="p-x",
        question="why yellow?",
        pair_id="p",
        language="en",
        target_response=TargetResponse(
            text="Yellowing means overwatering.", citations=cite, language="en"
        ),
    )
    assert _ml_run([en, fake]) is Verdict.FAIL


def test_multilingual_fails_pair_without_translation() -> None:
    cite = ["Monstera care — monstera.md (as of 2026-05-01)"]
    a = _mk(
        id="r1",
        question="q",
        pair_id="p",
        is_reference=True,
        language="en",
        target_response=TargetResponse(text="x", citations=cite, language="en"),
    )
    b = _mk(
        id="r2",
        question="q",
        pair_id="p",
        is_reference=True,
        language="en",
        target_response=TargetResponse(text="x", citations=cite, language="en"),
    )
    assert _ml_run([a, b]) is Verdict.FAIL  # two anchors, zero translations
