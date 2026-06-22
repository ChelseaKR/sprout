# 4. Never-certify-"safe" output guard

- Status: Accepted
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

Toxicity is the one place in Sprout where a wrong answer can hurt a living thing. A user
asking "is this safe for my cat?" is making a decision with a real downside, and the
failure that matters is not a missing citation — it is a *false reassurance*. Even a fully
grounded sentence can be dangerous: a corpus passage might say a plant is "generally
considered non-toxic," and an assistant that echoes "non-toxic" has effectively certified
safety on the strength of one source, for one animal, at one dose. The corpus is also
*silent* on most plant/species pairs, and silence must never read as "safe."

The second hard rule is therefore "**Never assert safety.** The assistant explains what a
cited source says about toxicity; it does not certify a plant safe and routes high-stakes
ingestion questions to a poison-control / vet contact line." This is a safety property that
must hold in **both** languages (EN/ES parity, ADR per the multilingual spec) and must be
independent of how the answer was generated.

## Decision

A dedicated **safety guard** layer, separate from the citation guard, enforces three things
(`guards.py`, `config.py::GuardsConfig`, `config.py::PromptConfig`):

1. **Classification.** `is_safety_query()` flags toxicity/ingestion questions by
   per-language keyword and phrase match (`toxicity_keywords`).
2. **Deny-list output filter.** `safety_filter()` / `asserts_safety()` drop *any* rendered
   sentence — even a grounded one — that contains a forbidden certification phrase, in
   either language: EN `"is safe"`, `"non-toxic"`, `"harmless"`, …; ES `"es seguro"`,
   `"no es tóxica"`, `"inofensiva"`, … The deny-list is per-language config, normalised
   before matching, and runs *after* the citation guard so it can veto an otherwise-valid
   sentence.
3. **Routing.** Every safety query — whether it answers or refuses — carries a
   `safety_notice` routing the user to a veterinarian or poison-control line
   (`safety_route_by_lang`), and the system prompt instructs the model never to certify a
   plant safe.

The guard is **fail-safe**: it can only ever *remove* a certification, never add one, so a
generator (offline or cloud) that emits "this is safe for cats" simply has that sentence
deleted, and if that empties the answer the result is a routed refusal.

## Consequences

- **Positive.** The safety suite verifies a structural property: for toxicity questions the
  assistant cites a toxicity reference, never renders a "safe" certification, and always
  routes to vet/poison-control — in EN and ES alike.
- **Positive.** The guarantee is provider-independent: it survives switching to the cloud
  Claude generator because the filter runs on output, not on the prompt.
- **Negative — the honest limit.** The deny-list is phrase-based, so it is only as complete
  as its phrase set; a novel certification phrasing in a third language, or a sufficiently
  oblique reassurance, could slip through until the list is extended. This is the standard
  deny-list weakness, mitigated by (a) extractive generation limiting phrasing to corpus
  text and (b) the safety suite as a regression net. Adding a language requires extending
  `forbidden_safe_phrases`, and that is an ADR-class change.
- **Negative.** Conservative classification means some non-safety questions that merely
  mention "cat" get a (harmless) routing notice attached. We accept over-routing.
- **Neutral.** This is explicitly *not* veterinary advice; the disclosure string says so in
  both languages.
