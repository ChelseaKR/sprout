"""Input/output guards — where "grounded" and "never certify safe" become structural.

The citation guard is the load-bearing gate: it re-verifies every candidate sentence
against the chunk it claims to come from and drops anything it cannot support, so an
ungrounded sentence is *structurally impossible* to render, not merely discouraged. The
safety-assertion guard drops any sentence that certifies a plant "safe"/"non-toxic" in
either language. Scope is enforced upstream by the retrieval threshold; PII redaction and
injection detection guard the (optional) network path and the logs.

On the cloud (non-deterministic) generation path, ``citation_guard`` can additionally take
an ``entailment_verifier`` (EXP-04, ``verifiers.py``) — a cross-encoder NLI model that must
also agree the cited chunk entails the sentence. It is a strictly *additional* gate applied
after the lexical check below, never a replacement for it. The offline extractive path
never passes one, so its by-construction groundedness guarantee is unchanged (ADR-0013).
"""

from __future__ import annotations

import re

from . import locales
from .config import GuardsConfig
from .models import AnswerSentence, Citation, RetrievedChunk
from .text import (
    contains_phrase,
    coverage,
    has_antonym_conflict,
    has_negation,
    normalize,
    strip_accents,
    token_set,
    tokenize,
)
from .verifiers import EntailmentVerifier

# --- input classification --------------------------------------------------------


def is_safety_query(query: str, language: str, cfg: GuardsConfig) -> bool:
    """True if the question is about toxicity/ingestion safety (either language)."""
    q_tokens = set(tokenize(query))
    for lang in {language, "en"}:
        for kw in cfg.toxicity_keywords.get(lang, []):
            if " " in kw:
                if contains_phrase(query, kw):
                    return True
            elif kw in q_tokens or any(kw in t for t in q_tokens):
                return True
    return False


def _matches_any(
    query: str, q_tokens: set[str], language: str, keywords: dict[str, list[str]]
) -> bool:
    """Exact-token (or exact-phrase) match against an audience keyword list.

    Deliberately stricter than ``is_safety_query``'s substring pass: substring matching
    is a safe over-trigger for *whether* something is a safety query, but for *audience
    routing* it misclassifies -- "cat" is inside "identification", "pet" inside "petal",
    "kid" inside "kidney", and "son" (a keyword we need) inside "poison". Exposure
    keyword lists therefore carry their inflected forms explicitly and match whole
    tokens only; ``tokenize`` has already lower-cased and accent-folded the query, and
    single-word keywords are folded here so accented list entries compare equal.
    """
    for lang in {language, "en"}:
        for kw in keywords.get(lang, []):
            if " " in kw:
                if contains_phrase(query, kw):
                    return True
            elif strip_accents(kw.lower()) in q_tokens:
                return True
    return False


def detect_exposure_type(query: str, language: str, cfg: GuardsConfig) -> str:
    """Classify a safety query's exposure audience (research item FIX-13).

    Splits the audience terms into a child/human subset
    (``GuardsConfig.child_exposure_keywords``) and an animal subset
    (``GuardsConfig.animal_exposure_keywords``) so the escalation card can be routed to
    the audience the query actually names, instead of always defaulting to the animal
    lines. Matching is exact-token/exact-phrase (see ``_matches_any``), not the
    substring pass ``is_safety_query`` uses, so audience routing never keys off word
    fragments. Deterministic and eval-gated -- it never infers an audience the query
    did not name.

    Returns one of:
      - ``"child"``: only child/human terms matched ("my toddler chewed a leaf").
      - ``"animal"``: only animal terms matched ("is this toxic to my cat?").
      - ``"both"``: both matched (ambiguous household query, e.g. "toxic to kids or
        pets?").
      - ``"unspecified"``: a safety/toxicity term matched but no audience was named
        ("is this plant poisonous?").
    """
    q_tokens = set(tokenize(query))
    is_child = _matches_any(query, q_tokens, language, cfg.child_exposure_keywords)
    is_animal = _matches_any(query, q_tokens, language, cfg.animal_exposure_keywords)
    if is_child and is_animal:
        return "both"
    if is_child:
        return "child"
    if is_animal:
        return "animal"
    return "unspecified"


_INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "instruction_override": re.compile(
        r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|above|prior|instructions?|rules?)\b",
        re.IGNORECASE,
    ),
    "role_play": re.compile(r"\b(you are now|pretend to be|act as|roleplay)\b", re.IGNORECASE),
    "system_prompt_probe": re.compile(
        r"\b(system prompt|your instructions|reveal|print).{0,20}\b(prompt|rules|instructions)\b",
        re.IGNORECASE,
    ),
    "safety_override": re.compile(
        r"\b(just (tell|say)|simply confirm).{0,20}\b(safe|fine|ok)\b", re.IGNORECASE
    ),
}


def detect_injection(text: str) -> list[str]:
    """Return matched prompt-injection category names (observability, not defense).

    Defense against injection is structural — the citation guard drops any sentence not
    entailed by a retrieved chunk — so this only labels attempts for logging and the
    refusal/adversarial eval suite.
    """
    return sorted(name for name, pat in _INJECTION_PATTERNS.items() if pat.search(text))


_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Bounded quantifiers avoid catastrophic backtracking (ReDoS) on adversarial input.
    (re.compile(r"[\w.+-]{1,64}@[\w-]{1,255}\.[\w.-]{1,255}"), "[email]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"\b(?:\+?\d[\s.-]?){9,13}\d\b"), "[phone]"),
]


def redact_pii(text: str) -> str:
    """Best-effort redaction of text sent to a network provider (never the index/logs untouched)."""
    out = text
    for pattern, replacement in _PII_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


# --- output guards ---------------------------------------------------------------


# Minimal Latin-lookalike table: only the characters a fuzz test
# (tests/test_guard_fuzzing.py) demonstrated as a deny-list bypass (Cyrillic lookalikes
# substituted for Latin a/e/o, e.g. "safe" with the "a" swapped for U+0430). Deliberately
# small and auditable rather than a full confusables table; keys are written as \u escapes
# (not literal glyphs) so the confusable pair stays visually explicit in the source — see
# docs/adr/0014-deny-list-homoglyph-folding.md.
_HOMOGLYPHS: dict[str, str] = {
    "\u0430": "a",  # CYRILLIC SMALL LETTER A
    "\u0435": "e",  # CYRILLIC SMALL LETTER IE
    "\u043e": "o",  # CYRILLIC SMALL LETTER O
}


def _fold_homoglyphs(text: str) -> str:
    """Map the minimal Cyrillic lookalike table above onto their Latin counterparts."""
    return "".join(_HOMOGLYPHS.get(ch, ch) for ch in text)


def _fold(text: str) -> str:
    """Normalise for safety matching: lower-case, collapse space, fold accents/hyphens/homoglyphs.

    Accent- and hyphen-folding keep the deny-list robust to "non-toxic" vs "non toxic" and
    Spanish accent variants, consistent with how the rest of the pipeline tokenises.
    Homoglyph-folding closes the Cyrillic-lookalike bypass found by property-based fuzzing
    (FIX-05); it is intentionally narrow, see ``_HOMOGLYPHS`` above.
    """
    return _fold_homoglyphs(strip_accents(normalize(text))).replace("-", " ")


