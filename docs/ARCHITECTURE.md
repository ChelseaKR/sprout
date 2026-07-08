# Architecture

> **Audience:** contributors and reviewers who need to know *where* a property lives in
> the code before they change it. This document describes the runtime pipeline, the
> provider seam, the in-repo eval harness, the data flow, and the invariants that the
> CI gates exist to protect. It references named engineering standards; per-repo *values*
> (coverage, thresholds, ASVS level) live in [`docs/ROADMAP.md`](ROADMAP.md).
>
> **Last verified:** 2026-06-22 · **Author:** Chelsea Kelly-Reif

---

## 1. The one idea

Sprout is **extractive RAG with a post-generation citation guard**, so groundedness is
100% *by construction* rather than by hope. The generator may only emit sentences copied
verbatim from retrieved passages; an independent guard re-verifies each one against the
chunk it claims; whatever survives *is* the answer. There is no text path by which an
ungrounded sentence reaches a user — which is also why the assistant exists mainly to give
the eval harness something honest to measure.

Everything that touches a model hides behind two `Protocol`s, and the default
implementations are deterministic and offline, so the whole project — including the eval —
runs with no network and no cloud account.

---

## 2. The answer pipeline

The pipeline contract is encoded as control flow in
[`src/sprout/answer.py`](../src/sprout/answer.py) (`Assistant.answer`). Each stage can only
*narrow* what reaches the user; none can introduce unsupported content.

```
                          ┌─────────────────────────── sprout ask / serve ───────────────────────────┐
                          │                                                                            │
   question ──▶ resolve language (lang.py) ──▶ classify safety query (guards.is_safety_query)          │
                          │                                                                            │
                          ▼                                                                            │
            ┌─────────────────────────────┐                                                            │
            │  retrieve  (retrieve.py)    │   hybrid: dense cosine  +  BM25                             │
            │  HashingEmbedding ⨉ store   │   fused by Reciprocal Rank Fusion (RRF)                     │
            │  species/topic filter       │   dedup by Jaccard                                          │
            └──────────────┬──────────────┘                                                            │
                           │ has_grounding()? = best cosine ≥ min_score AND shares a content term       │
                  no ──────┴───────────────────────────────▶  REFUSE (out_of_scope)  ──┐               │
                           │ yes                                                        │               │
                           ▼                                                            │               │
            ┌─────────────────────────────┐                                            │               │
            │ extractive generate          │  GenerationProvider.generate(...)          │               │
            │ (providers/deterministic)    │  returns [(sentence, chunk_id)] verbatim   │               │
            └──────────────┬──────────────┘                                            │               │
                           ▼                                                            │               │
            ┌─────────────────────────────┐                                            │               │
            │ citation_guard (guards.py)   │  re-verify each sentence ⟶ its chunk;       │               │
            │  LOAD-BEARING GATE           │  drop unsupported; tag provenance="corpus" │               │
            └──────────────┬──────────────┘                                            │               │
                           ▼                                                            │               │
            ┌─────────────────────────────┐                                            │               │
            │ safety_filter (guards.py)    │  drop any surviving sentence that          │               │
            │  never-certify-"safe"        │  certifies "safe"/"non-toxic" (EN+ES)      │               │
            └──────────────┬──────────────┘                                            │               │
                  empty ───┴───────────────────────────────▶  REFUSE (no_supported_…) ─┤               │
                           │ survivors                                                  │               │
                           ▼                                                            │               │
            ┌─────────────────────────────┐                                            │               │
            │ confidence (confidence.py)   │  score from retrieval evidence;            │               │
            │  abstain below threshold     │  below abstain_threshold ──▶ REFUSE ───────┤               │
            └──────────────┬──────────────┘   (low_confidence)                          │               │
                           ▼                                                            ▼               │
                 Answer(cited, as_of date,                                  Answer(refused=True,        │
                 confidence, safety_notice                                  refusal_text, +safety       │
                 if toxicity query)                                         routing if toxicity query)  │
                          └─────────────────────────────────────────────────────────────┘             │
                                                                                                        │
   For ANY toxicity/ingestion question (answer OR refusal), a vet / poison-control routing notice       │
   is attached. The assistant never certifies a plant "safe".                                           │
                          └─────────────────────────────────────────────────────────────────────────────┘
```

Stage by stage:

