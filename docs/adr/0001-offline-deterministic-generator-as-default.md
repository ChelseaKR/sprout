# 1. Offline deterministic generator as the default

- Status: Accepted
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

Sprout's headline artifact is its eval report, and a report nobody can reproduce is a
marketing claim, not evidence. The standard hosted-LLM path makes the whole project
hostage to three things a reviewer cannot control: a cloud account and API key, network
access at eval time, and the non-determinism of a sampled model. Any of the three breaks
the Definition of Done — "run `make eval` to regenerate the committed report with no cloud
account" — and breaks the reproducibility attributes the spec commits to
(**determinability**, **repeatability**, **byte-identical reports from identical inputs**).

A hosted model is also a cost and an availability dependency: a public reference
implementation that costs money to demonstrate and dies when a provider deprecates a model
is not **self-sustaining**, which the spec lists as a quality attribute ("runs offline with
no paid dependency, so it survives without funding").

The portfolio standard reinforces this: `SECURITY-AND-SUPPLY-CHAIN-STANDARD` lets a repo
declare **ASVS L1** only when it has no network ingress in its default path (see ADR-0008),
and `AI-EVALUATION-STANDARD` requires a CI eval gate that runs in `pytest` — fast, offline,
no hosted dependency.

## Decision

The **default and only-required** generation stack is offline and deterministic:

- `HashingEmbedding` — a signed SHA-256 token-hashing bag-of-tokens projection,
  L2-normalised (`providers/deterministic.py`). SHA-256 is used purely as a stable
  token→dimension map, a non-cryptographic use that also keeps SAST quiet.
- pure-Python **BM25** (`lexical.py`) fused with the dense path (see ADR-0002).
- `ExtractiveGenerator` — returns only sentences copied verbatim from retrieved chunks,
  each tagged to its chunk id (see ADR-0003).

The same input always yields a byte-identical index and answer, so the index, the answers,
and the eval verdict are reproducible in CI with no network. A **Claude-on-Bedrock**
generator (and Titan embeddings), plus a native Anthropic generator, are the **production
seam** behind a single config switch (`generation.provider`,
`retrieval.embedding_provider` in `config.py`); they are lazily imported so
`pip install sprout` with no extras still runs end to end. The default answer model behind
that seam, when enabled, is **Claude Haiku** (kept distinct from the judge model — ADR-0009).

## Consequences

- **Positive.** `make eval`, `make demo`, and the full test suite run with no account, no
  key, no network. The eval report is byte-identical for identical inputs and the corpus
  index rebuilds from `make ingest` (recoverability).
- **Positive.** The project costs nothing to demonstrate and survives provider churn; the
  cloud path is opt-in and budget-alarmed.
- **Positive.** Determinism makes every component unit-testable without mocking a model.
- **Negative — the honest limit, stated in the model card.** The hashing embedder is a
  retrieval *baseline*, not a semantic model: it matches on shared tokens, so paraphrase
  recall is weaker than a real dense embedder, and synonyms ("yellowing" vs "chlorosis")
  can be missed. This is a deliberate floor, not a ceiling — production recall comes from
  the Bedrock/Titan seam.
- **Negative.** The extractive generator's prose is stiffer than a fluent model's; we trade
  fluency for groundedness-by-construction (ADR-0003) and accept it.
- **Neutral.** Two stacks must stay behind one interface (`providers/base.py`); the
  adapter boundary is the cost of keeping offline and cloud modes **seamless**.
