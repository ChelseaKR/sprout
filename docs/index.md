# Sprout 🌱

A grounded, evaluated, multilingual houseplant-care assistant — and the public
**evaluation harness** that holds it to account. Sprout answers only from a versioned,
cited corpus, never certifies a plant "safe," abstains when uncertain, and works in
English and Spanish with enforced parity.

- **Architecture** — how the pipeline (guards → retrieve → extractive generate →
  citation guard → confidence) guarantees 100% groundedness by construction. See
  [Architecture](ARCHITECTURE.md) and the [Threat model](THREAT-MODEL.md).
- **The eval harness is the headline** — 8 suites<!-- claim:index-eval-suite-count --> (calibration, completeness, conversation, groundedness, multilingual, refusal, safety, toxicity-coverage)<!-- claim:index-eval-suite-names -->, deterministic checks blended
  with an LLM judge whose model differs from the answer model. See the [Evaluation report](audits/eval-report.md).
- **Responsible by construction** — see the [responsible-tech audits](RESPONSIBLE-TECH-AUDITS.md),
  the [model card](cards/model-card.md), the [data card](cards/data-card-corpus.md), and
  the [accessibility conformance report](accessibility/ACR.md).

Sprout is an independent, personal open-source project (Apache-2.0). The bundled corpus
is synthetic and CC0. **This is not veterinary or medical advice.**

Standards conformance and per-repo metric values live in the [Roadmap](ROADMAP.md); the
cross-cutting rigor is recorded through the public controls, targets, and evidence in this site.
