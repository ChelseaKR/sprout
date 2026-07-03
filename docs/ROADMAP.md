# Sprout — roadmap, metrics ledger, and conformance declarations

> This file carries Sprout's *values*. The cross-cutting rigor lives once in
> [`../../STANDARDS/`](../../STANDARDS/README.md); this repo references it and records only
> its targets, measured numbers, declared tiers, and any justified deviation. Silent
> deviation from a standard is a defect, not a footnote.

Author: Chelsea Kelly-Reif · Last updated: 2026-06-22 · Status: `In build` (Phase 3).

---

## AI-Evaluation-Standard: APPLIES  (tiers: RAG, red-team, model-card)

Sprout retrieves-then-generates over a cited corpus and consults an LLM-as-judge, so the
[AI Evaluation Standard](../../STANDARDS/AI-EVALUATION-STANDARD.md) binds in full. The three
eval layers (retrieval, generation, calibration) are all gated; the judge model
(`claude-sonnet-4-6`) is structurally different from the default answer model
(`claude-haiku-4-5-20251001`), and the offline deterministic generator is the default so the
entire eval runs with no network and no cloud account.

**EU AI Act / NIST AI RMF classification (explicit, per §6):** Not Annex III high-risk — no
recruitment, credit, law-enforcement, education, or critical-infrastructure decisioning; a
houseplant-care assistant. Not GPAI; API-only, training compute = 0. The named GenAI risks in
scope are **confabulation** (mitigated structurally: extractive generation + citation guard,
groundedness 100% by construction) and **information integrity / safety** (the
never-certify-"safe" toxicity rule and vet/poison-control routing). Reviewed 2026-06-22 by
Chelsea Kelly-Reif; recorded in `docs/audits/ai-risk-register.md` on completion of Phase 2.

---

## Metrics ledger

The portfolio-standard `Metric | Target | Measured by | Gate` shape. Targets are *this repo's*
values; the gate mechanics are defined in the referenced standard, not restated here. Every
row is an **AUTO-GATE** (mechanically checked, merge-blocking) unless marked REVIEW. The one
command that reproduces the whole set locally is `make verify`
(`lint · type · test · security · eval · a11y`).

### Code quality and coverage — [`CODE-QUALITY-STANDARD`](../../STANDARDS/CODE-QUALITY-STANDARD.md)

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| Lint | zero findings | `ruff format --check` + `ruff check src tests` | AUTO |
| Type safety | zero errors, strict | `mypy` (strict; `py.typed` shipped) | AUTO |
| Branch coverage | **≥ 90%** (published-library floor) | `pytest --cov=sprout --cov-fail-under=90` | AUTO |
| Layout | `src/` layout, importable as `sprout` | packaging test + import | AUTO |

### AI evaluation suites — [`AI-EVALUATION-STANDARD`](../../STANDARDS/AI-EVALUATION-STANDARD.md)

Five suites, 120+ committed YAML cases, scored by deterministic checks blended with an
LLM-as-judge (judge ≠ answer model). Runs are content-hashed and **byte-identical for
identical inputs**; the gate is *both* the absolute threshold below *and* no regression past
tolerance from the committed baseline. Each PASS must also clear its Wilson lower bound when
the statistical gate is on (see `runner.py::_apply_statistical_gate`).

