"""Input/output guards — where "grounded" and "never certify safe" become structural.

The citation guard is the load-bearing gate: it re-verifies every candidate sentence
against the chunk it claims to come from and drops anything it cannot support, so an
ungrounded sentence is *structurally impossible* to render, not merely discouraged. The
safety-assertion guard drops any sentence that certifies a plant "safe"/"non-toxic" in
either language. Scope is enforced upstream by the retrieval threshold; PII redaction and
injection detection guard the (optional) network path and the logs.
"""

from __future__ import annotations

import re

from .config import GuardsConfig
from .models import AnswerSentence, Citation, RetrievedChunk
from .text import (
    contains_phrase,
    coverage,
    has_negation,
    normalize,
    strip_accents,
    token_set,
    tokenize,
)

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


def _fold(text: str) -> str:
    """Normalise for safety matching: lower-case, collapse space, fold accents and hyphens.

    Accent- and hyphen-folding keep the deny-list robust to "non-toxic" vs "non toxic" and
    Spanish accent variants, consistent with how the rest of the pipeline tokenises.
    """
    return strip_accents(normalize(text)).replace("-", " ")


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


# Toxicity/harm terms whose negation amounts to a safety certification (EN + ES, folded).
_HARM_TOKENS = frozenset(
    {
        "toxic",
        "toxico",
        "toxica",
        "poison",
        "poisonous",
        "venenosa",
        "veneno",
        "harm",
        "harmful",
        "danger",
        "dangerous",
        "risk",
        "riesgo",
        "hurt",
    }
)
# Source-attribution markers: their presence means the sentence reports what the cited
# source says (or does not say), not a bare certification.
_SOURCE_MARKERS = frozenset(
    {
        "cited",
        "reference",
        "source",
        "list",
        "listed",
        "according",
        "states",
        "fuente",
        "citada",
        "indica",
        "lista",
        "listada",
        "menciona",
        "segun",
    }
)


def _supported_by(sentence: str, chunk_text: str, support_overlap: float) -> bool:
    """A sentence is supported iff it is verbatim-contained, or sufficiently covered AND
    its negation polarity matches the source.

    The polarity gate is load-bearing for the cloud generators: token coverage strips
    negations, so "X is not toxic" would otherwise score as covered by "X is toxic". A
    content-free fragment is never supported (it must carry at least one content token).
    """
    if contains_phrase(chunk_text, sentence):
        return True
    if not token_set(sentence):
        return False
    if has_negation(sentence) != has_negation(chunk_text):
        return False
    return coverage(sentence, chunk_text) >= support_overlap


def citation_guard(
    candidates: list[tuple[str, str]],
    retrieved: list[RetrievedChunk],
    support_overlap: float,
) -> list[AnswerSentence]:
    """Re-verify each candidate sentence against its cited chunk; drop the unsupported.

    This is why ungrounded generation is structurally impossible. A candidate survives
    only if (a) its ``chunk_id`` was actually retrieved and (b) the chunk's text supports
    the sentence. Survivors become :class:`AnswerSentence` objects tagged ``corpus``.
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
