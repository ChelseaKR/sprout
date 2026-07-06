# 10. Photo plant-ID is a selector, not a source of fact

- Status: Accepted
- Date: 2026-06-29
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

Users often do not know a plant's name — they have a photo. Accepting a photo and answering
"what is this and how do I care for it?" is the single most-requested houseplant feature.
But a vision model is a *generative* system with exactly the failure mode Sprout exists to
prevent: it can confidently name a plant that is wrong, and any care/toxicity answer built on
that wrong name is a fluent, dangerous fabrication — even if every sentence is "cited."

The four hard rules (retrieval-mandatory, no claim without a citation, never certify safe,
offline by default) must survive the photo path. The temptation is to treat the vision
model's output as fact and let it flow into the answer. That would breach the grounding
contract at its weakest seam.

## Decision

A photo identification is treated as a **selector, never a fact** — the same contract the
README already defines for Family-Greenhouse household data ("household data only selects and
personalises; only the cited corpus is a source of fact").

The path (`identify.py`) is:

1. **Identify.** A pluggable `PlantIdentifier` returns scored candidate species
   (`Identification`). The offline default (`OfflineIdentifier`) performs no network call and
   no on-device inference and always returns nothing. The `plantnet` provider
   (`providers/plantnet.py`) calls one allowlisted, plant-domain endpoint — the
   [Pl@ntNet API](https://my.plantnet.org/) — with its key read from `PLANTNET_API_KEY`
   (environment only). It is fail-closed: any error, missing key, or malformed response
   yields zero candidates.
2. **Resolve.** `resolve_species()` maps the best candidate that clears `min_confidence` to a
   species **already present in the cited corpus** (by scientific binomial, common-name token,
   or the existing alias glossary). A low-confidence match, or a species the corpus does not
   cover, does **not** resolve.
3. **Route.** The resolved species name is injected into the *unchanged* grounded pipeline
   (`Assistant.answer`), where it drives the existing species-scoped retrieval. The rendered
   answer is therefore produced by retrieve → extractive-generate → citation-guard →
   never-certify-safe → calibrated-abstention exactly as a typed question would be. Every
   sentence is still cited; toxicity still routes to a vet.
4. **Label, never assert.** The visual identification is surfaced *beside* the answer with the
   disclosure "a visual match, not a cited fact." It never enters `Answer.sentences` and is
   never citation-checked, because it is not presented as fact.
5. **Fallback.** Offline provider, no candidate, low confidence, or an off-corpus species all
   degrade to a localized "type the plant's name" message — the corpus-only path is always
   available.

## Consequences

- **Positive.** Groundedness is preserved *by construction*: the photo path adds no new way
  for an unsupported claim to render. The identifier can be wrong and the worst case is a
  cited answer about the wrong (but real, corpus-covered) plant, or a graceful fallback —
  never an invented fact. This is provable with offline tests (`test_identify.py`) because the
  whole resolution/routing logic is deterministic; only the thin HTTP shell needs a key.
- **Positive — minimal egress.** Exactly one new outbound call, to one allowlisted
  plant-specific API, behind an env-only key and a config switch. The default ships offline.
- **Negative — the honest limit.** Sprout can only ground answers for species in its corpus,
  so identification of an off-corpus plant resolves to a fallback even when the vision model is
  correct. Expanding coverage is a corpus change (data, not code), consistent with ADR-0006.
- **Negative.** A confident *wrong* identification of an in-corpus species yields a correct,
  cited answer about the wrong plant. We mitigate with the `min_confidence` gate and the
  explicit "visual match, not a cited fact" label, and we do not auto-act on the result.
- **Neutral.** The provider is pluggable; swapping Pl@ntNet for another allowlisted identifier
  is an adapter, not a pipeline change.
