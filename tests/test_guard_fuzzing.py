"""Property-based (Hypothesis) fuzzing of the output guards.

Attacks ``asserts_safety`` (the never-certify-safe deny-list) and ``citation_guard``
(the grounding gate, backed by ``_supported_by``) with the perturbation classes a cloud
generator or an adversarial corpus could actually produce: zero-width-character
injection, Unicode-confusable homoglyph substitution, letter-spacing, case perturbation,
and same-plant cross-chunk sentence recombination.

This is FIX-05 (``docs/ideation/02-large-scale-fixes.md``): "This is hypothesized, not
demonstrated; the fix starts by demonstrating or falsifying it." Every perturbation class
below is resolved to one of two outcomes, never silently skipped:

- **invariant** — fuzzing found no bypass; pinned as a metamorphic property
  (``asserts_safety(seed)`` implies ``asserts_safety(perturb(seed))``) so it cannot
  silently regress.
- **residual** — fuzzing found a bypass; pinned as a documented, bounded, *known*
  limitation (never a silent failure) with a test that demonstrates it directly.

Zero-width injection and case perturbation turned out to be invariants (after the
``text.normalize``/``text.tokenize`` fix in this change — see ADR-0012). Homoglyph
substitution is an invariant for the deny-list *phrase-match* path only (after the
``guards._fold`` homoglyph table added in this change) and a residual for the
negation/harm-token path. Letter-spacing is a residual on every path. The citation-guard
cross-chunk recombination admit-rate is quantified, not just asserted nonzero/zero,
matching the model card's "Cloud-mode residual risk" note.
"""

from __future__ import annotations

import random

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sprout.config import Config
from sprout.guards import asserts_safety, citation_guard
from sprout.models import Chunk, RetrievedChunk

# Bounded profile: enough examples to explore each perturbation space, fast enough for CI.
_FUZZ = settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])

_GUARDS = Config().guards
_SUPPORT_OVERLAP = Config().generation.support_overlap

# Zero-width space, zero-width non-joiner, zero-width joiner, BOM/zero-width-no-break-space.
# Written as \u escapes, not literal glyphs, since they render invisibly in a diff/editor.
_ZERO_WIDTH = ["​", "‌", "‍", "﻿"]

# Latin -> Cyrillic lookalike substitution used to *attack* the guard (mirrors the minimal
# defense table in guards._HOMOGLYPHS). "s" is left alone: no single-character Cyrillic
# lookalike is worth adding to a minimal, auditable attack/defense table. Written as \u
# escapes so the confusable pair is explicit rather than visually indistinguishable in the
# source.
_LATIN_TO_CONFUSABLE = {
    "a": "\u0430",  # CYRILLIC SMALL LETTER A
    "o": "\u043e",  # CYRILLIC SMALL LETTER O
    "e": "\u0435",  # CYRILLIC SMALL LETTER IE
}


# --- seed corpus: sentences the guard must already flag, unperturbed ------------------


def _phrase_seeds() -> list[tuple[str, str]]:
    """(sentence, lang) pairs built from the live deny-list config (``forbidden_safe_phrases``),
    so the seed corpus tracks the config instead of hard-coding a copy of it."""
    seeds = []
    for lang, phrases in _GUARDS.forbidden_safe_phrases.items():
        for phrase in phrases:
            seeds.append((f"Some sources say this plant {phrase} for pets and children.", lang))
    return seeds


# Negated-harm sentences: "X is not toxic" reads as a de-facto safety certification and
# trips asserts_safety's negation-aware harm-token branch, not the phrase-match branch.
_NEGATED_HARM_SEEDS: list[tuple[str, str]] = [
    ("This plant is not toxic to cats.", "en"),
    ("It poses no risk to dogs or children.", "en"),
    ("The plant will not harm your pet.", "en"),
    ("No es tóxico para los gatos.", "es"),
    ("No representa ningún riesgo para los perros.", "es"),
]

_ALL_SEEDS: list[tuple[str, str]] = _phrase_seeds() + _NEGATED_HARM_SEEDS


def test_seed_corpus_trips_the_guard_unperturbed() -> None:
    """Sanity check on the seed corpus itself: every seed used below must already trip
    ``asserts_safety`` before any perturbation, or the invariant tests below would be
    vacuous."""
    for text, lang in _ALL_SEEDS:
        assert asserts_safety(text, lang, _GUARDS), f"seed must trip the guard: {text!r}"


# --- perturbation strategies -----------------------------------------------------------