def asserts_safety(text: str, language: str, cfg: GuardsConfig) -> bool:
    """True if ``text`` contains a forbidden safety-certification phrase (any phrasing).

    Combines a folded deny-list with a negation-aware semantic check: a sentence that
    *negates* a toxicity/harm term ("is not toxic", "no risk", "will not harm") is also a
    de-facto safety certification, even when it dodges the literal deny-list.
    """
    haystack = _fold(text)
    for lang in {language, "en"}:
        for phrase in cfg.forbidden_safe_phrases.get(lang, []):
            if _fold(phrase) in haystack:
                return True
    # A bare negated-harm claim ("X is not toxic", "poses no risk") reads as a safety
    # certification. But a *source-attributed* statement ("the cited reference does not
    # list X as toxic") is reporting the source's silence, which CLAUDE.md explicitly
    # permits — so only flag negated-harm when there is no source attribution.
    if has_negation(text):
        toks = {strip_accents(t) for t in tokenize(text)}
        if toks & _HARM_TOKENS and not (toks & _SOURCE_MARKERS):
            return True
    return False


# Toxicity/harm terms whose negation amounts to a safety certification (EN + ES,
# folded). Authored per-language in src/sprout/locales/<lang>/bundle.yaml (FIX-09) and
# unioned here — the folding across languages stays, only the authoring surface moved.
_HARM_TOKENS = frozenset(
    locales.merged_list("guards", "harm_tokens", locales.available_languages())
)
# Source-attribution markers: their presence means the sentence reports what the cited
# source says (or does not say), not a bare certification. Same per-language authoring.
_SOURCE_MARKERS = frozenset(
    locales.merged_list("guards", "source_markers", locales.available_languages())
)


def _supported_by(sentence: str, chunk_text: str, support_overlap: float) -> bool:
    """A sentence is supported iff it is verbatim-contained, or sufficiently covered AND
    its negation polarity matches the source.

    The polarity gate is load-bearing for the cloud generators: token coverage strips
    negations, so "X is not toxic" would otherwise score as covered by "X is toxic".
    ``has_antonym_conflict`` catches the same failure mode when no negation marker is
    present at all ("X is safe" against a source that says "X is toxic"). A
    content-free fragment is never supported (it must carry at least one content token).
    """
    if contains_phrase(chunk_text, sentence):
        return True
    if not token_set(sentence):
        return False
    if has_negation(sentence) != has_negation(chunk_text):
        return False
    if has_antonym_conflict(sentence, chunk_text):
        return False
    return coverage(sentence, chunk_text) >= support_overlap


def citation_guard(
    candidates: list[tuple[str, str]],
    retrieved: list[RetrievedChunk],
    support_overlap: float,
    entailment_verifier: EntailmentVerifier | None = None,
) -> list[AnswerSentence]:
    """Re-verify each candidate sentence against its cited chunk; drop the unsupported.

    This is why ungrounded generation is structurally impossible. A candidate survives
    only if (a) its ``chunk_id`` was actually retrieved, (b) the chunk's text supports the
    sentence lexically, and (c) — when ``entailment_verifier`` is configured (cloud path
    only, EXP-04) — the verifier also agrees the chunk entails the sentence. Survivors
    become :class:`AnswerSentence` objects tagged ``corpus``.
    """
    by_id = {rc.chunk.chunk_id: rc.chunk for rc in retrieved}
    out: list[AnswerSentence] = []
    seen: set[str] = set()
    for text, chunk_id in candidates:
        chunk = by_id.get(chunk_id)
        if chunk is None:
            continue
        if not _supported_by(text, chunk.text, support_overlap):
            continue
        entailed = entailment_verifier is None or entailment_verifier.entails(chunk.text, text)
        if not entailed:
            continue
        key = normalize(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            AnswerSentence(
                text=text,
                chunk_id=chunk_id,
                citation=Citation(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    source=chunk.source,
                    quote=chunk.text,
                    license=chunk.license,
                    fetch_date=chunk.fetch_date,
                    url=chunk.url,
                ),
                provenance="corpus",
            )
        )
    return out


def safety_filter(
    sentences: list[AnswerSentence], language: str, cfg: GuardsConfig
) -> list[AnswerSentence]:
    """Drop any rendered sentence that certifies a plant 'safe' (never-certify-safe rule)."""
    return [s for s in sentences if not asserts_safety(s.text, language, cfg)]
