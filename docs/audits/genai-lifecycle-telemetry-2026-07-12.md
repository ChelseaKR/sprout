# GenAI lifecycle telemetry audit — 2026-07-12

## Result

The optional cloud paths now emit privacy-safe lifecycle records for every real model
operation. The shared portfolio runtime is vendored byte-for-byte at
`src/sprout/_vendor/genai_telemetry/` from immutable STANDARDS commit
`e8150c82fc35267f022af46ac71fe5a851e2d042`; `.standards-version` records that boundary.
`src/sprout/genai_telemetry.py` is only Sprout's record/sink wrapper. Provider modules own
neither semantic-convention spellings nor prices.

| Model boundary | System / operation | Recorded on success and failure |
|---|---|---|
| Native Anthropic answer generator | `anthropic` / `chat` | yes |
| Claude answer generator through Bedrock | `aws.bedrock` / `chat` | yes |
| Titan embedding adapter through Bedrock | `aws.bedrock` / `embeddings` | yes |
| Native Anthropic LLM judge | `anthropic` / `chat` | yes |

Each success record includes request and response model (when supplied), finish reason,
operation duration, and the input/output/cache token fields supplied by that provider. Claude
answer/judge records also carry an estimated USD cost from the shared pinned model-family price
table. Provider-separated fresh, cache-creation, and cache-read counts are summed into
canonical total input, then split into their three price buckets, so neither cache-hit rate nor
Claude cost omits or double-counts them.

Titan V2 uses the shared AWS catalog row rather than a Sprout-local estimate. Bedrock supplies
`inputTextTokenCount`, which is recorded with `generation.region` on the shared `Usage`; the
catalog selects the exact in-region rate and retains source/SKU metadata. Missing or unsupported
regions return `None`, and the normal provider factory rejects that unpriced activation rather
than borrowing another region's rate. Titan is input-only, so non-zero output/cache usage is also
unpriceable. Tests lock the configured `us-west-2` estimate at $0.02 per million input tokens and
the missing/unknown-region failure behavior.

For answer generation, `Assistant` invokes `estimated_cost_usd` after retrieval and before
`generate`; unknown/unpriced, invalid, or unavailable estimates fail closed, and estimates over
`generation.max_cost_usd` refuse without contacting the provider. Estimates are never presented
as billing data. Non-streaming adapters correctly omit `time_to_first_chunk`.

Prompts, completions, retrieved passages, legal or personal data, and user identifiers are
not fields on the telemetry record. Content capture is fixed to `false`. The default sink
emits compact JSON lines to stderr; a deployment can inject a native OTel exporter without
changing a provider call site. Export failures are isolated from the model operation.

## Verification

`tests/test_genai_telemetry.py` checks the pinned vendor boundary, forbids convention-name
literals outside the vendor package, validates all three input buckets plus Claude and region-aware
Titan pricing, and proves the no-content invariant. It exercises success,
invocation failure, and lazy-client-construction failure telemetry plus exporter-failure
isolation. End-to-end `Assistant` tests prove unpriced/unavailable/over-budget estimates prevent
the generator from being invoked, while the trace path invokes an allowed generator only once.
Provider-factory tests lock Titan's blocked activation and the Anthropic-vs-Bedrock model-id
validation. Ruff and strict mypy cover Sprout's wrapper and provider wiring; vendored runtime
source is lint/type/coverage-excluded and verified at its immutable upstream boundary.

## Lifecycle loop

- Offline development evaluation remains the merge-blocking `make eval` suite plus the
  calibrated deterministic judge.
- Corpus drift now has a weekly scheduled `make freshness` gate in
  `.github/workflows/corpus-freshness.yml`; its SLA values remain configuration-owned.
- A production trace-to-weekly-judge loop is **not activated because the cloud API is not
  deployed and has no live trace store or provisioned model credential**. This is an external
  launch gate, not an unimplemented local code path. Before cloud activation, provision the
  exporter/trace store, run `sprout calibrate --judge llm --gate`, and batch-score 100% of the
  low-volume traces weekly. Every failure must become a committed benchmark or a documented
  false positive before the next release.