1. **Language resolution** ([`lang.py`](../src/sprout/lang.py)). An explicit `language`
   wins if supported; otherwise it is detected, falling back to the corpus default. The
   resolved language drives every downstream string (refusal, safety routing, disclosure)
   so EN/ES parity is a property of one variable, not scattered branches.

2. **Safety classification** (`guards.is_safety_query`). Toxicity/ingestion intent is
   detected from per-language keyword lists *before* retrieval, so the routing directive can
   be attached to both the answer and the refusal paths.

3. **Retrieval is mandatory and first** ([`retrieve.py`](../src/sprout/retrieve.py)). Two
   ranking paths — cosine over `HashingEmbedding` vectors and Okapi BM25 — are fused by
   Reciprocal Rank Fusion (`rrf_k`), then near-duplicates are dropped by a Jaccard
   threshold. A conservative species/topic filter restricts candidates to the named plant
   when the question clearly names one, so "is pothos toxic to cats?" cannot ground in a
   Monstera passage. The chunks always carry their **cosine** score, so `min_score` keeps a
   stable meaning under hybrid fusion and is the single gate that decides answer-vs-refuse.
   `has_grounding()` additionally requires at least one shared content token — this makes
   out-of-scope refusal crisp despite the offline hashing embedder's occasional spurious
   cosine from hash collisions. **No grounding ⟶ immediate refusal; the generator is never
   asked to fill the gap.**

4. **Extractive generation** (`GenerationProvider.generate`). The offline
   `ExtractiveGenerator` scores each candidate sentence by query-token overlap (nudged by
   retrieval rank), returns the top *n* as `(sentence, chunk_id)` pairs copied **verbatim**
   from chunk text, and deduplicates. It has no path to fabricate.

5. **Citation guard** (`guards.citation_guard`) — *the load-bearing gate*. A candidate
   survives only if (a) its `chunk_id` was actually retrieved and (b) the chunk text
   *supports* the sentence (verbatim containment, or token coverage ≥ `support_overlap`).
   Survivors become `AnswerSentence`s carrying a full `Citation` (doc, source, license,
   fetch date, URL, quote) and tagged `provenance="corpus"`. This is why ungrounded output
   is *structurally impossible*, not merely discouraged — and why a misbehaving cloud
   provider degrades to a refusal rather than a hallucination. On the cloud path, an
   optional cross-encoder **NLI entailment verifier** (`verifiers.py`, EXP-04, ADR-0013;
   `generation.support_verifier: nli`) adds a second, model-based gate after the lexical
   one — closing the residual same-plant sentence-recombination risk the lexical
   bag-of-tokens check cannot see. It is strictly additive (can only drop what the lexical
   check already accepted, never admit more) and the offline path never passes one.

6. **Never-certify-safe filter** (`guards.safety_filter`). Any surviving sentence that
   asserts "safe"/"non-toxic"/"harmless" (per-language deny-list, accent-normalized) is
   dropped. The guarantee is enforced on rendered output, in both languages.

7. **Calibrated confidence** ([`confidence.py`](../src/sprout/confidence.py)). Confidence is
   a transparent logistic of *retrieval evidence* — best cosine, nudged by the margin over
   the runner-up — deliberately **not** answer fluency (which would reward confident
   nonsense). Below `abstain_threshold` the assistant refuses; below
   `low_confidence_threshold` it answers but flags the answer for review.

8. **Render or refuse**. A rendered `Answer` carries its sentences+citations, an `as_of`
   date (the newest cited `fetch_date`), the confidence, the localized disclosure, and a
   safety routing notice when the query was a toxicity query. A refusal carries a localized
   refusal message, a machine-readable `refusal_reason`
   (`out_of_scope` / `no_supported_sentences` / `low_confidence`), and the same safety
   routing when applicable.

A parallel `Assistant.trace()` returns the full retrieval + raw-candidate +
injection-category trace for the `--debug` flag (Debuggability/Inspectability), without
changing the answer.

---

## 3. The provider seam (offline default / cloud production)

All model-touching code hides behind two narrow `Protocol`s in
[`providers/base.py`](../src/sprout/providers/base.py); callers never import a concrete
provider, and [`providers/__init__.py`](../src/sprout/providers/__init__.py) resolves config
strings to implementations with **lazy imports** (so `boto3`/`httpx` are only imported when
the cloud path is actually selected — `pip install sprout` with no extras runs end to end).

