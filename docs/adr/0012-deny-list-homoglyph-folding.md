# 12. Deny-list homoglyph folding and zero-width normalization hardening

- Status: Accepted
- Date: 2026-07-03
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

FIX-05 (`docs/ideation/02-large-scale-fixes.md`) tasked property-based fuzzing
(`tests/test_guard_fuzzing.py`, Hypothesis) with attacking `asserts_safety`,
`_supported_by`, and `citation_guard` with the inputs a cloud generator or an adversarial
corpus could actually produce: zero-width character injection, Unicode-confusable
homoglyph substitution, letter-spacing, and case perturbation.

The fuzzing demonstrated (not merely hypothesized) that:

1. Inserting a zero-width character (U+200B/U+200C/U+200D/U+FEFF) inside a denied phrase
   or a harm/negation token defeated both the deny-list phrase match (`guards._fold`) and
   the negation-aware harm-token check (`tokenize`), because neither routed through a
   Unicode-format-character strip.
2. Substituting a Cyrillic lookalike for a Latin vowel (e.g. Cyrillic "а" U+0430 for Latin
   "a" in "sаfe") defeated the deny-list phrase match — `_fold` folds accents and hyphens
   but had no homoglyph table.
3. Letter-spacing ("s a f e") and homoglyphs against the *harm-token/negation* branch
   (as opposed to the phrase-match branch) remain undefended; see Consequences.

This is exactly the residual the model card's "Cloud-mode residual risk" section already
names: the offline extractive generator cannot fabricate, so these guards are the sole
structural defense once a cloud generator composes free text.

## Decision

Two changes close (1) and (2) above:

- `src/sprout/text.py`: `normalize()` now applies Unicode NFKC normalization and strips
  characters in category `Cf` (format — covers ZWSP/ZWNJ/ZWJ/BOM) before the existing
  whitespace-collapse and lower-casing. The same strip is applied inside `tokenize()`
  (factored into a shared `_strip_zero_width` helper), because the negation-aware
  harm-token check in `asserts_safety` reads `tokenize(text)` directly rather than
  `normalize(text)`, and fuzzing showed it was independently bypassable. Characters are
  *removed*, not replaced with a space, so the surrounding letters re-join into the
  original word rather than splitting into spurious sub-tokens.
- `src/sprout/guards.py`: `_fold()` gains `_fold_homoglyphs()`, a **minimal, three-entry**
  table mapping the Cyrillic lookalikes fuzzing actually found effective (а/е/о →
  Latin a/e/o) onto their Latin counterparts. This is deliberately not a general
  confusables table (e.g. the full Unicode Consortium `confusables.txt`) — a small,
  auditable, documented table is preferred over a large opaque one for a
  CODEOWNERS-guarded safety file, consistent with the deny-list's existing "small,
  explicit, auditable" design (see `text.py` module docstring on `_STOPWORDS`).

This is a change to `src/sprout/guards.py`, a CODEOWNERS-guarded safety-critical file
(`.github/CODEOWNERS`: "Safety-critical guardrails — changes require an ADR and owner
review"), hence this ADR.

## Consequences

- **Positive.** The deny-list phrase match and the negation/harm-token check are both
  robust to zero-width-character injection, and the deny-list phrase match is robust to
  the three Cyrillic lookalikes fuzzing demonstrated. `tests/test_guard_fuzzing.py` pins
  this as a regression net: `asserts_safety(seed)` implies `asserts_safety(perturb(seed))`
  for zero-width and case perturbations, and (post-fix) for the homoglyph perturbation
  restricted to the deny-list phrase-match path.
- **Negative — the honest limit, same shape as ADR-0004's.** Homoglyph folding is scoped
  narrowly to `guards._fold` (the deny-list phrase-match path); it is **not** applied
  inside `tokenize()`, so the negation/harm-token branch of `asserts_safety` remains
  bypassable by a homoglyph substituted into a harm word (e.g. Cyrillic "о" in "tоxic")
  and is **not** applied to retrieval/stemming generally — routing Unicode confusable
  folding through `tokenize()` would change matching behavior for every caller (retrieval,
  citation coverage, the eval judge), which is a larger blast radius than this fix's scope
  and would need its own ADR and eval-delta justification (README: "no ... without an ADR
  justifying an eval delta"). Letter-spacing ("s a f e") is not defended at all — it
  defeats both the phrase-match and the token-based checks by construction, since spacing
  is exactly what both mechanisms use as a token boundary; a real defense (fuzzy or
  token-merge matching) is a larger change than this item's scope. Both residuals are
  pinned as documented, not-yet-defended cases in `tests/test_guard_fuzzing.py` rather than
  silently left unmeasured.
- **Positive.** `tests/test_guard_fuzzing.py` also quantifies the previously
  qualitative-only "cloud-mode residual" risk in the model card
  (`docs/cards/model-card.md`, "Cloud-mode residual risk"): `_supported_by`/
  `citation_guard`'s bag-of-token coverage check admits some fraction of same-plant
  cross-chunk sentence recombinations; the test measures and bounds that admit-rate rather
  than asserting a qualitative "bounded in practice."
- **Neutral.** No change to `forbidden_safe_phrases`, `toxicity_keywords`, or any
  per-language content — this hardens *matching*, not the deny-list's coverage.
