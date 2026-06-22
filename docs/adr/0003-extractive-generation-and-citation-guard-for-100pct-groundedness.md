# 3. Extractive generation + citation guard for 100% groundedness

- Status: Accepted
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

The first hard rule is "**No claim without a citation.** Every substantive sentence
resolves to a retrieved passage or it does not render." The conventional RAG approach —
prompt a generative model with retrieved context and *ask* it to cite — makes groundedness
a *probability*, measured after the fact and never quite 1.0. Faithfulness benchmarks
(`AI-EVALUATION-STANDARD` sets a floor of ≥0.80) exist precisely because free-form
generation drifts: it paraphrases past what the source says, blends two passages, or
invents a plausible detail. For a domain with a real safety edge (toxicity), "usually
grounded" is the wrong target.

We want groundedness that is **true by construction**, not measured-and-hoped, so that the
eval's groundedness suite is *verifying an invariant* rather than discovering a rate.

## Decision

Generation is **extractive**, and an independent **citation guard** re-verifies it.

1. The default `ExtractiveGenerator` (`providers/deterministic.py`) returns only sentences
   **copied verbatim** from retrieved chunks, each tagged with its `chunk_id`. There is no
   text path by which it can fabricate.
2. The **citation guard** (`guards.py::citation_guard`) is the load-bearing gate and runs
   *after* generation, independent of the generator. A candidate sentence survives only if
   (a) its `chunk_id` was actually retrieved and (b) the chunk text supports the sentence —
   verbatim containment or token coverage ≥ `support_overlap` (default 0.66). Survivors
   become `AnswerSentence` objects carrying a full `Citation` (source, license, fetch date,
   quote) and tagged `provenance="corpus"`. **Whatever survives the guard *is* the answer;
   if nothing survives, that is a refusal** (`answer.py`).

Because the guard is independent of the generator and applies the *same* check regardless
of provider, it holds for the production Claude seam too: a model that paraphrases past its
source has those sentences dropped before they reach a user. Ungrounded output is therefore
**structurally impossible to render**, not merely discouraged — groundedness is 100% by
construction, and the citation guard doubles as the structural defense against
prompt-injection (an injected instruction cannot be entailed by a corpus chunk, so it never
survives; injection detection in `guards.py` is observability only).

## Consequences

- **Positive.** The groundedness suite verifies an invariant; the spec's **correctness**,
  **precision/fidelity**, and **traceability** attributes are mechanical, not aspirational.
  Every rendered sentence carries its exact passage and fetch date.
- **Positive.** The guard is the seam where the cheap offline generator and the expensive
  cloud generator are held to the *identical* bar, so the safety property does not depend on
  which provider is configured.
- **Positive.** Injection defense is a free side effect of the entailment requirement.
- **Negative — the honest limit.** Extractive prose reads stiffly: answers are stitched
  source sentences, not a synthesised paragraph. We accept reduced fluency for guaranteed
  groundedness; the model card states this.
- **Negative.** The coverage-overlap check is lexical, so a *correct* paraphrase from the
  cloud generator can be dropped as "unsupported." This is a deliberate false-negative bias
  — over-refusing is safe; over-claiming is not.
- **Neutral.** `support_overlap` is tunable, but it is a guardrail: changing it is an
  ADR-class change per the README.