| Protocol | Method | Offline default | Cloud / production seam |
|---|---|---|---|
| `EmbeddingProvider` | `embed(text) -> vector` | `HashingEmbedding` (SHA-256 token→dim projection, L2-normalized, deterministic) | `TitanEmbedding` (Amazon Titan v2 on Bedrock) |
| `GenerationProvider` | `generate(query, context, n) -> [(sentence, chunk_id)]` | `ExtractiveGenerator` (verbatim sentence selection) | `BedrockGenerator` (Claude Haiku) · `AnthropicGenerator` (native API) |

The seam's safety posture is **identical across implementations**, which is the point of a
narrow contract:

- The generator may only return `(sentence, chunk_id)` pairs drawn from supplied context;
  the citation guard re-verifies every one regardless of who produced it. A *wrong
  attribution* from a cloud model is dropped, not shown.
- `BedrockGenerator` mirrors the offline failure posture exactly: any exception, timeout, or
  malformed/empty model response returns an **empty candidate list**, so a provider outage
  degrades to a refusal — never an ungrounded answer. The boto client is configured with a
  5 s connect / 60 s read timeout and bounded retries.
- The **answer model is Claude Haiku**; the **judge model is Claude Sonnet** — judge ≠
  answer model is structural (see §4). Production uses Claude via Bedrock behind
  `generation.provider: bedrock`; see the [model card](cards/model-card.md) and
  `STANDARDS/AI-EVALUATION-STANDARD.md`.

Offline is the **default and the privacy-preserving mode**: it costs nothing, needs no
account, and makes every component unit-testable. The cloud path is a config switch
(Interchangeability), not a code change at the call sites.

The index itself ([`store.py`](../src/sprout/store.py)) is a flat in-memory cosine store
serialized to one JSON file — **no database, no mutable server state**. Recovery is
"re-ingest" (`sprout ingest`).

---

## 4. The eval harness (the actual product)

The harness lives in [`src/sprout/eval/`](../src/sprout/eval/) and is corpus-agnostic and
reusable. It blends **deterministic checks** with an **LLM-as-judge**, and is **fail-closed
everywhere**: a hash mismatch, a malformed case, an empty suite, or a malformed judge
response fails the run rather than passing quietly.

```
eval/suites/*.yaml ─▶ dataset.load_suite_dir() ──▶ Dataset (content-addressed, sha256:<hash[:12]>)
   (120+ cases)         │  Pydantic extra="forbid"     │  verified against eval/suites.sha256 sidecar
                        │  fail-closed on bad case      │  (mismatch ⟶ DatasetError)
                        ▼                               ▼
            ┌───────────────────────────────────────────────────────┐
            │ run_evaluation(dataset, judge, suites, target, seed)   │   runner.py
            │  • RunFingerprint = {harness_ver, seed, dataset_hash,  │   (NO wall-clock ⟶ byte-identical
            │    judge_config_hash, target, suite_names}             │    artifact for identical inputs)
            │  • each suite.run(ctx) in a try/except                 │
            │      raises  ⟶  fail_closed() FAIL (never aborts run)  │
            │  • optional Wilson-lower-bound statistical gate        │
            └───────────────────────────┬───────────────────────────┘
                                         ▼
         ┌──────────┬──────────┬──────────────┬───────────┬───────────────┐
         │ grounded │  safety  │ calibration  │  refusal  │  multilingual │   suites/ (self-register)
         └────┬─────┴────┬─────┴──────┬───────┴─────┬─────┴──────┬────────┘
              │          │            │             │            │
              │  Judge protocol (judge.py) — the single model-touching seam:
              │  entails / contains / equivalent
              │     DeterministicJudge (lexical coverage + negation-polarity guard, offline)
              │     AnthropicJudge     (Claude Sonnet; injected CompletionFn; malformed ⟶ raises)
              ▼
         SuiteResult (verdict, score, Wilson CI, n_items, judge_config_hash, failing_examples)
              ▼
         report.py ─▶ EVALS / eval-report.{md, html, json}  +  JUnit XML  +  SARIF
                       (pure function of RunResult; HTML self-checked for a11y before write)
```

Key design points, mapped to code:

