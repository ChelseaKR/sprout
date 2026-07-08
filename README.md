# Sprout 🌱 — a grounded, evaluated plant-care assistant

> A retrieval-augmented houseplant-care assistant that answers only from a versioned,
> cited horticulture corpus — and a rigorous public **evaluation harness** that measures
> groundedness, toxicity safety, calibrated uncertainty, and English/Spanish parity.
> The eval report is the headline artifact; the assistant exists so the harness has
> something honest to measure.

**Status:** `In build` · reference implementation · independent personal open-source
project · Apache-2.0 · unaffiliated with any employer or client; contains no proprietary
or client material. The bundled corpus and eval data are **synthetic and CC0-1.0**.

[![CI](https://github.com/ChelseaKR/sprout/actions/workflows/ci.yml/badge.svg)](https://github.com/ChelseaKR/sprout/actions/workflows/ci.yml)
&nbsp;Python ≥3.12 · offline by default · WCAG 2.2 AA

---

## What it does

- Answers a plant-care question (*"why are my Monstera's leaves yellowing?"*) with an
  **inline citation** to the governing passage and its fetch date — or says plainly that
  the corpus does not cover it and points elsewhere.
- Treats **toxicity** as a safety property: a *"is this safe for my cat?"* question is
  answered only from a cited toxicity reference, the assistant **never asserts "safe,"**
  and it routes high-stakes ingestion questions to a vet / poison-control line.
- Expresses **calibrated uncertainty**: below a confidence threshold it abstains rather
  than guesses.
- Works in **English and Spanish** with enforced parity.
- **Identifies a plant from a photo**, then answers from the *same* cited corpus. The
  visual match only *selects* the species (it's labelled "a visual match, not a cited
  fact" and never rendered as one); the care answer still flows through the grounded,
  guarded pipeline. Offline by default, with a graceful "type the plant's name" fallback
  and an allowlisted Pl@ntNet provider behind a config switch — see
  [ADR-0010](docs/adr/0010-photo-plant-id-as-selector-not-fact-source.md).
- **Sets local care reminders** (watering/fertilizing) tied to a plant and answer, stored
  only on your device — offline, opt-in, nothing uploaded — see
  [ADR-0011](docs/adr/0011-local-first-reminder-scheduler.md).

### The four hard rules (enforced, not aspirational)

1. **No claim without a citation.** Generation is *extractive* — every rendered sentence
   is copied verbatim from a retrieved passage and re-verified by an independent citation
   guard; an ungrounded sentence cannot render. Groundedness is 100% *by construction*.
2. **Never assert safety.** A deny-list output guard blocks "safe"/"non-toxic"
   certifications in both languages and routes ingestion questions to poison-control.
3. **Corpus is versioned and dated.** Every passage carries source, license, and fetch
   date; the UI shows "based on references as of &lt;date&gt;."
4. **Offline by default.** A deterministic embedding + extractive generator make the whole
   project — including the eval — run with no network and no cloud account. A
   Claude-on-Bedrock generator is the production seam behind a config switch.

---

## Quickstart (offline, no cloud account)

```bash
pipx install sprout              # or: uv sync && uv run sprout ...
sprout ingest                    # build the index from the bundled corpus
sprout ask "Why are my Monstera's leaves yellowing?"
sprout ask "¿Es tóxico el potho para los gatos?"   # Spanish, with EN/ES parity
sprout identify plant.jpg -q "is this toxic to my cat?"   # photo → cited care answer (offline → fallback)
sprout remind add pothos --kind water --every 7    # local, offline reminder
sprout serve                     # accessible chat UI + JSON/SSE API at :8000
make eval                        # regenerate the committed eval report, fully offline
```

`make demo` reproduces a scripted session end to end.

## The eval harness (the actual product)

120+ YAML cases across five suites, scored by **deterministic checks** blended with an
**LLM-as-judge** (judge model ≠ answer model), reported in `docs/audits/eval-report.{md,html,json}`
plus JUnit + SARIF. Runs are content-hashed and **byte-identical for identical inputs**.

| Suite | Asks |
|---|---|
| **groundedness** | Is every claim entailed by the cited passage? (contradicted vs unsupported) |
| **safety** | For toxicity questions: cite a toxicity ref, never certify "safe," route to vet/poison-control |
| **calibration** | Do stated confidences track correctness? (reliability diagram, ECE; abstain below threshold) |
| **refusal** | Out-of-scope, "just tell me it's fine," and prompt-injection embedded in questions |
| **multilingual** | Spanish answers preserve the facts and citations of their English mirror |

Everything is **fail-closed**: a dataset hash mismatch, a malformed case, an empty suite,
or a malformed judge response fails the run rather than passing quietly.

---

## For Claude Code

- **Build from:** `CLAUDE.md` (the spec) + `~/portfolio/STANDARDS/` (the cross-cutting rigor)
  + `docs/ROADMAP.md` (phased plan + per-repo metric values).
- **Entry points:** the `sprout` CLI (`src/sprout/cli.py`) and the eval harness (`src/sprout/eval/`).
- **Hard guardrails — change only behind an ADR + CODEOWNERS review:** the citation guard
  and never-certify-safe guard (`src/sprout/guards.py`), the abstention thresholds
  (`src/sprout/confidence.py`), and the fail-closed eval loader (`src/sprout/eval/dataset.py`).
- **The one command that proves it:** `make verify` reproduces the full CI gate set locally
  (lint · type · test ≥90% · security · a11y · eval). A phase is not "done" until it is green.
- **Definition of done:** `pipx install sprout`, ask a question offline, get a cited answer
  or an honest refusal, run `make eval` to regenerate the committed report with no cloud
  account, and read a model card that states the limits plainly — with every gate green.

## Standards conformance

This repo references the portfolio [`STANDARDS/`](../STANDARDS/README.md) rather than
restating them. Per-repo *values* live in [`docs/ROADMAP.md`](docs/ROADMAP.md) and
[`docs/RESPONSIBLE-TECH-AUDITS.md`](docs/RESPONSIBLE-TECH-AUDITS.md).

| Standard | Applies | This repo's posture |
|---|---|---|
| Quality & Metrics (ISO 25010 / DORA) | ✅ | Metrics ledger in ROADMAP; `make verify` uses the same tools/thresholds as the CI-required checks |
| Code Quality | ✅ | `ruff` + `mypy --strict`; branch coverage ≥90% (published-library floor); src layout |
| Security & Supply Chain | ✅ | ASVS L1 (offline mode); pip-audit + Semgrep blocking (CI and `make verify`); gitleaks in CI; CodeQL + zizmor workflow-SAST; SHA-pinned actions; SBOM generated + uploaded on release |
| CI/CD | ✅ | Single `ci-gate` required check; least-privilege tokens; `make verify` mirrors CI's tools/thresholds |
| Release & Versioning | ✅ | SemVer; Keep-a-Changelog; PyPI Trusted Publishing (OIDC) wired; **no tag has ever been cut yet** — signed tags apply starting the first real release (corrected 2026-07-05; see `CHANGELOG.md`) |
| Accessibility | ✅ | WCAG 2.2 AA target; structural `sprout a11y-check` gate is merge-blocking; axe/pa11y run today as **advisory only**, Lighthouse **not yet wired** (gap tracked, corrected 2026-07-05); transcript view; ACR (VPAT 2.5 Rev 508) |
| Observability | ✅ | Tier C (offline CLI: structured JSON logs, PII-free, integration-tested); Tier A for the optional serverless API |
| Internationalization | ✅ | EN/ES key + placeholder parity; AI-eval enforces \|EN−ES\| ≤ 5pp pass-rate parity |
| AI Evaluation | ✅ | RAG groundedness/safety/multilingual gates green; refusal gated at 0.90 (offline floor, portfolio target 0.95, gap tracked); judge-calibration (deterministic judge, 66 probes) gated at agreement 0.909 / κ 0.807 (corrected 2026-07-08 — see `docs/ROADMAP.md`); judge≠answer model; model/data cards |
| Documentation | ✅ | Full `docs/` set; ADRs; dated, regenerated audit artifacts |
| Responsible-Tech Framework | ✅ | `docs/RESPONSIBLE-TECH-AUDITS.md` §A–F + AI-EVAL + I18N; no audit is N/A (added to this table 2026-07-05 — was silently omitted) |

No standard is `N/A`. Family Greenhouse personalization (household-data path, ASVS L2) is
**deferred to a later phase**; see [`docs/ROADMAP.md`](docs/ROADMAP.md). Every row above with a
"gap tracked" note is tracked in [`docs/ROADMAP.md`](docs/ROADMAP.md) and this repo's remediation
history, not silently carried — see the 2026-07-05 audit remediation for the full list.

## Architecture (one screen)

```
question ─▶ guards(input) ─▶ retrieve(hybrid BM25 + dense, threshold gate)
                                   │  weak match → refuse
                                   ▼
                       extractive generate (verbatim sentences, tagged to chunks)
                                   ▼
              guards(output): citation re-verify + never-certify-safe + provenance
                                   ▼
                      confidence/abstention ─▶ Answer (cited) | refusal
```

- **Offline default:** `HashingEmbedding` (deterministic) + pure-Python BM25 +
  `ExtractiveGenerator`; **production seam:** Bedrock Claude + Titan behind a config switch.
- **No database, no agentic loop, no reranker** without an ADR justifying an eval delta.
- See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/THREAT-MODEL.md`](docs/THREAT-MODEL.md),
  and the [model card](docs/cards/model-card.md).

## Repository layout

```
src/sprout/        ingest · retrieve · answer · guards · confidence · providers/ · server · cli
  eval/            the harness: dataset · suites · runner · judges · report · calibration
corpus/            manifest.yaml (dated, licensed) + processed passages (EN/ES, synthetic CC0)
eval/suites/       120+ YAML cases; baseline.json
web/dist/          framework-free WCAG 2.2 chat UI
docs/              ARCHITECTURE · THREAT-MODEL · ACCESSIBILITY · ROADMAP · audits/ · cards/ · adr/
```

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Bundled corpus and eval
datasets are synthetic and CC0-1.0. This is not veterinary or medical advice.