| Suite / metric | Target | Measured by | Gate |
|---|---|---|---|
| **groundedness** (every claim entailed by its cited passage) | **≥ 0.95** | `eval/suites/groundedness` + judge entailment | AUTO |
| **safety** (cite a toxicity ref, never certify "safe," route to vet/poison-control) | **≥ 0.95** | `eval/suites/safety` + deny-list guard | AUTO |
| **refusal** (out-of-scope, "just tell me it's fine," embedded injection) | **≥ 0.95** | `eval/suites/refusal` | AUTO |
| **multilingual** (ES preserves the facts + citations of its EN mirror) | **≥ 0.85** | `eval/suites/multilingual` + judge equivalence | AUTO |
| **calibration** (stated confidence tracks correctness) | **ECE ≤ 0.15** | `eval/suites/calibration` (reliability diagram + ECE) | AUTO |
| Abstention enforced below threshold | answered cases below 0.45 confidence must have been refusals | calibration suite invariant | AUTO |
| EN/ES pass-rate parity | **\|EN − ES\| ≤ 5 pp** | bilingual benchmark slice | AUTO |
| Hallucination rate | 0% by construction (extractive + citation guard) | citation guard unit tests + groundedness suite | AUTO |
| Judge ↔ human agreement | ≥ 0.80 raw · Cohen's κ ≥ 0.60 | `sprout calibrate` on the dated probe set | AUTO |
| Judge-calibration freshness | probe set re-labeled within 30 days | timestamp on `eval/judge_probes.yaml` | AUTO |
| Fail-closed loader | hash mismatch / malformed case / empty suite / bad judge output → FAIL | `eval/dataset.py` + `runner.fail_closed` | AUTO |
| Model card completeness | required HF front-matter present | `docs/cards/model-card.md` lint | AUTO |
| Card honesty / limits framing | truthful, not box-ticking | owner review per release | REVIEW |
| Red-team (OWASP LLM01–LLM10) | 0 open critical findings | Promptfoo `redteam` on prompt/model PRs | AUTO |

**Provider note (per standard §0):** Sprout standardizes on Anthropic Claude — Haiku to answer,
Sonnet to judge — behind a config switch; the deterministic offline generator is the default and
is what CI exercises (no network, no key). No "rejected because" deviation is recorded.

### Accessibility — [`ACCESSIBILITY-STANDARD`](../../STANDARDS/ACCESSIBILITY-STANDARD.md)

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| Conformance level | **WCAG 2.2 AA** | axe + pa11y + Lighthouse on chat UI, HTML eval report, transcript view | AUTO |
| Structural a11y check | zero violations | `sprout a11y-check` on `web/dist/index.html` + `docs/audits/eval-report.html` | AUTO |
| Non-chat alternate view | static, paginated Q/A/citations renders | transcript-view check | AUTO |
| Color independence | severity + provenance never color-only | manual SR review (NVDA, VoiceOver) | REVIEW |
| ACR (VPAT 2.5 Rev 508) | committed, regenerated on release | `docs/accessibility/ACR.md` | REVIEW |

### Security and supply chain — [`SECURITY-AND-SUPPLY-CHAIN-STANDARD`](../../STANDARDS/SECURITY-AND-SUPPLY-CHAIN-STANDARD.md)

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| App-security level | **OWASP ASVS L1** (offline mode; no auth, no persistence, no network) | review-gate checklist | REVIEW |
| Dependency audit | zero unresolved advisories | `pip-audit` (blocking in CI; **never** `\|\| true`) | AUTO |
| Secret scanning | zero leaks | `gitleaks` | AUTO |
| Static analysis | zero high findings | Semgrep / CodeQL | AUTO |
| Actions pinning | SHA-pinned, least-privilege tokens | CI policy lint | AUTO |
| SBOM | emitted on release | release workflow | AUTO |
| PII in logs | **zero** — logger whitelists low-cardinality fields only, never question text | `obs.py` `_ALLOWED_FIELDS` + Semgrep/bandit | AUTO (never N/A) |

### Internationalization — [`INTERNATIONALIZATION-STANDARD`](../../STANDARDS/INTERNATIONALIZATION-STANDARD.md)

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| EN/ES key + placeholder parity | complete, no orphan keys | per-language bundle diff | AUTO |
| EN/ES eval pass-rate parity | **\|EN − ES\| ≤ 5 pp** | multilingual suite (also in the AI ledger above) | AUTO |

### Quality, release, CI/CD — [`QUALITY-AND-METRICS`](../../STANDARDS/QUALITY-AND-METRICS-STANDARD.md) · [`RELEASE-AND-VERSIONING`](../../STANDARDS/RELEASE-AND-VERSIONING-STANDARD.md) · [`CI-CD-STANDARD`](../../STANDARDS/CI-CD-STANDARD.md)

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| First-token latency (offline) | p95 < 200 ms | latency budget test | AUTO |
| Reproducibility | byte-identical report from identical inputs | run fingerprint excludes wall-clock | AUTO |
| Versioning | SemVer; signed tags; Keep-a-Changelog | release workflow | AUTO |
| Publish | PyPI Trusted Publishing (OIDC) | release workflow | AUTO |
| CI parity | `make verify` == required `ci-gate` check | CI invocation diff | AUTO |

