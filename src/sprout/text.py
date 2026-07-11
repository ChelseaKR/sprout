"""Dependency-free bilingual (English/Spanish) text helpers.

Retrieval (BM25 + dense), the extractive generator, and the deterministic eval
judge all reduce text to tokens the *same* way through this module, so "what is a
token" can never drift between the component that finds a passage, the component
that quotes it, and the component that judges the quote. Everything here is pure
and deterministic: no randomness, no network, no locale dependence.
"""

from __future__ import annotations

import re
import unicodedata

# Bilingual stop-word set. Kept deliberately small and explicit (not a downloaded
# corpus) so the behaviour is auditable and stable across releases.
_STOPWORDS: frozenset[str] = frozenset(
    {
        # English
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "do",
        "does",
        "did",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
        "about",
        "can",
        "could",
        "should",
        "would",
        "am",
        "we",
        "us",
        "he",
        "she",
        "his",
        "her",
        "any",
        "all",
        "more",
        "most",
        "some",
        "such",
        "only",
        "own",
        "too",
        "very",
        "just",
        "also",
        "get",
        "got",
        # Spanish
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "y",
        "o",
        "de",
        "del",
        "que",
        "en",
        "es",
        "son",
        "ser",
        "está",
        "estan",
        "están",
        "al",
        "se",
        "su",
        "sus",
        "como",
        "cómo",
        "por",
        "para",
        "con",
        "mi",
        "mis",
        "tu",
        "tus",
        "le",
        "lo",
        "te",
        "nos",
        "muy",
        "más",
        "mas",
        "pero",
        "si",
        "sí",
        "ya",
        "este",
        "esta",
        "estos",
        "estas",
        "cuando",
        "cuándo",
        "donde",
        "dónde",
        "qué",
        "cual",
        "cuál",
        "porque",
        "porqué",
        "puede",
        "pueden",
        "hay",
        "ha",
        "han",
        "soy",
    }
)

# Negation markers in both languages. Negations are stop-words for retrieval but
# polarity-bearing for grounding, so callers use ``has_negation`` separately rather
# than relying on token overlap (which would treat "is toxic" ~ "is not toxic").
_NEGATIONS: frozenset[str] = frozenset(
    {
        "no",
        "not",
        "never",
        "cannot",
        "cant",
        "without",
        "none",
        "neither",
        "nor",
        "nunca",
        "ni",
        "sin",
        "tampoco",
        "jamas",
        "jamás",
        "nada",
        "ningun",
        "ningún",
        "ninguna",
        "noun",
    }
)

_TOKEN_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?|[^\W\d_]+", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_NEG_NT_RE = re.compile(r"\b\w+n't\b", re.IGNORECASE)


def strip_accents(token: str) -> str:
    """Fold accents so 'también' and 'tambien' tokenise identically."""
    decomposed = unicodedata.normalize("NFKD", token)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# Backwards-compatible private alias (used internally before this was public).
_strip_accents = strip_accents


def _strip_zero_width(text: str) -> str:
    """NFKC-normalize and drop Unicode format characters (category ``Cf``).

    Category Cf covers the zero-width space/non-joiner/joiner (U+200B, U+200C, U+200D) and
    the BOM/zero-width-no-break-space (U+FEFF) — invisible characters an adversarial input
    can splice into a word (e.g. "safe" with a U+200B inserted between the "s" and the "a")
    to dodge exact-phrase and token matching without changing how the text *looks* or reads
    aloud. Characters are removed outright (not replaced with a space) so the surrounding
    letters re-join into the original word instead of being split into spurious sub-tokens.
    Applied before tokenisation so every consumer of ``tokenize``/``normalize`` — retrieval,
    the citation guard, and the never-certify-safe deny-list — sees the same de-obfuscated
    text.
    """
    return "".join(
        ch for ch in unicodedata.normalize("NFKC", text) if unicodedata.category(ch) != "Cf"
    )


def tokenize(text: str) -> list[str]:
    """Lower-cased, accent-folded word/number tokens, in document order."""
    return [_strip_accents(m.group(0).lower()) for m in _TOKEN_RE.finditer(_strip_zero_width(text))]


def _stem(token: str) -> str:
    """A tiny, conservative bilingual suffix stripper.

    Not a linguistic stemmer — just enough to fold the most common plural/verb
    inflections ("leaves"->"leav", "watering"->"water", "plantas"->"plant") so a
    query and the passage that answers it land on the same token. Numbers pass
    through untouched so figures stay exact for grounding.
    """
    if token.isdigit() or any(ch.isdigit() for ch in token):
        return token
    for suffix in ("ndoles", "andolo", "iendo", "ando", "ciones", "cion", "mente"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    for suffix in ("ing", "ies", "ied"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)] + ("y" if suffix in ("ies", "ied") else "")
    for suffix in ("es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    if token.endswith("ed") and len(token) - 2 >= 3:
        return token[:-2]
    return token


def content_tokens(text: str) -> list[str]:
    """Stemmed, stop-word-free content tokens — the unit of retrieval and grounding."""
    out: list[str] = []
    for tok in tokenize(text):
        if tok in _STOPWORDS or tok in _NEGATIONS:
            continue
        out.append(_stem(tok))
    return out


def token_set(text: str) -> frozenset[str]:
    """Unique content tokens of ``text``."""
    return frozenset(content_tokens(text))


def has_negation(text: str) -> bool:
    """True if ``text`` contains an explicit negation marker (either language)."""
    if _NEG_NT_RE.search(text):
        return True
    return any(tok in _NEGATIONS for tok in tokenize(text))


def split_sentences(text: str) -> list[str]:
    """Split into trimmed sentences on terminal punctuation, preserving decimals.

    "Let the top 1.5 inches dry. Then water." -> ["Let the top 1.5 inches dry.",
    "Then water."]. Decimal points do not split because the regex requires
    whitespace after the punctuation.
    """
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def coverage(needle: str, haystack: str) -> float:
    """Fraction of ``needle``'s content tokens that appear in ``haystack``.

    A recall-style, asymmetric measure: 1.0 means every content word of the
    claim is present in the source. Returns 1.0 for an empty needle (vacuously
    covered) so a punctuation-only sentence never fails grounding spuriously.
    """
    needle_tokens = token_set(needle)
    if not needle_tokens:
        return 1.0
    hay = token_set(haystack)
    present = sum(1 for tok in needle_tokens if tok in hay)
    return present / len(needle_tokens)


def jaccard(a: str, b: str) -> float:
    """Jaccard similarity of the two texts' content-token sets."""
    sa, sb = token_set(a), token_set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def normalize(text: str) -> str:
    """NFKC-normalize, drop zero-width/format characters, collapse whitespace, lower-case.

    Used for verbatim-containment checks (``contains_phrase``) and folded into
    ``guards._fold`` for the never-certify-safe deny-list, so both must survive
    zero-width-character injection between the letters of a denied phrase.
    """
    return re.sub(r"\s+", " ", _strip_zero_width(text)).strip().lower()


def contains_phrase(haystack: str, phrase: str) -> bool:
    """Case-insensitive, whitespace-insensitive substring test."""
    return normalize(phrase) in normalize(haystack)
