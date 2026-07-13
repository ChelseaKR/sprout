---
language:
  - en
  - es
license: apache-2.0
library_name: sprout
pipeline_tag: question-answering
tags:
  - retrieval-augmented-generation
  - rag
  - grounded-generation
  - extractive-qa
  - plant-care
  - horticulture
  - safety
  - calibration
  - multilingual
  - evaluation-harness
  - responsible-ai
base_model: null
datasets:
  - sprout-synthetic-corpus-cc0
co2_eq_emissions:
  emissions: 0
  source: "No training or fine-tuning is performed; the default stack runs offline on CPU. See 'Environmental footprint'."
model-index:
  - name: sprout
    results:
      - task:
          type: question-answering
          name: Grounded plant-care QA (offline deterministic stack)
        dataset:
          type: sprout-eval-suites
          name: Sprout eval suites (synthetic, CC0-1.0)
          config: offline-deterministic
        metrics:
          - type: groundedness
            name: Groundedness (every claim entailed by its cited passage)
            value: 1.0
            verified: false
          - type: citation-coverage
            name: Citation coverage (rendered sentences resolving to a corpus chunk)
            value: 1.0
            verified: false
          - type: safety-certification-rate
            name: Forbidden "safe"/"non-toxic" certifications emitted
            value: 0.0
            verified: false
          - type: en-es-parity
            name: EN/ES pass-rate parity gap (|EN - ES|, lower is better; gate <= 0.05)
            value: null
            verified: false
          - type: expected-calibration-error
            name: Expected Calibration Error (ECE, lower is better)
            value: null
            verified: false
---

# Model card — Sprout

> Sprout is a grounded, evaluated, multilingual (EN/ES) houseplant-care assistant. It answers
> only from a versioned, cited horticulture corpus, never certifies a plant "safe," abstains
> below a confidence threshold, and ships with a public evaluation harness as its headline
> artifact. This card documents the *system as deployed* — a retrieval pipeline with a swappable
> generator — not a trained model. **Sprout trains nothing.**

- **Author:** Chelsea Kelly-Reif
- **Project status:** reference implementation · independent personal open-source project ·
  Apache-2.0 · unaffiliated with any employer or client; contains no proprietary or client material
- **Version:** `sprout` 0.1.0
- **Card date:** 2026-06-22
- **Repository layout:** package at `src/sprout/`; eval harness at `src/sprout/eval/`
- **License:** Apache-2.0 (code); bundled corpus and eval datasets are **synthetic and CC0-1.0**

This card follows the Hugging Face model-card format and the portfolio
`AI-EVALUATION-STANDARD` §4 (model/data cards as
committed, release-regenerated artifacts). It references the cross-cutting standards rather than
restating them.

---

## Intended use

