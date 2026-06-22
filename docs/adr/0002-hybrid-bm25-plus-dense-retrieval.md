# 2. Hybrid BM25 + dense retrieval

- Status: Accepted
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

Retrieval is mandatory and runs first: nothing downstream ever sees a passage that did not
clear the gate, and a weak retrieval is a refusal, not a hallucination opportunity. That
makes recall the single most consequential property of the system — a passage that is not
retrieved cannot be cited, and the answer the user deserved becomes an out-of-scope refusal.

The offline default embedder (ADR-0001) is a token-hashing projection, not a semantic
model. On its own it has a specific failure mode: it matches on shared *tokens*, so a
question phrased differently from the corpus ("my plant's leaves are going yellow") can
under-rank the passage that answers it, and unrelated text can occasionally score a small
spurious cosine via hash collisions. A pure-dense path over a weak embedder is therefore
brittle in exactly the cases users hit.

The spec lists **redundancy** as a quality attribute — "hybrid retrieval means one path's
miss is caught by the other" — and explicitly forbids adding a reranker "unless an eval
delta justifies it in an ADR."

## Decision

Retrieval is **hybrid** (`retrieve.py`): two independent ranking paths fused by
**Reciprocal Rank Fusion (RRF)**.

- **Dense path:** cosine over the `HashingEmbedding` vectors held in the `VectorStore`.
- **Lexical path:** Okapi **BM25** (`lexical.py`, `k1`/`b`/`rrf_k` in `config.py`).
- **Fusion:** RRF combines the two rank lists; one path's miss is recovered by the other.
- **Species/topic filter:** a *conservative* filter restricts candidates to a named plant
  when the question clearly names one (distinctive source-slug token intersecting the
  query, with a generic-token stoplist), so "is pothos toxic to cats?" cannot accidentally
  ground in a *Monstera* passage. When no species is clearly named, the filter is a no-op.
- **Threshold gate:** returned chunks carry their **cosine** score so `min_score` keeps a
  single, stable meaning under hybrid; `has_grounding()` additionally requires at least one
  shared content token between query and chunk, which makes out-of-scope refusal crisp
  rather than relying on a small spurious cosine.
- **Dedup:** near-duplicate chunks (Jaccard ≥ `dedup_threshold`) are collapsed so one fact
  does not crowd the citation list.

No reranker and no agentic loop. Hybrid is the cheapest redundancy that addresses the
weak-embedder failure mode; a reranker would be the next step *only* behind a measured eval
delta, per the spec.

## Consequences

- **Positive.** Recall is materially more robust than pure-dense over the offline embedder;
  the lexical path catches exact-term questions, the dense path catches loose paraphrase,
  and RRF needs no score normalisation between the two.
- **Positive.** The species filter is a structural defense against cross-species grounding,
  which is a *safety*-relevant error (toxicity answers must cite the right plant).
- **Positive.** `min_score` remains the single answer-vs-refuse knob, retrievable and
  testable; the gate is deterministic.
- **Negative.** Two code paths plus a filter is more surface than a single retriever; the
  conservative filter can occasionally fail to narrow to a species whose name is not in its
  source slug (it then falls back to the full corpus — a recall-safe, precision-lossy
  default).
- **Neutral.** RRF's `rrf_k` and BM25's `k1`/`b` are tunable in config, but per the spec
  they are tuned against eval failures only, never against vibes.