---

## Observability tier

Per the [Observability Standard §0](../../STANDARDS/OBSERVABILITY-STANDARD.md), the tier is
declared here and any skipped control is recorded as **N/A-with-reason**; silent omission is a
defect caught by the tier-declaration gate. Sprout has two surfaces and states both.

**Tier C — the offline CLI (the default, and what CI exercises).**
`OTEL_SERVICE_NAME` / `service.name` = `sprout`.

- Logging is opt-in structured JSON via `observability.log_format: json` (`text` by default),
  emitted by `src/sprout/obs.py`. It is **PII-free by construction**: the logger drops any
  field outside a whitelist of low-cardinality keys (`language`, `refused`, `refusal_reason`,
  `is_safety_query`, `confidence`, `n_retrieved`, `n_sentences`, `injection_categories`,
  `status`, `route`, `index_size`) — the user's question text is never logged.
- **N/A-with-reason — OTel tracing, RED/USE metrics, SLOs, burn-rate alerts, `/livez`+`/readyz`:**
  out of scope for a local-only CLI with no network surface (standard §10). The valid-JSON and
  required-field log gates apply *only when* `--log-format json` is selected.
- **NOT N/A — the PII/secrets-in-logs gate.** It is non-tiered and binds here exactly as in any
  Tier-A service; the whitelist above is its enforcement.

**Tier A — the optional serverless API (`infra/`, behind a config switch).**
When the cloud generator and serverless deploy are enabled, the API surface adopts the full
Tier-A stack: OTel traces + metrics with trace-correlated structured logs, RED per endpoint,
`/livez`+`/readyz`, an SLO file, and multi-window burn-rate alerts. This surface is **scaffold
only today** (Phase 3/4); its Tier-A controls are tracked, not yet green, and `infra/` ships no
deployable manifest at this commit. The offline Tier-C path remains fully functional with the
serverless surface absent.

---

## Per-standard applicability — none N/A

Every portfolio standard **APPLIES** to Sprout. There is no standard marked N/A at the repo
level. The single deferred scope is noted explicitly.

| Standard | Applies | Posture / values |
|---|---|---|
| Quality & Metrics (ISO 25010 / DORA) | APPLIES | Ledger above; `make verify` = CI gate set; latency + reproducibility budgets |
| Code Quality | APPLIES | `ruff` + `mypy --strict`; branch coverage ≥ 90%; `src/` layout |
| Security & Supply Chain | APPLIES | ASVS **L1** (offline mode — no auth/persistence/network to defend); pip-audit, gitleaks, Semgrep, SHA-pinned actions, SBOM |
| CI/CD | APPLIES | Single `ci-gate` required check; least-privilege tokens; local/CI parity via `make verify` |
| Release & Versioning | APPLIES | SemVer; signed tags; Keep-a-Changelog; PyPI Trusted Publishing (OIDC) |
| Accessibility | APPLIES | WCAG **2.2 AA** gate; transcript view; ACR (VPAT 2.5 Rev 508) |
| Observability | APPLIES | **Tier C** (offline CLI) + **Tier A** (optional serverless); see section above; non-CLI Tier-A controls tracked |
| Internationalization | APPLIES | EN/ES key + placeholder parity; \|EN − ES\| ≤ 5 pp eval parity |
| AI Evaluation | APPLIES (RAG, red-team, model-card) | groundedness/safety/refusal/multilingual/calibration gates; judge ≠ answer model; κ + reliability; model/data cards |
| Documentation | APPLIES | Full `docs/` set; ADRs; dated, regenerated audit artifacts |

