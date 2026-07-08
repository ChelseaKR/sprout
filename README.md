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

**Live reference:** [sprout.chelseakr.com](https://sprout.chelseakr.com) — the
deterministic cited-answer pipeline runs entirely in the browser; questions are not
sent, saved, or logged.

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
- **Provides local reminder contracts** for CLI/API adopters, stored only on the running
  device — offline, opt-in, nothing uploaded. Reminders are intentionally absent from the
  public web reference because household tasks belong in Family Greenhouse; see
  [ADR-0011](docs/adr/0011-local-first-reminder-scheduler.md) and
  [ADR-0015](docs/adr/0015-web-is-a-reference-and-assurance-surface.md). **Exports them as
  a standards-based `.ics` calendar** (`sprout remind export --ics`) so any calendar app
  can notify you — one-directional, no sync/push channel added, the local JSON file stays
  the single source of truth.

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
git clone https://github.com/ChelseaKR/sprout.git
cd sprout
uv sync --extra serve
uv run sprout ingest
uv run sprout ask "Why are my Monstera's leaves yellowing?"
```

The project has not published its first package release yet. After the initial release,
`pipx install sprout` will be the supported packaged installation path. From a source checkout:

```bash
uv run sprout ingest                    # build the index from the bundled corpus
uv run sprout ask "Why are my Monstera's leaves yellowing?"
uv run sprout ask "¿Es tóxico el potho para los gatos?"   # Spanish, with EN/ES parity
uv run sprout identify plant.jpg -q "is this toxic to my cat?"   # photo → cited care answer
uv run sprout remind add pothos --kind water --every 7    # local, offline reminder
uv run sprout remind export --ics --out reminders.ics     # standards-based calendar file, any app
uv run sprout serve                     # stateless reference UI + JSON/SSE API at :8000
pipx install sprout              # or: uv sync && uv run sprout ...
sprout ingest                    # build the index from the bundled corpus
sprout ask "Why are my Monstera's leaves yellowing?"
sprout ask "¿Es tóxico el potho para los gatos?"   # Spanish, with EN/ES parity
sprout ask "How much water does my Pothos need?" --season winter --light "north window"
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

Agent-facing build instructions live in [`CLAUDE.md`](./CLAUDE.md) (the spec, plus the
agent contract at its end).

## Standards conformance

The table below names the engineering standards applied to Sprout; their concrete controls,
targets, and evidence are recorded in this public repository. Per-repo *values* live in
[`docs/ROADMAP.md`](docs/ROADMAP.md) and
[`docs/RESPONSIBLE-TECH-AUDITS.md`](docs/RESPONSIBLE-TECH-AUDITS.md).

| Standard | Applies | This repo's posture |
|---|---|---|
| Quality & Metrics (ISO 25010 / DORA) | ✅ | Metrics ledger in ROADMAP; `make verify` uses the same tools/thresholds as the CI-required checks |
| Code Quality | ✅ | `ruff` + `mypy --strict`; branch coverage ≥90% (published-library floor); src layout |
| Security & Supply-Chain | ✅ | ASVS L1 offline mode; scoped ASVS L2 review for the authenticated Family Greenhouse boundary; pip-audit + Semgrep blocking; gitleaks; CodeQL + zizmor; SHA-pinned actions; release SBOM |
| CI/CD | ✅ | Single `ci-gate` required check; least-privilege tokens; `make verify` mirrors CI's tools/thresholds |
| Release & Versioning | ✅ | SemVer; Keep-a-Changelog; PyPI Trusted Publishing (OIDC) wired; **no tag has ever been cut yet** — signed tags apply starting the first real release (corrected 2026-07-05; see `CHANGELOG.md`) |
| Accessibility | ✅ | WCAG 2.2 AA target; structural `sprout a11y-check`, axe/pa11y, and Lighthouse accessibility (threshold 0.95) are all **merge-blocking** (wired 2026-07-08); transcript view; ACR (VPAT 2.5 Rev 508) |
| Observability | ✅ | Tier C (offline CLI: structured JSON logs, PII-free, integration-tested); Tier A for the optional serverless API |
| Internationalization | ✅ | EN/ES key + placeholder parity; AI-eval enforces \|EN−ES\| ≤ 5pp pass-rate parity |
| AI Evaluation | ✅ | RAG groundedness/safety/multilingual gates green; refusal gated at 0.90 (offline floor, portfolio target 0.95, gap tracked); judge-calibration (deterministic judge, 66 probes) gated at agreement 0.955 / κ 0.906 (probe set expanded + antonym-polarity guard, 2026-07-08 — see `docs/ROADMAP.md`); judge≠answer model; model/data cards |
| Documentation | ✅ | Full `docs/` set; ADRs; dated, regenerated audit artifacts |
| Responsible-Tech Framework | ✅ | `docs/RESPONSIBLE-TECH-AUDITS.md` §A–F + AI-EVAL + I18N; every audit applies (added to this table 2026-07-05 — was silently omitted) |

No standard is `N/A`. Family Greenhouse Phase A personalization is implemented behind a feature
flag with an ASVS L2 review; notification and confirmed-write phases remain deferred. Every row above with a
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
web/dist/          framework-free WCAG 2.2 reference and assurance surface
docs/              ARCHITECTURE · THREAT-MODEL · ACCESSIBILITY · ROADMAP · audits/ · cards/ · adr/
```

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Bundled corpus and eval
datasets are synthetic and CC0-1.0. This is not veterinary or medical advice.