@st.composite
def _zero_width_perturbation(draw: st.DrawFn, seed: tuple[str, str]) -> tuple[str, str]:
    """Insert 1..len(text) zero-width/format characters at random intra-string positions."""
    text, lang = seed
    n = draw(st.integers(min_value=1, max_value=max(1, len(text))))
    positions = draw(
        st.lists(st.integers(min_value=0, max_value=len(text)), min_size=n, max_size=n)
    )
    chars = draw(st.lists(st.sampled_from(_ZERO_WIDTH), min_size=n, max_size=n))
    out = list(text)
    for pos, ch in sorted(zip(positions, chars, strict=True), key=lambda p: -p[0]):
        out.insert(pos, ch)
    return "".join(out), lang


@st.composite
def _case_perturbation(draw: st.DrawFn, seed: tuple[str, str]) -> tuple[str, str]:
    """Swap the case of a random subset of characters."""
    text, lang = seed
    flips = draw(st.lists(st.booleans(), min_size=len(text), max_size=len(text)))
    out = "".join(
        ch.swapcase() if flip and ch.isalpha() else ch for ch, flip in zip(text, flips, strict=True)
    )
    return out, lang


@st.composite
def _homoglyph_perturbation(draw: st.DrawFn, seed: tuple[str, str]) -> tuple[str, str]:
    """Substitute a random, non-empty subset of a/o/e occurrences with Cyrillic lookalikes."""
    text, lang = seed
    idxs = [i for i, ch in enumerate(text) if ch.lower() in _LATIN_TO_CONFUSABLE]
    assert idxs, f"seed has no a/o/e to substitute: {text!r}"
    subset = draw(st.lists(st.sampled_from(idxs), min_size=1, max_size=len(idxs), unique=True))
    out = list(text)
    for i in subset:
        out[i] = _LATIN_TO_CONFUSABLE[out[i].lower()]
    return "".join(out), lang


def _seeds() -> st.SearchStrategy[tuple[str, str]]:
    return st.sampled_from(_ALL_SEEDS)


def _phrase_seeds_only() -> st.SearchStrategy[tuple[str, str]]:
    return st.sampled_from(_phrase_seeds())


# --- invariants: zero-width and case perturbations never defeat the guard -------------


@_FUZZ
@given(perturbed=_seeds().flatmap(_zero_width_perturbation))
def test_zero_width_injection_does_not_defeat_the_guard(perturbed: tuple[str, str]) -> None:
    """text.normalize / text.tokenize both strip Unicode format characters (category Cf,
    covering ZWSP/ZWNJ/ZWJ/BOM) before matching, so splicing them anywhere into a
    guard-tripping seed must not let it slip past either the deny-list phrase match or
    the negation-aware harm-token check."""
    text, lang = perturbed
    assert asserts_safety(text, lang, _GUARDS)


@_FUZZ
@given(perturbed=_seeds().flatmap(_case_perturbation))
def test_case_perturbation_does_not_defeat_the_guard(perturbed: tuple[str, str]) -> None:
    """Both matching paths lower-case before comparing, so case perturbation of a
    guard-tripping seed must not let it slip past."""
    text, lang = perturbed
    assert asserts_safety(text, lang, _GUARDS)


# --- homoglyph: invariant for the phrase-match path, residual for the harm-token path --


@_FUZZ
@given(perturbed=_phrase_seeds_only().flatmap(_homoglyph_perturbation))
def test_homoglyph_substitution_does_not_defeat_the_deny_list_phrase_match(
    perturbed: tuple[str, str],
) -> None:
    """guards._fold folds the minimal Cyrillic a/e/o lookalike table (ADR-0012) before the
    deny-list phrase-match check, so substituting Cyrillic lookalikes into a phrase-match
    seed must not let it slip past *this* path."""
    text, lang = perturbed
    assert asserts_safety(text, lang, _GUARDS)


def test_homoglyph_substitution_of_a_harm_token_is_a_documented_residual() -> None:
    """Known, undefended residual (see ADR-0012 Consequences): the negation-aware
    harm-token branch of ``asserts_safety`` reads ``text.tokenize``, which is not routed
    through the homoglyph fold (that fold is deliberately scoped to ``guards._fold`` only,
    to avoid changing retrieval/stemming behavior for every other caller). Substituting a
    Cyrillic lookalike into the harm word itself defeats this branch. This is filed here,
    not silently left unmeasured, as FIX-05 requires.
    """
    seed = "This plant is not toxic to cats."
    assert asserts_safety(seed, "en", _GUARDS)
    cyrillic_o = "\u043e"  # CYRILLIC SMALL LETTER O, substituted for "o" below
    bypass = seed.replace("o", cyrillic_o)
    assert not asserts_safety(bypass, "en", _GUARDS)


# --- letter-spacing: residual on every path ---------------------------------------------