**Deferred (not N/A) — Family Greenhouse personalization.** The household-data path
(per-user context from the Family Greenhouse public API, the `personalization` and `provenance`
eval suites, sentinel-PII privacy proofs, and the **ASVS L2** posture that an authenticated,
key-bearing network surface requires) is **deferred to a later phase** and is intentionally
absent from this commit. It does not lower any standard — it *raises* the security bar from L1
to L2 when it lands, and adds two eval suites. Until then, corpus-only (the privacy-preserving
default) is fully functional. See **Family Greenhouse integration** in
[`../CLAUDE.md`](../CLAUDE.md) for the full plan and phasing (A → B → C).

---

## Build plan and current status

The four phases from the spec, with honest status as of 2026-06-22. A phase is **done** only
when `make verify` is green for its scope.

### Phase 1 — corpus + retrieval
*Fetch and snapshot open-licensed care/toxicity references with a dated manifest; chunk by care
topic; hybrid retrieval against smoke questions; `guards.py` v1 (safety-assertion ban, scope,
PII).*

**Status: in progress.**
- Done: hybrid retrieval (`retrieve.py` — BM25 + deterministic dense via reciprocal rank fusion,
  topic filter, `min_score` threshold gate), `guards.py` v1 (citation guard, never-certify-safe
  deny-list EN/ES, scope via retrieval threshold, PII redaction + injection labeling), ingest /
  chunk / store pipeline, config-over-code (`config/sprout.yaml`).
- Outstanding: author and commit the synthetic CC0 corpus into `corpus/processed/` with a dated,
  licensed `corpus/manifest.yaml` (the directory exists but ships no passages yet); wire the CI
  smoke suite of corpus-derived questions.

### Phase 2 — eval first
*Runner, judges, report. Author 60 cases (groundedness, safety, refusal) from the corpus. Wire
the CI smoke suite. Commit a baseline scoreboard, mediocre numbers included.*

**Status: harness built; cases + baseline pending.**
- Done: the eval engine — fail-closed dataset loader, run fingerprint (reproducible), all five
  suites registered (`eval/suites/`), deterministic + Anthropic judges behind one Protocol
  (judge ≠ answer model), report generation (MD + HTML + JSON; JUnit + SARIF), Wilson statistical
  gate, ECE/reliability calibration.
- Outstanding: author the 120+ YAML cases under `eval/suites/`; run `make eval-baseline` to
  commit `docs/audits/eval-baseline.json` + the first scoreboard (mediocre numbers included, not
  hidden); make the eval job a required CI status check; commit the judge-calibration probe set
  and its κ.

### Phase 3 — quality + multilingual
*Tune retrieval/prompts against eval failures only; add calibration suite and abstention; Spanish
to parity; model card. Accessible web UI deployed behind a real URL with a "reference
implementation" banner.*

**Status: in progress (current phase).**
- Done: calibration suite + two-threshold abstention (`confidence.py`), EN/ES throughout
  (`lang.py`, per-language bundles, parity suite), framework-free WCAG 2.2 chat UI shipped in
  `web/dist/`, structural a11y check, structured PII-free logging.
- Outstanding: tune only against committed eval failures (no tuning to the test set); commit the
  model card at `docs/cards/model-card.md` and the data card; deploy the UI behind a real URL
  with the reference-implementation banner; commit the ACR and the OWASP-LLM red-team report.

### Phase 4 — generalize
*A `corpus.yaml` so any care corpus can be swapped in; "adapt this to your domain" doc.*

**Status: guide done; personalization phases deferred.**
- The seam exists (`config/sprout.yaml` already points the whole system at a corpus path,
  manifest, languages, models, and thresholds; the eval runner is corpus-agnostic). The
  "adapt this to your domain" guide is written ([`docs/ADAPT.md`](ADAPT.md), linked in the site
  nav) and walks an adopter through swapping the corpus, manifest, domain vocabulary,
  retrieval/abstention tuning, languages, and generator/embedding provider using only that
  config seam. Remaining Phase 4 scope is the deferred Family Greenhouse personalization phases
  (A → B → C) above.

---

## Definition of done (the bar each phase is held to)

A fresh user can `pipx install sprout`, ask a plant question **offline**, get a cited answer (or
an honest refusal), run `make eval` to regenerate the committed report with no cloud account, and
read a model card that states the limits plainly — with every CI gate green. `make verify`
reproduces the full gate set locally; if it is not green, the phase is not done.
