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
        "non",
    }
)

_TOKEN_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?|[^\W\d_]+", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_NEG_NT_RE = re.compile(r"\b\w+n't\b", re.IGNORECASE)

# Splits a query into clauses on coordinating conjunctions and clause punctuation, in
# both languages. Deliberately conservative (a fixed conjunction list, not an NLP parser)
# so clause boundaries stay auditable: "How often should I water, and does that change in
# winter?" splits into two clauses; "How often should I water my pothos?" stays one.
# py/polynomial-redos: the pattern used to open with a shared ``\s*``, so on a run of n
# whitespace characters the engine consumed the rest of the run at *every* one of the n start
# positions before failing — O(n²) in a value the caller supplies (`POST /api/chat`, capped at
# `server.max_question_chars`). Dropping the surrounding ``\s*`` makes both branches start on a
# character class that whitespace cannot satisfy, so a non-delimiter position fails in O(1).
#
# Equivalent for this module's only consumer: the pieces now keep their surrounding whitespace,
# and ``extract_facets`` feeds every piece through ``.strip()`` and ``token_set`` (which
# tokenises with ``_TOKEN_RE``), so leading/trailing whitespace on a clause is not observable.
# ``\s++`` is possessive because no conjunction begins with whitespace, so a whitespace run
# never had a match to give back.
_FACET_SPLIT_RE = re.compile(
    r"(?:[,;?]+|(?<=\w)\s++(?:and|but|or|as well as|y|pero|o)\s++(?=\w))",
    re.IGNORECASE,
)


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


def extract_facets(query: str) -> list[frozenset[str]]:
    """Split a query into per-clause content-token sets ("facets").

    A single-part question ("How often should I water my pothos?") yields one facet —
    its whole content-token set — so single-part behaviour is unchanged downstream. A
    multi-part question ("How often should I water, and does that change in winter?")
    yields one facet per clause, so a caller can require each clause's topic to surface
    in the answer instead of ranking every candidate against one pooled bag of tokens
    (which lets the dominant clause crowd out the others). Empty/stop-word-only clauses
    are dropped; a query with no content tokens at all yields an empty list.
    """
    clauses = [c for c in _FACET_SPLIT_RE.split(query.strip()) if c.strip()]
    facets = [toks for c in clauses if (toks := token_set(c))]
    return facets


def has_negation(text: str) -> bool:
    """True if ``text`` contains an explicit negation marker (either language)."""
    if _NEG_NT_RE.search(text):
        return True
    return any(tok in _NEGATIONS for tok in tokenize(text))


# Safety-relevant antonym pairs (bilingual, gender/number-inflected). Deliberately a
# small, curated, domain-specific list — this project's whole safety surface is the
# toxic/non-toxic axis — rather than a general antonym dictionary, so it stays auditable
# and cannot introduce false contradictions on unrelated vocabulary. ``has_negation``
# catches "is not toxic"; this catches the polarity flip that carries no negation marker
# at all, e.g. "is safe" asserted against a source that says "is toxic".
_ANTONYM_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"safe", "toxic"}),
        frozenset({"safe", "poisonous"}),
        frozenset({"nontoxic", "toxic"}),
        frozenset({"harmless", "toxic"}),
        frozenset({"harmless", "poisonous"}),
        frozenset({"harmless", "dangerous"}),
        frozenset({"edible", "toxic"}),
        frozenset({"edible", "poisonous"}),
        frozenset({"seguro", "toxico"}),
        frozenset({"segura", "toxica"}),
        frozenset({"seguros", "toxicos"}),
        frozenset({"seguras", "toxicas"}),
        frozenset({"seguro", "venenoso"}),
        frozenset({"segura", "venenosa"}),
        frozenset({"inofensivo", "toxico"}),
        frozenset({"inofensiva", "toxica"}),
        frozenset({"comestible", "venenoso"}),
        frozenset({"comestible", "venenosa"}),
        frozenset({"comestible", "toxico"}),
        frozenset({"comestible", "toxica"}),
    }
)