- **Fail-closed data boundary** ([`dataset.py`](../src/sprout/eval/dataset.py)). Cases are
  authored one YAML file per suite, parsed into a strict `DatasetItem`
  (`extra="forbid", frozen=True`). The combined `Dataset` is **content-addressed** — its
  version is `sha256:<hash[:12]>` over canonical items — and a committed `suites.sha256`
  sidecar pins it. A mismatch raises `DatasetError`: the dataset is tamper-evident and
  reproducible. Duplicate ids and empty datasets also raise.

- **Run identity = fingerprint** ([`runner.py`](../src/sprout/eval/runner.py)). The
  `RunFingerprint` (harness version, seed, dataset hash, judge config hash, target, suite
  names) deliberately excludes wall-clock time, so the JSON artifact is **byte-identical for
  identical inputs** — the reproducibility property the report and the baseline diff rely
  on. Threshold overrides are applied copy-on-write so registry singletons are never
  mutated.

- **No "skipped" verdict** ([`suite.py`](../src/sprout/eval/suite.py)). `Verdict` is only
  PASS or FAIL. A `SuiteResult` with `n_items == 0` *cannot* be PASS (a validator raises);
  any suite that throws is converted to a zero-item `fail_closed` FAIL. Every suite carries a
  written `MetricDefinition` (name, definition, threshold, direction) reproduced verbatim in
  the report — no opaque score. Each result also carries a **Wilson confidence interval**
  and an `underpowered` (n<30) flag; the optional statistical gate flips PASS→FAIL when the
  CI lower bound does not clear the threshold.

- **Judge ≠ answer model, behind one Protocol** ([`judge.py`](../src/sprout/eval/judge.py),
  [`llm_judge.py`](../src/sprout/eval/llm_judge.py)). A suite asks only three relational
  questions — `entails` (groundedness), `contains` (fact/anchor coverage), `equivalent`
  (multilingual). That is the *only* place a model is consulted, so a suite is identical
  whether run under the offline `DeterministicJudge` (lexical coverage + a negation-polarity
  contradiction guard, fully reproducible, no network) or the `AnthropicJudge` (Claude
  **Sonnet**, distinct from the **Haiku** answer model). The judge's `config_hash` — model
  id, prompt version, temperature, thresholds — is folded into the run fingerprint, so any
  judge change is visible in the run identity and invalidates a stale calibration record.
  The model call is an injected `CompletionFn`, so the harness is fully testable offline and
  never hit in CI; malformed judge JSON raises (fail-closed).

- **The five suites** ([`suites/`](../src/sprout/eval/suites/)). `groundedness` (every claim
  entailed by its cited passage; contradicted vs unsupported), `safety` (deterministic: no
  "safe" certification, routes to vet/poison-control, cites a toxicity reference or honestly
  refuses — threshold 0.95, immune to judge drift), `calibration` (reliability diagram +
  ECE; abstains below threshold), `refusal` (out-of-scope, "just tell me it's fine",
  embedded prompt injection), `multilingual` (Spanish answers preserve the facts and
  citations of their English mirror, `|EN−ES| ≤ 5pp` parity).

- **Reproducible reporting** ([`report.py`](../src/sprout/eval/report.py)). Every artifact
  is a pure function of `RunResult` (no wall-clock): Markdown scoreboard, an HTML report that
  is **structurally accessibility-checked before it is written** (we never emit an
  inaccessible accessibility tool), plus JUnit and SARIF so any CI can annotate failures.
  Failures are shown with full traces, never hidden.

---

## 5. Data flow and provenance

```
corpus/manifest.yaml  (per-doc: title, source, url, license, fetch_date, language, topic)
        │   ingest.py: every processed file MUST have a manifest row, or ingest fails loudly
        ▼
corpus/processed/*.{en,es}.md ──▶ Document ──▶ chunk_document() ──▶ Chunk (carries provenance)
        │                                            (by care topic, overlap)
        ▼   embed each chunk (HashingEmbedding | Titan)
   VectorStore  ──save──▶  index.json  (sorted-key, format-versioned; rebuilds from `make ingest`)
        │
        ▼
   query time: Retriever ⟶ RetrievedChunk{chunk, cosine score}
        ▼
   ExtractiveGenerator ⟶ (sentence, chunk_id)  ─verbatim─▶  citation_guard ⟶ AnswerSentence{citation}
        ▼
   Answer{sentences, citations(source+license+fetch_date), as_of, confidence, safety_notice}
```

