"""Issue #168: the multilingual suite fails an answer that mixes languages.

Before this check, the suite compared a Spanish answer with its English anchor on the
refuse/answer decision, the language-invariant cited-plant set, and the answer-level
language tag — so an English sentence quoted into a Spanish answer passed all three.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sprout.eval.dataset import Dataset, DatasetItem, Provenance, TargetResponse
from sprout.eval.judge import DeterministicJudge
from sprout.eval.runner import run_evaluation
from sprout.eval.suite import SuiteResult, Verdict, resolve_suites
from sprout.eval.suites._sentence_language import (
    EN_FUNCTION_WORDS,
    ES_FUNCTION_WORDS,
    off_language_sentences,
    sentence_language,
)
from sprout.text import split_sentences

_ROOT = Path(__file__).resolve().parent.parent
PROV = Provenance(source="synthetic", license="CC0-1.0", added="2026-10-17")

EN_SENTENCE = (
    "The Monstera (Monstera deliciosa) grows best in bright, indirect light for roughly "
    "6 to 8 hours a day."
)
ES_SENTENCE = (
    "La Monstera (Monstera deliciosa) crece mejor con luz brillante e indirecta durante "
    "unas 6 a 8 horas al día."
)
ES_SECOND = "Riega la Monstera cuando los 2 a 3 centímetros superiores del sustrato se sequen."


# --- the detector ------------------------------------------------------------------
def test_clear_english_and_spanish_sentences_are_attributed() -> None:
    assert sentence_language(EN_SENTENCE) == "en"
    assert sentence_language(ES_SENTENCE) == "es"


@pytest.mark.parametrize(
    "fragment",
    ["Monstera deliciosa.", "Epipremnum aureum", "", "6 a 8", "Aloe vera (Aloe barbadensis)."],
)
def test_name_only_or_short_fragments_are_undetermined_not_failed(fragment: str) -> None:
    assert sentence_language(fragment) is None


def test_one_accent_does_not_flip_an_english_sentence() -> None:
    # An English sentence quoting a Spanish name keeps its language.
    assert sentence_language("The label calls it Potho, and the reference lists it as toxic.") == (
        "en"
    )


def test_the_two_function_word_lists_share_no_word() -> None:
    assert not (EN_FUNCTION_WORDS & ES_FUNCTION_WORDS)


def test_ambiguous_words_are_on_neither_list() -> None:
    # Words that are function words or common forms in both languages must not vote.
    for word in ("a", "no", "me", "se", "use", "come", "has", "once"):
        assert word not in EN_FUNCTION_WORDS
        assert word not in ES_FUNCTION_WORDS


def test_off_language_sentences_names_the_offending_sentence() -> None:
    mixed = f"{ES_SENTENCE} {EN_SENTENCE}"
    assert off_language_sentences(mixed, "es") == [(EN_SENTENCE, "en")]
    assert off_language_sentences(f"{ES_SENTENCE} {ES_SECOND}", "es") == []


@pytest.mark.parametrize("expected", [None, "fr", ""])
def test_an_expected_language_the_detector_cannot_judge_checks_nothing(
    expected: str | None,
) -> None:
    assert off_language_sentences(EN_SENTENCE, expected) == []


def test_no_bundled_corpus_sentence_is_attributed_to_the_other_language() -> None:
    """The check must not have false positives on the text the assistant actually quotes.

    Every sentence the extractive generator can render comes from this corpus, so a
    sentence of `x.es.md` read as English (or the reverse) would be a false failure.
    Undetermined is allowed — that is the documented false-negative side of the check.
    """
    files = sorted((_ROOT / "corpus" / "processed").glob("*.md"))
    assert files, "bundled corpus not found"
    checked = 0
    for path in files:
        expected = "es" if path.name.endswith(".es.md") else "en"
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith(("#", "---")):
                continue
            for sentence in split_sentences(line):
                checked += 1
                assert off_language_sentences(sentence, expected) == [], (path.name, sentence)
    assert checked > 500


# --- the suite ---------------------------------------------------------------------
def _item(item_id: str, *, text: str, language: str, reference: bool = False) -> DatasetItem:
    source = "monstera.md" if language == "en" else "monstera.es.md"
    return DatasetItem(
        id=item_id,
        question="q",
        provenance=PROV,
        pair_id="p",
        is_reference=reference,
        language=language,
        target_response=TargetResponse(
            text=text,
            citations=[f"Monstera — {source} (as of 2026-05-01)"],
            language=language,
        ),
    )


def _run(items: list[DatasetItem]) -> SuiteResult:
    result = run_evaluation(
        Dataset.from_items(items),
        DeterministicJudge(),
        resolve_suites("multilingual"),
        target="t",
    )
    return result.suite_results[0]


def test_a_spanish_answer_with_an_english_sentence_fails() -> None:
    """The #168 shape: same plant, same decision, Spanish tag — and one English sentence."""
    anchor = _item("p-en", text=EN_SENTENCE, language="en", reference=True)
    mixed = _item("p-es", text=f"{ES_SENTENCE} {EN_SENTENCE}", language="es")
    result = _run([anchor, mixed])
    assert result.verdict is Verdict.FAIL
    (failure,) = result.failing_examples
    assert failure.item_id == "p-es"
    assert "plants_ok=True" in failure.detail
    assert "lang_ok=True" in failure.detail
    assert "sentence_lang_ok=False" in failure.detail
    assert "detected as 'en'" in failure.detail


def test_a_wholly_spanish_answer_passes() -> None:
    anchor = _item("p-en", text=EN_SENTENCE, language="en", reference=True)
    clean = _item("p-es", text=f"{ES_SENTENCE} {ES_SECOND}", language="es")
    result = _run([anchor, clean])
    assert result.verdict is Verdict.PASS
    assert result.failing_examples == ()


def test_a_mixed_reference_anchor_fails_its_translation_too() -> None:
    anchor = _item("p-en", text=f"{EN_SENTENCE} {ES_SECOND}", language="en", reference=True)
    clean = _item("p-es", text=ES_SENTENCE, language="es")
    result = _run([anchor, clean])
    assert result.verdict is Verdict.FAIL
    (failure,) = result.failing_examples
    assert "p-en renders a sentence detected as 'es'" in failure.detail