def has_antonym_conflict(a: str, b: str) -> bool:
    """True if ``a`` and ``b`` assert opposite sides of a known safety antonym pair.

    "Aloe is safe for dogs" flatly contradicts a source that says "Aloe is toxic to
    dogs" even though neither sentence contains an explicit negation marker, so
    ``has_negation`` alone cannot catch it. Only flags a conflict when each text
    contains exactly one, differing side of a pair — a text that mentions both sides
    (rare, e.g. quoting a contrast) is left to the coverage/negation checks instead of
    being guessed at here.
    """
    toks_a = set(tokenize(a))
    toks_b = set(tokenize(b))
    for pair in _ANTONYM_PAIRS:
        side_a = toks_a & pair
        side_b = toks_b & pair
        if side_a and side_b and not (side_a & side_b):
            return True
    return False


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


# --- numeric-cadence extraction (source-disagreement probe, EXP-02) --------------
#
# Bilingual "every N day(s)/week(s)" / "cada N día(s)/semana(s)" cadence mentions,
# anchored to a small, explicit care-action vocabulary so a cadence is only ever
# compared against another cadence about the *same* action. This is deliberately
# narrower than a general contradiction probe: the ideation note for this feature
# (EXP-02, docs/ideation/03-expansions.md) calls out that naive polarity/number
# checks over-fire on legitimate seasonal or per-action variation, so extraction
# starts and stays scoped to numeric-cadence conflicts only.
_CADENCE_RE = re.compile(
    r"(?:every|cada)\s+(\d+(?:\.\d+)?)\s*-?\s*"
    r"(days?|weeks?|d[ií]as?|semanas?)\b",
    re.IGNORECASE,
)

_CADENCE_UNIT_DAYS: dict[str, float] = {
    "day": 1.0,
    "days": 1.0,
    "dia": 1.0,
    "dias": 1.0,
    "week": 7.0,
    "weeks": 7.0,
    "semana": 7.0,
    "semanas": 7.0,
}

# Small, explicit bilingual care-action vocabulary. Each key is the normalised action
# name a cadence mention is reported under, so an English chunk and a Spanish chunk
# that disagree about the same action still compare equal.
_CARE_ACTIONS: dict[str, frozenset[str]] = {
    "water": frozenset({"water", "watering", "watered", "riega", "riego", "regar", "regando"}),
    "fertilize": frozenset(
        {
            "fertilize",
            "fertilizing",
            "fertilized",
            "feed",
            "feeding",
            "fertiliza",
            "fertilizar",
            "fertilizando",
            "abona",
            "abonar",
        }
    ),
    "mist": frozenset({"mist", "misting", "misted", "rocia", "rociar", "rociando"}),
    "repot": frozenset({"repot", "repotting", "repotted", "trasplanta", "trasplantar"}),
}

# How far (in characters) around a cadence mention to look for an anchoring action
# word. Bounded and symmetric so "Water ... every 7 days" and "Every 7 days, water
# ..." both anchor, while a cadence with no nearby action word (e.g. "check the soil
# every 3 days") is conservatively left unanchored and skipped.
_ACTION_WINDOW_CHARS = 40


def extract_cadences(text: str) -> list[tuple[str, float, str]]:
    """Bilingual 'every N day(s)/week(s)' mentions anchored to a known care action.

    Returns one ``(action, days, mention)`` tuple per anchored match, e.g.
    ``[("water", 7.0, "every 7 days")]``. Weeks normalise to days so "every 2 weeks"
    and "every 14 days" compare equal instead of registering as a false conflict. A
    cadence with no recognised action word in its surrounding window is dropped —
    unanchored numbers are exactly the over-firing risk this stays conservative about.
    """
    out: list[tuple[str, float, str]] = []
    for m in _CADENCE_RE.finditer(text):
        value = float(m.group(1))
        unit = strip_accents(m.group(2).lower())
        days = value * _CADENCE_UNIT_DAYS.get(unit, 1.0)
        window_start = max(0, m.start() - _ACTION_WINDOW_CHARS)
        window_end = min(len(text), m.end() + _ACTION_WINDOW_CHARS)
        window_tokens = set(tokenize(text[window_start:window_end]))
        for action, markers in _CARE_ACTIONS.items():
            if window_tokens & markers:
                out.append((action, days, m.group(0)))
                break
    return out
