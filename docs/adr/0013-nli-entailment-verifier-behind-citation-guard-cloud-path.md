# 13. NLI-grade entailment verifier behind the citation guard (cloud path only)

- Status: Accepted
- Date: 2026-07-08
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

The model card (`docs/cards/model-card.md`) has stated since the cloud-path hardening pass:
"A production deployment should add an NLI-grade entailment verifier on the cloud path; the
guards are the safety boundary, not the model's instruction-following." No backlog item
implemented it (`docs/ideation/03-expansions.md`, EXP-04).

ADR-0003 established the citation guard as the load-bearing groundedness gate: a candidate
sentence survives only if it is verbatim-contained in, or lexically covered by, its cited
chunk, with a negation-polarity check added later to catch inversion attacks. That check is
bag-of-tokens: it measures *shared vocabulary*, not entailment. The residual risk it cannot
catch is a cloud generator's **same-plant sentence recombination** — swapping which
attribute applies between two chunks about the same species (e.g. attributing chunk A's
watering cadence to chunk B's light requirement) where each half, taken alone, still clears
the coverage threshold against *some* retrieved chunk. Retrieval's species/topic scoping
bounds how often this can happen (there is usually only one plant's chunks in play), but it
does not eliminate it, and FIX-05 (property-based fuzzing of the guard) is expected to
quantify a non-zero admit rate for exactly this pattern.

The offline `ExtractiveGenerator` cannot recombine — it copies sentences verbatim from a
single retrieved chunk, so this risk is specific to the cloud (Bedrock/Anthropic) path.

## Decision

Add an optional, cloud-path-only **NLI cross-encoder entailment verifier** as a second gate
*after* the existing lexical check, never a replacement for it.

1. **`guards.citation_guard`** takes an optional fourth argument, `entailment_verifier:
   EntailmentVerifier | None`. A candidate must still pass the existing lexical
   `_supported_by` check first; if a verifier is supplied, it must *also* judge the cited
   chunk as entailing the sentence (`entails(premise=chunk.text, hypothesis=sentence)`).
   `None` (the default, and the only value the offline path ever passes) reproduces prior
   behavior exactly — bit-identical, per the excellence bar.
2. **`verifiers.py`** defines the `EntailmentVerifier` Protocol and
   `NLIEntailmentVerifier` (threshold over an injected `score_fn`), plus
   `build_onnx_entailment_scorer` — the real loader, using CPU `onnxruntime` +
   `tokenizers` (no torch/transformers) against a Hugging Face Hub-hosted ONNX
   cross-encoder NLI checkpoint. The loader downloads the pinned file and verifies its
   SHA-256 against `generation.nli.model_sha256` before constructing an inference session,
   the same content-hash discipline `determinism.py` applies to the eval dataset and the
   judge config — a hash mismatch refuses to load rather than running unpinned weights.
3. **Config** (`GenerationConfig.support_verifier: "lexical" | "nli"`, default `"lexical"`;
   `GenerationConfig.nli: NLIVerifierConfig`) enforces, at load time, both risks the
   expansion doc flagged: `support_verifier: "nli"` is rejected when `provider ==
   "deterministic"` (the offline path is grounded by construction and gains nothing from
   this, and must stay zero-ML-dependency), and rejected when `nli.model_sha256` is unset
   (never load unpinned weights). Both are `ValueError` at config load — fail closed, not a
   silent no-op.
4. **`sprout[nli]` extra** (`onnxruntime`, `tokenizers`, `huggingface-hub`, `numpy`) keeps
   `onnxruntime`/`tokenizers` out of the base install, mirroring how `boto3` is scoped to
   `sprout[bedrock]`. `providers.build_entailment_verifier` lazily imports the loader only
   when `support_verifier: "nli"` is actually configured.
5. **Eval fingerprint.** `cli._target_name` appends the verifier's model id, revision,
   weight-hash prefix, and threshold (`verifiers.config_identity`, computed from config
   alone, no download) to the eval `target` string whenever `support_verifier: "nli"` is
   set, so a run with the verifier enabled is never conflated with one without it in
   `RunFingerprint.digest` or a baseline diff.
6. `guards.py` is a CODEOWNERS-guarded file; this ADR is the required review artifact for
   that change.

## Consequences

- **Positive.** Directly implements the model card's own stated production requirement;
  closes the specific residual risk it names. The verifier is strictly additive — it can
  only narrow what the lexical guard already accepts, never widen it (a chunk that fails
  lexical coverage is dropped before the verifier ever runs), so it cannot introduce a new
  way to admit an ungrounded sentence.
- **Positive.** The offline path is provably unaffected: `citation_guard`'s default
  parameter reproduces the old call signature's behavior, and `Assistant.from_store` only
  builds a non-`None` verifier when `support_verifier: "nli"` is configured, which config
  validation restricts to the cloud path.
- **Negative — new supply-chain artifact.** Model weights are fetched from the Hugging Face
  Hub at runtime rather than vendored; mitigated by hash pinning (fail-closed on mismatch)
  and scoping the dependency to an optional extra so it is never pulled into the default
  install's SBOM.
- **Negative — latency.** The cloud path already makes a network call to the generator; one
  more CPU-bound local inference call is a bounded, acceptable addition on a path that is
  not latency-budgeted the way the offline path is.
- **Known limit — EN/ES asymmetry.** Off-the-shelf NLI checkpoints are typically
  EN-strong/ES-weaker (per the expansion doc's own risk note). This ADR does **not** claim
  parity for the NLI gate; per-language false-reject rates must be measured (an eval-suite
  addition, tracked separately) before defaulting `support_verifier: "nli"` to on for
  Spanish-language cloud traffic. Until measured, treat `nli` as EN-validated only.
- **Neutral.** `entail_threshold` and `entailment_label_index` are config, changing them is
  an ADR-class change per the house rule (the same rule `support_overlap` is already under,
  ADR-0003).

## Excellence bar (from the expansion doc)

- Offline behavior bit-identical to before this change — covered by
  `test_citation_guard_default_unaffected_offline_path`.
- FIX-05's measured recombination admit-rate should drop materially on the cloud path once
  a real checkpoint is deployed and FIX-05's fuzz suite is run against it; that measurement
  is out of scope for this ADR (which lands the mechanism) and belongs to FIX-05's own
  report once both land.
