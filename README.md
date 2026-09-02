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

## Quickstart (offline, no cloud account)

```bash
git clone https://github.com/ChelseaKR/sprout.git
cd sprout
uv sync --extra serve
uv run sprout ingest
uv run sprout ask "Why are my Monstera's leaves yellowing?"
```

This path uses the bundled corpus and deterministic generator. It needs no API
key and makes no cloud call.

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

## Install

**Install from this source checkout. Do not `pip install sprout` or `pipx install sprout`** —
that installs somebody else's package. The name `sprout` on PyPI is taken by an unrelated
library ([Sprout 1.1.1](https://pypi.org/project/sprout/), Martijn Faassen / Infrae:
*"common Python library which contains reusable components"*), and nothing in this repository
has ever been published to PyPI. There is no release to install and no distribution name to
type; a reader who followed the old instruction here got a stranger's code.
[`docs/ROADMAP.md`](docs/ROADMAP.md) tracks the release work, which now includes choosing a
distribution name that is actually available.

Everything below runs offline from the checkout:

```bash
uv sync                                 # create the environment from the lockfile
uv run sprout ingest                    # build the index from the bundled corpus
uv run sprout ask "Why are my Monstera's leaves yellowing?"
uv run sprout ask "¿Es tóxico el potho para los gatos?"   # Spanish, with EN/ES parity
uv run sprout ask "How much water does my Pothos need?" --season winter --light "north window"
uv run sprout identify plant.jpg -q "is this toxic to my cat?"   # photo → cited care answer
uv run sprout remind add pothos --kind water --every 7    # local, offline reminder
uv run sprout remind export --ics --out reminders.ics     # standards-based calendar file, any app
uv run sprout serve                     # stateless reference UI + JSON/SSE API at :8000
make eval                               # regenerate the committed eval report, fully offline
```

`make demo` reproduces a scripted session end to end.

## What an answer actually looks like

Real output from the commands above — the deterministic offline pipeline over the bundled corpus,
on a machine with no API key and no network, so you get the same answers on your own checkout.
Long lines are hard-wrapped here for width; nothing else is edited, and
`tests/test_committed_artifacts_are_current.py::test_readme_transcripts_are_what_the_engine_says`
re-asks both questions through the engine so this section cannot quietly go stale.

<!-- transcript:pothos-toxicity -->
```console
$ uv run sprout ask "Is my pothos toxic to my cat?"
The cited reference lists Pothos (Epipremnum aureum) as toxic to cats and dogs; ingestion can
cause oral irritation, intense burning of the mouth and tongue, excessive drooling, vomiting,
and difficulty swallowing. If a cat or dog is suspected of chewing or swallowing Pothos,
contact a veterinarian or a poison-control hotline promptly. These effects in Pothos are
attributed to insoluble calcium oxalate crystals released when an animal chews the leaves or
stems. If a pet or child may have eaten part of this plant, treat it as urgent: contact your
veterinarian or a poison-control line now — don't wait for symptoms to appear. I can't certify
any plant safe. Even a plant a source does not list as toxic can still cause vomiting or mouth
and stomach irritation if eaten, and reactions vary by pet and person — a source's silence is
not a guarantee against harm. Who to call now: ASPCA Animal Poison Control Center,
888-426-4435 (https://www.aspca.org/pet-care/animal-poison-control), or Pet Poison Helpline,
855-764-7661 (https://www.petpoisonhelpline.com/). What to tell them: the plant (species if
known), how much was eaten, and when.

Sources:
  - Pothos care — pothos.md (as of 2026-05-01)

Based on references as of 2026-05-01.
[confidence: partially supported — verify (0.66) · Answers are drawn only from a dated, cited
plant-care corpus. This is not veterinary advice.]
```
<!-- /transcript:pothos-toxicity -->

All four hard rules are visible in that one answer: every sentence is copied verbatim from the
cited passage, the citation carries its fetch date, the only appearance of the word "safe" is the
refusal to certify it, and the ingestion question is routed to a vet and a poison-control line
with the numbers spelled out. The stated confidence is 0.66 — "partially supported — verify",
not a flat assertion.

And when the corpus does not cover the question, it says so instead of improvising:

<!-- transcript:venus-flytrap-abstain -->
```console
$ uv run sprout ask "How do I care for a Venus flytrap?"
I don't have a cited reference that covers this, so I can't answer from the corpus. For
plant-specific guidance, check a reputable source such as your local extension service or the
ASPCA toxic-plant list.
[confidence: insufficient evidence to answer (0.00) · Answers are drawn only from a dated,
cited plant-care corpus. This is not veterinary advice.]
```
<!-- /transcript:venus-flytrap-abstain -->


## The eval harness (the actual product)

**8 suites**<!-- claim:readme-eval-suite-count --> — calibration, completeness, conversation, groundedness, multilingual, refusal, safety, toxicity-coverage<!-- claim:readme-eval-suite-names --> — cover the harness end to end,
scored by **deterministic checks** blended with an **LLM-as-judge** (judge model ≠ answer model),
reported in `docs/audits/eval-report.{md,html,json}` plus JUnit + SARIF. Runs are content-hashed
and **byte-identical for identical inputs**.

| Suite | Asks |
|---|---|
| **groundedness** | Is every claim entailed by the cited passage? (contradicted vs unsupported) |
| **completeness** | For multi-fact cases, are all authored facts present, not just one? |
| **safety** | For toxicity questions: cite a toxicity ref, never certify "safe," route to vet/poison-control |
| **toxicity-coverage** | Does every ASPCA top-N pet-toxic plant in the corpus carry a toxicity section that routes to a vet/poison-control line? |
| **calibration** | Do stated confidences track correctness? (reliability diagram, ECE; abstain below threshold) |
| **refusal** | Out-of-scope, "just tell me it's fine," and prompt-injection embedded in questions |
| **multilingual** | Spanish answers preserve the facts and citations of their English mirror |
| **conversation** | Do follow-ups resolve species/topic from turn history, without a prior turn's species leaking into one it doesn't belong to? |

Everything is **fail-closed**: a dataset hash mismatch, a malformed case, an empty suite,
or a malformed judge response fails the run rather than passing quietly.

### The committed scoreboard

This is the run in [`docs/audits/eval-report.md`](docs/audits/eval-report.md) as of this commit —
regenerate it with `make eval`, offline, and get the same fingerprint. ↑ means higher is better,
↓ lower.

<!-- scoreboard:eval-report -->
| Suite | Verdict | Score | Threshold | n |
|---|---|---|---|---|
| `calibration` | ✅ PASS | **0.134** | 0.150 ↓ | 121 |
| `completeness` | ✅ PASS | **1.000** | 0.900 ↑ | 3 |
| `conversation` | ✅ PASS | **1.000** | 0.950 ↑ | 9 |
| `groundedness` | ✅ PASS | **1.000** | 0.950 ↑ | 121 |
| `multilingual` | ✅ PASS | **0.917** | 0.850 ↑ | 12 |
| `refusal` | ✅ PASS | **0.923** | 0.900 ↑ | 39 |
| `safety` | ✅ PASS | **1.000** | 0.950 ↑ | 42 |
| `toxicity-coverage` | ✅ PASS | **1.000** | 0.990 ↑ | 12 |
<!-- /scoreboard:eval-report -->

Overall verdict **PASS**, run fingerprint `50a032e7e395aa04` (dataset) ·
`ff1ad7874e00` (judge config) · seed `1729` · target
`deterministic:extractive`. `tests/test_committed_artifacts_are_current.py::test_readme_scoreboard_matches_the_committed_report`
re-renders this table from `eval-report.json` and fails if the README has drifted from it, so
these numbers cannot outlive the run that produced them.

Two of them are honest about their own weakness rather than rounded away. `completeness` scores
1.000 on **n=3**, an under-powered sample whose 95% CI is [0.439, 1.000] — the committed report
labels it as such. `refusal` sits at 0.923 against a 0.90 offline floor, below the 0.95 portfolio
target, because the deterministic hashing embedder cannot separate every unknown-species or
jailbreak phrasing; that gap is recorded in the model card, not hidden.


---

Agent-facing build instructions live in [`CLAUDE.md`](./CLAUDE.md) (the spec, plus the
agent contract at its end).

## Standards conformance

The table below names the engineering standards applied to Sprout; their concrete controls,
targets, and evidence are recorded in this public repository. Per-repo *values* live in
[`docs/ROADMAP.md`](docs/ROADMAP.md) and
[`docs/RESPONSIBLE-TECH-AUDITS.md`](docs/RESPONSIBLE-TECH-AUDITS.md).

| Standard | State | This repo's posture |
|---|---|---|
| Quality & Metrics | Applies | ISO 25010 / DORA. Metrics ledger in ROADMAP; `make verify` uses the same tools/thresholds as the CI-required checks |
| Code Quality | Applies | `ruff` + `mypy --strict`; branch coverage ≥**90%**<!-- claim:readme-coverage-floor --> (published-library floor); src layout |
| Security & Supply-Chain | Applies | ASVS L1 offline mode; scoped ASVS L2 review for the authenticated Family Greenhouse boundary; pip-audit + Semgrep blocking; gitleaks; CodeQL + zizmor; SHA-pinned actions; release SBOM |
| CI/CD | Applies | Single `ci-gate` required check; least-privilege tokens; `make verify` mirrors CI's tools/thresholds |
| Release & Versioning | Applies | SemVer; Keep-a-Changelog; PyPI Trusted Publishing (OIDC) wired; **no tag has ever been cut yet** — signed tags apply starting the first real release (corrected 2026-07-05; see `CHANGELOG.md`) |
| Accessibility | Applies | WCAG 2.2 AA target; structural `sprout a11y-check`, axe/pa11y, and Lighthouse accessibility (threshold 0.95) are all **merge-blocking** (wired 2026-07-08); transcript view; ACR (VPAT 2.5 Rev 508) |
| Observability | Applies | Tier C (offline CLI: structured JSON logs, PII-free, integration-tested); Tier A for the optional serverless API |
| Internationalization | Applies | EN/ES key + placeholder parity; the `multilingual` eval suite gates *per-case* EN/ES structural parity — each Spanish case must match its English anchor on the refuse/answer decision and the cited-plant set — at **≥ 0.85**<!-- claim:readme-multilingual-parity-threshold -->. An \|EN−ES\| *pass-rate delta* is a planned metric that nothing computes or gates; the model card records it `value: null, verified: false` |
| AI Evaluation | Applies | RAG groundedness/safety/multilingual gates green; refusal gated at **0.90**<!-- claim:readme-refusal-target --> (offline floor, portfolio target 0.95, recorded as an open gap); judge-calibration (deterministic judge, 66 probes) **enforced floor: agreement ≥ 0.80**<!-- claim:readme-judge-calibration-floor-agreement --> **· Cohen's κ ≥ 0.60**<!-- claim:readme-judge-calibration-floor-kappa --> (CI gate; a regression below either fails the build) — last *measured*, well above floor, at agreement 0.955 / κ 0.906 (probe set expanded + antonym-polarity guard, 2026-07-08 — see `docs/ROADMAP.md`); judge≠answer model; model/data cards |
| Documentation | Applies | Full `docs/` set; ADRs; dated, regenerated audit artifacts |
| Responsible-Tech Framework | Applies | `docs/RESPONSIBLE-TECH-AUDITS.md` §A–F + AI-EVAL + I18N; every audit applies (added to this table 2026-07-05 — was silently omitted) |
| Performance | Applies | Offline first-token latency budgeted at p95 < 200 ms and gated by `tests/test_latency.py`; reproducibility budgets in the ROADMAP ledger; Tier-A latency and availability SLOs declared in `slos/` and schema-checked by `make slo` |
| Incident Response | Applies | `SECURITY.md` is the private reporting channel and states the disclosure SLA: triage within 72 hours, CVSS-based severity, coordinated disclosure, and a `Security` CHANGELOG entry referencing the advisory. Not met: no severity-label convention and no committed-postmortem requirement |
| Data Governance | Applies | `docs/cards/data-card-corpus.md` and `docs/cards/model-card.md` are committed and regenerated with the audits; corpus provenance and citation freshness are gated by `make freshness`. Not met: no stated governance tier and no retention SLA |
| AI Development Measurement | Applies | Not met: no baseline and no outcome metrics are recorded for this repository's development stream |

No standard is `N/A`. Family Greenhouse Phase A personalization is implemented behind a feature
flag with an ASVS L2 review; notification and confirmed-write phases remain deferred. Every row above with a
"open gap" note is recorded in [`docs/ROADMAP.md`](docs/ROADMAP.md) and this repo's remediation
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
eval/suites/       YAML case suites (see "The eval harness" above); baseline.json
web/dist/          framework-free WCAG 2.2 reference and assurance surface
docs/              ARCHITECTURE · THREAT-MODEL · ACCESSIBILITY · ROADMAP · audits/ · cards/ · adr/
```

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Bundled corpus and eval
datasets are synthetic and CC0-1.0. This is not veterinary or medical advice.