Sprout answers everyday household plant-care questions — diagnosis ("why are my Monstera's leaves
yellowing?"), routine care ("how often should I water in winter?"), and toxicity lookups ("is
Pothos toxic to cats?") — and grounds every substantive sentence in a retrieved, dated, licensed
corpus passage with an inline citation, or refuses and points elsewhere.

**Primary uses**

- Interactive Q&A over the bundled (or an adopter's substituted) horticulture corpus, via the
  `sprout` CLI, the JSON/SSE API, or the accessible chat UI.
- A worked **reference implementation** of grounded RAG with structural groundedness, a
  never-certify-"safe" safety guard, calibrated abstention, and EN/ES parity.
- A **corpus-agnostic evaluation harness**: the eval runner and suites measure groundedness,
  safety, calibration, refusal, and multilingual parity against any care corpus that follows the
  same manifest contract.

**Intended users**: developers and reviewers studying responsible-AI RAG patterns; hobbyist plant
owners using the demo; teams adapting the harness to their own grounded-QA domain.

**Out-of-the-box behavior**: the offline deterministic stack is the default. No cloud account, API
key, or network is required to ingest the corpus, answer questions, or regenerate the eval report.

## Out-of-scope use

Sprout is **not** any of the following, and these uses are explicitly unsupported:

- **Veterinary, medical, or emergency advice.** Sprout does not diagnose or treat animal or human
  poisoning. Toxicity questions are routed to a vet / poison-control line; the assistant reports
  what a cited source says and never substitutes for a professional.
- **A safety certifier.** Sprout will never tell you a plant *is* safe, non-toxic, or fine to chew.
  The never-certify-"safe" guard (below) is structural, not a guideline.
- **A general-knowledge chatbot.** Out-of-scope questions (cooking, legal, anything the corpus does
  not cover) are refused by the retrieval threshold gate, not answered from model priors.
- **A source of facts beyond the cited corpus.** Sprout cannot answer about a species, pest, or
  product absent from the loaded corpus; it refuses rather than extrapolating.
- **An authority for high-stakes or commercial horticulture** (agricultural dosing, pesticide
  application rates, regulated-substance guidance). The corpus is general household plant care.
- **A multilingual service beyond EN/ES.** Only English and Spanish are supported and parity-tested;
  other languages are out of scope until added as a localization module.
- **A personalization service in v1.** The Family Greenhouse household-data path (per-user plants,
  care history) is deferred to a later phase and is not part of this release.

## The two stacks: offline deterministic default vs. the Claude-on-Bedrock seam

Sprout's pipeline is fixed; only the *generator* (and optionally the *embedder*) is swappable behind
a config switch (`config/sprout.yaml`). The pipeline contract is the same in both modes:
`guards(input) → retrieve (hybrid, threshold-gated) → generate → citation guard → never-certify-safe
guard → confidence/abstention → answer-or-refuse`.

### Offline deterministic stack (default — `provider: deterministic`)

- **Embedding:** `HashingEmbedding` — a signed SHA-256 token-hashing bag-of-tokens projection,
  L2-normalised, 512-d. SHA-256 is used purely as a stable token→dimension map (a non-cryptographic
  use). The same text always yields a byte-identical vector, so the index is reproducible in CI. It
  is a retrieval *baseline*, not a semantic model.
- **Retrieval:** pure-Python **Okapi BM25** fused with dense cosine via **Reciprocal Rank Fusion**,
  a conservative species/topic filter, and a single `min_score` gate that decides answer-vs-refuse.
- **Generator:** `ExtractiveGenerator` — selects the most query-relevant sentences **verbatim** from
  retrieved chunks, each tagged with its chunk id. There is no text path by which it can fabricate.
- **Why it matters:** groundedness and citation coverage are **100% by construction** — the
  generator can only copy retrieved text, and the citation guard re-verifies it. The whole project,
  including the eval, runs with **no network and no cloud account**, for free.

### Claude-on-Bedrock production seam (`provider: bedrock`) and native Anthropic (`provider: anthropic`)

- **Answer model:** Claude **Haiku** — `anthropic.claude-haiku-4-5-20251001-v1:0` on Bedrock, or
  `claude-haiku-4-5-20251001` via the native Anthropic Messages API. Temperature 0.0; the prompt
  constrains the model to quote the numbered sources and never certify a plant "safe."
- **Embedding (Bedrock):** Amazon Titan `amazon.titan-embed-text-v2:0`.
- **Same failure posture as offline.** Any exception, timeout, or malformed/empty model response
  logs and returns an *empty* candidate list, so a provider outage degrades to a refusal — never an
  ungrounded answer. A circuit breaker / fail-closed parse wraps the client.
- **Still grounded.** Model-generated sentences are attributed to their best-overlap retrieved chunk
  and then **independently re-verified by the same citation guard**, so a hallucinated or
  mis-attributed sentence is *dropped*, not shown. Groundedness does not depend on the model's good
  behavior; it depends on the guard.
- **Cost & dependencies:** Claude answer calls are shared-table priced and fail closed before the
  provider call when unpriced or above the configured per-answer ceiling. Titan uses the exact
  shared AWS catalog rate for the configured Bedrock region and rejects missing/unsupported
  regions rather than borrowing a rate. `boto3` and `httpx` are lazily imported and their clients
  cached only when selected, so a plain install runs offline end to end. These paths require live
  credentials and are tested via injected clients.

> **The generator is interchangeable; the guards are not.** Swapping in Claude raises fluency and
> recall but cannot weaken groundedness, the never-certify-safe rule, or abstention — those are
> enforced downstream of generation. Per the README, the citation guard, the never-certify-safe
> guard, the abstention thresholds, and the fail-closed eval loader change **only behind an ADR +
> CODEOWNERS review**.

## Never-certify-"safe" and calibrated abstention

These are the two behaviors that make Sprout honest about its limits.

### Never certify "safe"

- A deny-list output guard (`guards.asserts_safety`) drops **any rendered sentence** that certifies
  a plant "safe" / "non-toxic" in **either language**, after generation, regardless of which
  generator produced it.
- Toxicity/ingestion questions are detected on input (`is_safety_query`) and carry a **routing
  directive to a vet / poison-control line** on both the answer *and* the refusal paths.
- Sprout reports *what a cited toxicity reference says* and, when the corpus is silent, says so —
  it does not infer safety from absence of evidence.
- The routing directive is a **standardized safety message** shown on every toxicity answer *and*
  refusal, in EN and ES (`PromptConfig.safety_directive_for`), with three parts in urgency order:
  (1) an **urgency-forward routing line** — if a pet or child may have eaten part of a plant, treat
  it as urgent and call now, rather than leading with reassurance; (2) a **"not listed as toxic is
  not safe" caveat** — any plant material can cause vomiting or GI upset and individual animals
  vary, so a source's silence is not a guarantee against harm; and (3) a **standardized escalation
  card** naming the public authorities — the **ASPCA Animal Poison Control Center** and the **Pet
  Poison Helpline** (with their published numbers and official pages) — plus the three facts a
  clinician needs: the plant, how much was eaten, and when. None of this asserts safety, and the
  caveat is source-attributed so the never-certify-"safe" guard leaves it intact.

### Calibrated abstention

- Confidence is a transparent function of **retrieval evidence** — the best passage's cosine score,
  nudged by its margin over the runner-up, through a fixed logistic. It deliberately does **not**
  depend on answer fluency, which would reward confident nonsense.
- Below `abstain_threshold` (default **0.25**)<!-- claim:model-card-abstain-threshold --> the assistant **refuses rather than guesses**. Below
  `low_confidence_threshold` (default **0.50**)<!-- claim:model-card-low-confidence-threshold --> it answers but flags the answer for human review.
  (Per [ADR-0012](../adr/0012-recalibrated-abstention-thresholds-supersedes-0005.md), which
  supersedes ADR-0005; the earlier 0.45/0.62 figures never matched the shipped, calibrated
  values and are corrected here as of 2026-07-05.)
- The harness checks that these stated confidences track correctness via a **reliability diagram**
  and **Expected Calibration Error (ECE)** in the calibration suite — a confidence Sprout cannot
  back up is a test failure, not a footnote.

## Training data

**None.** Sprout performs **no training and no fine-tuning.** It is a retrieval system over a
corpus, plus a swappable, pinned, third-party generator used only at inference.

- **Knowledge source:** the bundled `corpus/` — cleaned, chunked passages carrying per-document
  `source`, `license`, `fetch_date`, and `language` in `corpus/manifest.yaml`. The bundled corpus
  and all eval datasets are **synthetic and CC0-1.0** — authored for this project, containing no
  scraped or proprietary text — so the demo is fully redistributable. See
  [`docs/cards/data-card-corpus.md`](data-card-corpus.md) for the datasheet.
- **No user-query persistence** in the demo; secrets come from the environment, never the corpus or
  config.
- **Adopters substitute their own corpus** via `config/sprout.yaml`; doing so changes the knowledge
  source but not the pipeline, the guards, or this card's structural claims.

## Evaluation

The eval harness is the headline artifact. The committed, release-regenerated report lives at
[`docs/audits/eval-report.md`](../audits/eval-report.md) (with `.html`, `.json`, JUnit, and SARIF
companions). Runs are **content-hashed and byte-identical for identical inputs**; the run identity
changes if the dataset, judge model, prompt version, temperature, or thresholds change.

Scoring blends **deterministic checks** (citation resolves to the corpus; forbidden "safe"
certifications absent; "as of" date shown; language matches) with an **LLM-as-judge** for
groundedness/helpfulness. **The judge model is deliberately different from the answer model:**

- **Answer model:** Claude **Haiku** (cloud seam) or the offline `ExtractiveGenerator` (default).
- **Judge model:** Claude **Sonnet** — `claude-sonnet-4-6` — at temperature 0.0, with a committed,
  versioned judge prompt (`PROMPT_VERSION`). Malformed judge output **raises** (fail-closed).

A **10% human-agreement sample** is reported with raw agreement and **Cohen's κ** (portfolio gate:
κ ≥ 0.60); the judge is only trusted insofar as it tracks human labels.

### The five suites

| Suite | What it asks |
|---|---|
| **groundedness** | Is every claim entailed by the cited passage? (flags *contradicted* vs *unsupported*) |
| **safety** | For toxicity/ingestion questions: cite a toxicity reference, never certify "safe," route to vet/poison-control |
| **calibration** | Do stated confidences track correctness? (reliability diagram, ECE; abstains below threshold) |
| **refusal** | Out-of-scope, "just tell me it's fine," and prompt-injection embedded in questions |
| **multilingual** | Spanish answers preserve the facts and citations of their English mirror |

Target **120+ YAML cases**, each carrying id, question, expected behavior
(answer / partial / refuse-and-redirect), required citation or fact, language tag, and rationale.
Everything is **fail-closed**: a dataset-hash mismatch, a malformed case, an empty suite, or a
malformed judge response fails the run rather than passing quietly (a zero-item suite can never
report PASS). Each suite carries a written `MetricDefinition` (name, definition, threshold,
direction) reproduced verbatim in the report — no opaque scores.

The numeric `model-index` `value`s above are illustrative of the **offline deterministic stack's
by-construction guarantees** (groundedness, citation coverage = 1.0; forbidden certifications =
0.0). Per-run scores — including ECE and the EN/ES parity gap, which depend on the judge and the
case set — are authoritative in the committed report, not here.

## Limitations and disclaimers

### A passing evaluation is NOT a safety guarantee. This is NOT veterinary advice.

**Read this section before relying on any answer.**

- **A green eval is evidence, not a warranty.** The suites measure groundedness, the absence of
  "safe" certifications, calibration, refusal behavior, and EN/ES parity *on a finite case set
  against a specific corpus and judge*. Passing them means Sprout behaved correctly on those cases.
  It does **not** prove an answer is correct, complete, current, or safe for your specific plant,
  pet, child, or situation.
- **Sprout is not veterinary, medical, or emergency advice and must not be used as such.** If an
  animal or person may have ingested a plant, contact a veterinarian or poison-control line
  immediately. Sprout deliberately refuses to certify safety precisely because that judgment is not
  its to make.
- **Grounded ≠ true.** The citation guard guarantees every rendered sentence is *supported by a
  retrieved passage*. It does **not** guarantee the passage is *correct* — plant-care lore is
  contradictory and seasonal, and the bundled corpus is **synthetic** (authored for testing), so it
  must not be treated as horticultural ground truth. With a real corpus, answers are only as good,
  current, and unbiased as that corpus.
- **Corpus-bounded by design.** Anything outside the loaded corpus is refused, including newer
  species, products, or guidance. Coverage gaps look like refusals, not best guesses — which is the
  intended failure mode, but a limitation nonetheless.
- **"Not listed as toxic" is not "safe," and a cited answer can be true-but-incomplete.** A source
  that does not list a plant as toxic is not a clean bill of health: any plant material can cause
  vomiting or GI upset and individual animals vary. Because generation is *extractive*, a rendered
  sentence is faithful to its passage yet that passage may legitimately *omit* a toxin or a caveat —
  a correct retrieval that happens to be incomplete is the failure that matters most here. Sprout
  mitigates this by never certifying safety and by attaching the non-toxic caveat and the
  vet/poison-control escalation card to every toxicity answer and refusal, but the residual risk is
  real: treat reassuring-sounding silence as unverified and call a professional.
- **Photo-ID can be confidently wrong; reminders are local-only.** When the optional photo path is
  used, a visual match is a *selector, not a fact* — it never renders as a citation and the care
  answer still flows through the grounded pipeline, but a confident *wrong* identification of an
  in-corpus species can yield a correct, cited answer about the *wrong* plant (mitigated by the
  confidence gate and the "a visual match, not a cited fact" label; see ADR-0010). Care reminders
  are stored only on the user's device (`var/reminders.json`): no sync, no push delivery (ADR-0011).
- **Offline retrieval is a baseline.** The default `HashingEmbedding` is lexical, not semantic;
  paraphrased or synonym-heavy questions may under-retrieve and refuse where a semantic embedder
  (Titan/Bedrock) would answer. This trades recall for zero-dependency reproducibility.
- **Calibration is empirical and corpus-specific.** Confidence is derived from retrieval evidence
  and tuned to the bundled data; on a different corpus the thresholds should be re-calibrated and
  the reliability diagram re-checked.
- **Cloud-mode residual risk.** The offline default cannot fabricate (it copies source sentences
  verbatim), so its grounding/never-certify-safe guarantees hold by construction. With a Claude
  generator the model composes free text, and the citation guard becomes the sole structural defense.
  An adversarial review hardened that path: the guard now rejects negation-polarity inversion
  ("X is not toxic" attributed to a "toxic" chunk) and content-free fragments, and the
  never-certify-safe guard is negation-aware (catching "no risk"/"pet-safe") while still permitting
  honest *source-attributed* statements ("the cited reference does not list X as toxic"). One
  residual remains: lexical (bag-of-token) verification can still admit a same-plant *recombination*
  (e.g. swapping which attribute applies), bounded in practice because retrieval is species-scoped to
  one plant. A production deployment should add an NLI-grade entailment verifier on the cloud path;
  the guards are the safety boundary, not the model's instruction-following.
- **Prompt-injection is handled structurally, not perfectly.** Injection attempts are *labeled* for
  the refusal suite and logs; the actual defense is that an injected instruction cannot produce a
  sentence entailed by a retrieved chunk. Novel attacks should be filed as eval cases.

## Fairness and EN/ES parity

Sprout's fairness commitment is **language parity**: a Spanish-speaking user must get the same
facts, the same citations, and the same safety behavior as an English-speaking user.

- **Parity is a gate, not an aspiration.** The multilingual suite checks that each Spanish answer
  preserves the facts and citations of its English mirror, and the AI-evaluation gate enforces a
  pass-rate parity of **|EN − ES| ≤ 5 pp** (per
  `AI-EVALUATION-STANDARD`); a wider gap fails CI.
  Per-segment results are **disaggregated by language** in the report — no language is allowed to
  hide inside a macro average.
- **Same guards in both languages.** The never-certify-"safe" deny-list, the safety-query detector,
  and the vet/poison-control routing all operate in EN and ES; a "safe" certification is blocked in
  Spanish exactly as in English.
- **Localization is modular.** All user-facing strings live in per-language bundles; adding a
  language is a localization module plus its parity cases — but until a language has both, it is
  out of scope rather than silently degraded.
- **Known parity limit.** Parity is measured on the synthetic corpus's EN/ES mirror; on an adopter's
  corpus, parity is only as good as the translation fidelity of *that* corpus, and must be
  re-measured.

## Environmental footprint

**No training or fine-tuning is performed**, so there is no training-time compute or emissions to
report. The default stack runs offline on CPU at negligible energy cost. The optional Claude seam
incurs ordinary third-party inference cost bounded by the per-answer preflight ceiling; per-token
inference emissions are governed by the provider, not this project. Per the AI-evaluation
standard, the environmental-footprint metric is **N/A-with-reason for this API-only / no-train repo**.

## How to cite / reproduce

```bash
git clone https://github.com/ChelseaKR/sprout.git && cd sprout
uv sync
uv run sprout ingest               # build the index from the bundled CC0 corpus
uv run sprout ask "Why are my Monstera's leaves yellowing?"
make eval                          # regenerate docs/audits/eval-report.* fully offline
make verify                        # the full CI gate set: lint · type · test >=90% · security · a11y · eval
```

The model card, data card, and eval report are **regenerated and re-committed on each release** —
the same audit-as-artifact discipline applied across the portfolio.

## Related documents

- Front door and standards table: [`README.md`](../../README.md)
- Architecture: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) · Threat model:
  [`docs/THREAT-MODEL.md`](../THREAT-MODEL.md)
- Eval report (authoritative scores): [`docs/audits/eval-report.md`](../audits/eval-report.md)
- Data card (corpus datasheet): [`docs/cards/data-card-corpus.md`](data-card-corpus.md)
- Cross-cutting standards: `STANDARDS/AI-EVALUATION-STANDARD.md`,
  `STANDARDS/RESPONSIBLE-TECH-FRAMEWORK.md`
