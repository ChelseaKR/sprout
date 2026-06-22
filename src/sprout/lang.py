"""Dependency-free language detection over the supported set (English, Spanish).

The assistant must answer in the language the user wrote in, and the multilingual
eval suite checks that an answer's language matches its expected tag. We do not pull
in a heavy model for a two-language decision: a small, deterministic marker-word and
diacritic scorer is enough and, crucially, gives the *same* answer every run with no
network. ``langdetect`` is consulted only as an optional tie-breaker when installed.
"""

from __future__ import annotations

from .text import tokenize

SUPPORTED: tuple[str, ...] = ("en", "es")
DEFAULT_LANGUAGE = "en"

# Function words that are strong, mutually-exclusive signals for each language.
_MARKERS: dict[str, frozenset[str]] = {
    "es": frozenset(
        {
            "el",
            "la",
            "los",
            "las",
            "una",
            "unos",
            "unas",
            "que",
            "de",
            "del",
            "como",
            "cómo",
            "por",
            "para",
            "con",
            "es",
            "son",
            "está",
            "están",
            "mi",
            "su",
            "pero",
            "porque",
            "cuando",
            "donde",
            "muy",
            "más",
            "hoja",
            "hojas",
            "planta",
            "agua",
            "luz",
            "tóxica",
            "tóxico",
            "gato",
            "perro",
            "regar",
            "riego",
            "amarilla",
            "amarillas",
        }
    ),
    "en": frozenset(
        {
            "the",
            "and",
            "is",
            "are",
            "of",
            "to",
            "in",
            "my",
            "why",
            "how",
            "what",
            "for",
            "with",
            "leaf",
            "leaves",
            "plant",
            "water",
            "light",
            "toxic",
            "cat",
            "dog",
            "yellow",
            "yellowing",
            "watering",
            "should",
            "does",
        }
    ),
}

# Characters that only appear in Spanish text in this domain.
_SPANISH_CHARS = frozenset("ñ¿¡áéíóúü")


def detect_language(text: str, *, default: str = DEFAULT_LANGUAGE) -> str:
    """Return the best-guess BCP-47 tag in :data:`SUPPORTED`, or ``default``.

    Scoring is purely lexical and deterministic: marker-word hits plus a bonus for
    Spanish-only characters. Ties and empty/uncertain input fall back to ``default``
    (English), matching the config's reference-language convention.
    """
    lowered = text.lower()
    if any(ch in _SPANISH_CHARS for ch in lowered):
        # Spanish-only orthography is decisive on its own.
        return "es"

    toks = set(tokenize(text))
    if not toks:
        return default

    scores = {lang: sum(1 for t in toks if t in markers) for lang, markers in _MARKERS.items()}
    best = max(SUPPORTED, key=lambda lang: scores[lang])
    if scores[best] == 0 or scores["en"] == scores["es"]:
        return _langdetect_fallback(text, default)
    return best


def _langdetect_fallback(text: str, default: str) -> str:
    """Optional tie-breaker via ``langdetect`` if it is installed; else ``default``."""
    try:
        from langdetect import detect
    except ImportError:
        return default
    try:
        guess = str(detect(text))
    except Exception:
        return default
    return guess if guess in SUPPORTED else default
