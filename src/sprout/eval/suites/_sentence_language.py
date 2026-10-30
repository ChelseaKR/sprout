"""Per-sentence language check for the multilingual suite (issue #168).

The multilingual suite used to compare a Spanish answer with its English anchor on the
refuse/answer decision and the *language-invariant* cited-plant set ('monstera.md' and
'monstera.es.md' both read as 'monstera'), plus the answer-level language tag. None of
those looks at the language of an individual rendered sentence, so an English sentence
quoted into a Spanish answer passed every check. This module supplies that missing
check.

It is deliberately small, offline, and deterministic: two closed lists of high-frequency
function words, plus Spanish-only orthography as extra evidence. It is also deliberately
*independent* of the runtime detector (``sprout.lang``, whose marker lists live in the
locale bundles): a check that shared the assistant's own vocabulary could not catch a
fault in it.

Known limits, stated so the check is not read as more than it is:

* It is a two-language (EN/ES) heuristic, not a language identifier. A sentence in any
  other language is "undetermined", never a failure.
* It only *flags* a sentence when the evidence is clear: at least
  :data:`MIN_EVIDENCE` function-word hits for one language and at least twice as many as
  for the other. Short or name-heavy fragments ("Monstera deliciosa.") are undetermined
  and pass. The check therefore has false negatives by design and should not produce
  false positives; ``tests/test_sentence_language.py`` pins the latter against every
  sentence in the bundled corpus.
* Function words shared by both languages (``a``, ``no``, ``me``, ``se``) and English
  words that are also common Spanish forms (``use``, ``come``, ``has``, ``once``) are
  excluded on purpose, so neither list can vote for the other language.
"""

from __future__ import annotations

import re

from ...text import split_sentences

#: Minimum function-word hits before a sentence is attributed to a language at all.
MIN_EVIDENCE = 2

#: English function words that are not also Spanish words.
EN_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "the", "and", "of", "to", "is", "are", "was", "be", "been", "it", "its", "this",
        "that", "these", "those", "with", "for", "from", "or", "on", "at", "by", "as",
        "if", "when", "your", "you", "they", "their", "them", "can", "should", "will",
        "does", "do", "not", "than", "into", "about", "each", "every", "which", "what",
        "why", "how", "where", "while", "after", "before", "during", "between", "any",
        "all", "more", "most", "less", "but", "so", "then", "there", "an", "in", "keep",
    }
)  # fmt: skip

#: Spanish function words that are not also English words.
ES_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "y",
        "en", "que", "por", "para", "con", "sin", "es", "son", "está", "están", "esta",
        "este", "estos", "estas", "su", "sus", "lo", "le", "les", "pero", "cuando",
        "como", "cómo", "más", "muy", "cada", "entre", "hasta", "puede", "pueden",
        "debe", "deben", "sobre", "porque", "qué", "tu", "tus", "también", "si",
    }
)  # fmt: skip

_SPANISH_ORTHOGRAPHY = frozenset("ñ¿¡áéíóú")
_WORD_RE = re.compile(r"[a-záéíóúüñ]+")


def sentence_language(sentence: str) -> str | None:
    """Return ``"en"``/``"es"`` when the evidence is clear, else ``None`` (undetermined)."""
    lowered = sentence.lower()
    words = _WORD_RE.findall(lowered)
    en = sum(1 for w in words if w in EN_FUNCTION_WORDS)
    es = sum(1 for w in words if w in ES_FUNCTION_WORDS)
    # Spanish-only orthography is one extra vote, not a verdict: an English sentence that
    # quotes a Spanish name ("the Potho (Epipremnum aureum)") must not flip on one accent.
    if any(ch in _SPANISH_ORTHOGRAPHY for ch in lowered):
        es += 1
    if en >= MIN_EVIDENCE and en >= 2 * es:
        return "en"
    if es >= MIN_EVIDENCE and es >= 2 * en:
        return "es"
    return None


def off_language_sentences(text: str, expected: str | None) -> list[tuple[str, str]]:
    """Sentences of ``text`` confidently detected in a language other than ``expected``.

    Returns ``(sentence, detected_language)`` pairs; an empty list means no rendered
    sentence contradicts ``expected``. ``expected`` of ``None`` or outside EN/ES checks
    nothing (the detector cannot speak to it) rather than failing.
    """
    if expected not in ("en", "es"):
        return []
    out: list[tuple[str, str]] = []
    for sentence in split_sentences(text):
        detected = sentence_language(sentence)
        if detected is not None and detected != expected:
            out.append((sentence, detected))
    return out