Provenance is enforced at the data boundary, not hoped for downstream
([`ingest.py`](../src/sprout/ingest.py)): the manifest is the source of truth, and a
processed file with no matching `ManifestEntry` (source, url, license, fetch_date, language,
topic) raises during ingest. Every chunk — and therefore every citation — carries source,
license, and fetch date, which is how the UI honestly shows "based on references as of
&lt;date&gt;." The bundled corpus and eval data are **synthetic and CC0-1.0**.

---

## 6. Key invariants (what the CI gates protect)

These are the properties a reviewer must preserve. Several are guarded by CODEOWNERS +
an ADR requirement; see the [README "Hard guardrails"](../README.md) note.

| # | Invariant | Enforced in |
|---|---|---|
| **I1** | **No claim without a citation.** Every rendered sentence resolves to a retrieved chunk that supports it; unsupported sentences cannot render. | `guards.citation_guard`; `answer.answer` makes survivors *be* the answer |
| **I2** | **Retrieval is mandatory and first.** No grounding ⟶ refuse; the generator never fills a gap. | `retrieve.has_grounding`, `answer.answer` |
| **I3** | **Never certify "safe."** No rendered sentence asserts safety in any supported language. | `guards.safety_filter` / `asserts_safety`; `safety` eval suite (threshold 0.95) |
| **I4** | **Toxicity questions route to vet / poison-control** — on both the answer and refusal paths. | `is_safety_query` ⟶ `safety_notice`; `safety` suite asserts routing |
| **I5** | **Calibrated abstention.** Confidence is a function of retrieval evidence (not fluency); below threshold the assistant refuses. | `confidence.score_confidence` / `should_abstain` |
| **I6** | **Provider failure degrades to a refusal**, never an ungrounded answer. | `BedrockGenerator.generate` returns `[]` on any error; `[]` ⟶ refusal |
| **I7** | **Determinism / reproducibility.** Same inputs ⟶ byte-identical index and eval artifacts; no wall-clock or RNG in the hash path. | `determinism.py`; `RunFingerprint`; `report.py` pure functions |
| **I8** | **Fail-closed evaluation.** Hash mismatch, malformed case, empty/zero-item suite, or malformed judge output ⟶ FAIL. | `dataset.load_suite_dir`, `suite.SuiteResult` validator, `runner` try/except, `llm_judge._parse_score` |
| **I9** | **Judge ≠ answer model**, and judge config is part of run identity. | `llm_judge.DEFAULT_JUDGE_MODEL` (Sonnet) vs answer Haiku; `config_hash` in fingerprint |
| **I10** | **Provenance is mandatory.** No corpus passage without source + license + fetch_date. | `ingest.load_corpus` raises on a file with no manifest entry |
| **I11** | **PII-free logs by construction.** Only whitelisted low-cardinality fields are logged; question text never is. | `obs.Logger._ALLOWED_FIELDS` |
| **I12** | **EN/ES parity.** One resolved-language variable drives every user-facing string; the multilingual suite gates `|EN−ES| ≤ 5pp`. | `answer._resolve_language`; `multilingual` suite |

---

## 7. What is deliberately *not* here

- **No agentic loop, no reranker, no database.** Added only behind an ADR that shows an eval
  delta justifying the complexity.
- **No user-query persistence** in the demo (Securability/Confidentiality).
- **Family Greenhouse personalization** (household-data path, provenance tag
  `from your Greenhouse`, ASVS L2) is **deferred to a later phase**; see
  [`CLAUDE.md`](../CLAUDE.md) and [`docs/ROADMAP.md`](ROADMAP.md). The grounding contract is
  already designed for it: household data may *select and personalize* but never renders as a
  cited horticultural fact.

## 8. See also

- [`docs/THREAT-MODEL.md`](THREAT-MODEL.md) — STRIDE analysis with mitigations mapped to code.
- [`docs/cards/model-card.md`](cards/model-card.md) — limits stated plainly.
- [`docs/ACCESSIBILITY.md`](ACCESSIBILITY.md) + the ACR — WCAG 2.2 AA posture.
- `STANDARDS/` — the cross-cutting rigor this repo conforms to.