@_FUZZ
@given(seed=_seeds())
def test_letter_spacing_is_a_documented_residual(seed: tuple[str, str]) -> None:
    """Known, undefended residual: inserting a space between every character breaks both
    the deny-list substring match and the negation/harm-token check, because whitespace is
    exactly what both mechanisms use as a token boundary. A real defense (fuzzy or
    token-merge matching) is a larger change than this item's scope; filed here rather than
    silently left unmeasured, per FIX-05."""
    text, lang = seed
    assert asserts_safety(text, lang, _GUARDS)
    spaced = " ".join(text)
    assert not asserts_safety(spaced, lang, _GUARDS)


# --- citation_guard: same-plant cross-chunk recombination -------------------------------


def _make_chunk(chunk_id: str, doc_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        title="Toxicity",
        source=f"{doc_id}.md",
        text=text,
        language="en",
        topic="toxicity",
        source_name="Synthetic",
        url=f"https://example.invalid/{doc_id}.md",
        license="CC0-1.0",
        fetch_date="2026-05-01",
    )


_POTHOS_CATS_TEXT = "Pothos is toxic to cats and causes oral irritation and vomiting."
_POTHOS_DOGS_TEXT = "Pothos exposure in dogs has been linked to drooling and lethargy."
_MONSTERA_TEXT = "Monstera contains calcium oxalate crystals that irritate the mouth."

_pothos_cats = _make_chunk("pothos-cats", "pothos", _POTHOS_CATS_TEXT)
_pothos_dogs = _make_chunk("pothos-dogs", "pothos", _POTHOS_DOGS_TEXT)
_monstera = _make_chunk("monstera-tox", "monstera", _MONSTERA_TEXT)
_RETRIEVED = [
    RetrievedChunk(chunk=_pothos_cats, score=0.9),
    RetrievedChunk(chunk=_pothos_dogs, score=0.9),
    RetrievedChunk(chunk=_monstera, score=0.9),
]
_POTHOS_TOKEN_POOL = _POTHOS_CATS_TEXT.split() + _POTHOS_DOGS_TEXT.split()


@st.composite
def _recombination_sentence(draw: st.DrawFn) -> str:
    """A sentence recombining a random subset (in random order) of the words across the
    two same-plant Pothos chunks — the "sentence recombining tokens across both chunks"
    FIX-05 asks for."""
    k = draw(st.integers(min_value=3, max_value=len(_POTHOS_TOKEN_POOL)))
    words = draw(
        st.lists(
            st.sampled_from(_POTHOS_TOKEN_POOL),
            min_size=k,
            max_size=k,
        )
    )
    return " ".join(words)


@_FUZZ
@given(sentence=_recombination_sentence())
def test_citation_guard_never_admits_recombination_against_an_unrelated_species(
    sentence: str,
) -> None:
    """Invariant (the model card's "bounded in practice because retrieval is
    species-scoped to one plant" claim, made structural): a sentence built purely from
    Pothos-chunk tokens must never be admitted as supported by an unrelated species'
    chunk (Monstera), regardless of recombination."""
    out = citation_guard([(sentence, "monstera-tox")], _RETRIEVED, _SUPPORT_OVERLAP)
    assert out == []


def test_citation_guard_recombination_admit_rate_is_quantified() -> None:
    """Quantifies the documented "Cloud-mode residual risk" in the model card: bag-of-token
    coverage in ``_supported_by`` can admit a same-plant cross-chunk recombination that was
    never actually written in either source chunk. This computes a real number (a
    deterministic Monte-Carlo sample, fixed seed for reproducibility) instead of leaving the
    residual as a qualitative note, per FIX-05's "Excellent looks like: ... the
    recombination residual carries a *number*."

    The bounds pin the residual as real (>0: recombination is sometimes admitted — this
    genuinely is a bypass) and partial (<1: the coverage/negation-polarity gates still
    reject most recombinations — this is not a wide-open hole). If a future guard
    improvement drives this to 0, tighten the lower bound in the same change (a good
    outcome); if it drifts towards 1, that is a regression and must be investigated before
    loosening the upper bound.
    """
    rng = random.Random(20260703)
    total = 300
    admitted = 0
    for _ in range(total):
        k = rng.randint(3, len(_POTHOS_TOKEN_POOL))
        sample = rng.sample(_POTHOS_TOKEN_POOL, k)
        rng.shuffle(sample)
        sentence = " ".join(sample)
        out_cats = citation_guard([(sentence, "pothos-cats")], _RETRIEVED, _SUPPORT_OVERLAP)
        out_dogs = citation_guard([(sentence, "pothos-dogs")], _RETRIEVED, _SUPPORT_OVERLAP)
        if out_cats or out_dogs:
            admitted += 1
    rate = admitted / total
    assert 0.05 <= rate <= 0.70, (
        f"same-plant cross-chunk recombination admit-rate = {rate:.1%} "
        f"({admitted}/{total}) fell outside the documented bound; see ADR-0012 and the "
        "model card's Cloud-mode residual risk note"
    )
