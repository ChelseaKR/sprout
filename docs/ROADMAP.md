# Sprout — roadmap, metrics ledger, and conformance declarations

> This file carries Sprout's *values*. The cross-cutting rigor lives once in
> [`../../STANDARDS/`](../../STANDARDS/README.md); this repo references it and records only
> its targets, measured numbers, declared tiers, and any justified deviation. Silent
> deviation from a standard is a defect, not a footnote.

Author: Chelsea Kelly-Reif · Last updated: 2026-07-05 (conformance-audit remediation pass —
corrected several rows below that had gone stale since 2026-06-22; see the dated erratum/gap
notes throughout) · Status: `In build` (Phase 3).

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
| **groundedness** (every claim entailed by its cited passage) | **≥ 0.95**<!-- claim:roadmap-groundedness-threshold --> | `eval/suites/groundedness` + judge entailment | AUTO |
| **safety** (cite a toxicity ref, never certify "safe," route to vet/poison-control) | **≥ 0.95** | `eval/suites/safety` + deny-list guard | AUTO |
| **refusal** (out-of-scope, "just tell me it's fine," embedded injection) | **0.90 offline / ≥ 0.95 portfolio**<!-- claim:roadmap-refusal-target --> — `sprout eval` now auto-selects the gate from `retrieval.embedding_provider` (`refusal.threshold_for`): the offline hashing embedder keeps its documented 0.90 floor (per the suite's own docstring — it cannot fully separate every unknown-species/jailbreak phrasing from in-scope), and the run auto-raises the gate to the ≥ 0.95 portfolio target the moment `embedding_provider: bedrock` (Titan) is configured. CI still exercises the offline default only, so 0.90 remains what's actually measured today — corrected 2026-07-08, was a hardcoded 0.90 with no enforcement path to 0.95 at all | `eval/suites/refusal` | AUTO |
| **multilingual** (ES preserves the facts + citations of its EN mirror) | **≥ 0.85** | `eval/suites/multilingual` + judge equivalence | AUTO |
| **calibration** (stated confidence tracks correctness) | **ECE ≤ 0.15** | `eval/suites/calibration` (reliability diagram + ECE) | AUTO |
| Abstention enforced below threshold | answered cases below 0.25<!-- claim:roadmap-abstention-enforced --> confidence must have been refusals (ADR-0012, supersedes ADR-0005; corrected 2026-07-05 — see execution log) | calibration suite invariant | AUTO |
| EN/ES pass-rate parity | **\|EN − ES\| ≤ 5 pp** | bilingual benchmark slice | AUTO |
| Hallucination rate | 0% by construction (extractive + citation guard) | citation guard unit tests + groundedness suite | AUTO |
| Judge ↔ human agreement | ≥ 0.80 raw · Cohen's κ ≥ 0.60 | `sprout calibrate --gate` on the dated probe set | AUTO (fixed 2026-07-08, P0-4 — the deterministic judge's negation-only polarity guard missed antonym contradictions with no explicit negation marker, e.g. "safe" asserted against a source that says "toxic"; `has_antonym_conflict` closes that gap for `entails` and `equivalent`, raising the measured record to 0.917 agreement / κ 0.824 on the same 12-probe set, and the CI/`make verify` step now passes `--gate` and can fail the build. See `docs/audits/judge-calibration.md`.) |
| Judge-calibration freshness | probe set re-labeled within 30 days | `labeled_date` on `eval/judge_probes.yaml`, checked by `sprout calibrate` | **warn-only (wired 2026-07-05, P1-19) — currently 13 days old, under threshold; `sprout calibrate` prints a warning past 30 days but does not yet fail the command (ties to P0-4: flips to a hard failure once the LLM judge is calibrated and `--gate` is enabled)** |
| Fail-closed loader | hash mismatch / malformed case / empty suite / bad judge output → FAIL | `eval/dataset.py` + `runner.fail_closed` | AUTO |
| Model card completeness | required HF front-matter present | `tests/test_model_card.py` | AUTO (wired 2026-07-05 — see P1-11; previously declared AUTO with no lint) |
| Card honesty / limits framing | truthful, not box-ticking | owner review per release | REVIEW |
| Red-team (OWASP LLM01–LLM10) | 0 open critical findings | Promptfoo `redteam` on prompt/model PRs | **config committed 2026-07-08 (`eval/redteam/promptfooconfig.yaml`, `eval/redteam/README.md`) — covers OWASP LLM01–LLM10 against the live `POST /api/chat` pipeline in EN+ES; wired as an advisory, non-blocking `redteam` CI job (`.github/workflows/ci.yml`) that needs `ANTHROPIC_API_KEY`; gap now: the key is not yet provisioned as a repo secret and no run has completed, so it is not yet in `ci-gate` and "0 open critical findings" is not yet a measured number — the refusal/adversarial eval suite plus the manual dated red-team report (`docs/audits/red-team-2026-06-22.md`) remain the standing substitute until a run is observed clean and the job is promoted to blocking** |
| Garak (LLM vulnerability scanner) | n/a | — | **N/A-with-reason** — the offline deterministic default has no LLM to scan (extractive generation, no model in the loop); revisit when the Bedrock/Anthropic generator seam is activated in a production configuration. Added 2026-07-05 (previously unrecorded — AIEV-14). |

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
| First-token latency (offline) | p95 < 200 ms | `tests/test_latency.py` | AUTO (wired 2026-07-05 — previously declared AUTO with no test; see P1-10) |
| Reproducibility | byte-identical report from identical inputs | run fingerprint excludes wall-clock | AUTO |
| Versioning | SemVer; Keep-a-Changelog; signed tags on first release | release workflow | AUTO (mechanism wired; **never yet exercised** — no tag has ever been cut, corrected 2026-07-05; see CHANGELOG.md) |
| Publish | PyPI Trusted Publishing (OIDC) | release workflow | AUTO (wired; unexercised — same caveat) |
| CI parity | `make verify` uses the same tools/thresholds as the required `ci-gate` checks | `sprout ci-parity-check` (`src/sprout/ci_parity.py`, `tests/test_ci_parity.py`) mechanically diffs `.github/workflows/ci.yml`'s required jobs against their `Makefile` target(s); run via `make ci-parity-check` (also a `make verify` prerequisite) and the `ci-parity` CI job (a `ci-gate` dependency) | AUTO (wired 2026-07-08, closing `ci-parity-no-mechanical-diff`; the checker's first run also surfaced two real gaps — `docs` and the `zizmor` workflow-SAST scan were required by `ci-gate` but absent from `make verify` — now closed via new `docs`/`workflow-lint` prerequisites) |

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
| Release & Versioning | APPLIES | SemVer; Keep-a-Changelog; PyPI Trusted Publishing (OIDC) wired but unexercised; signed tags on first release (no tag has ever been cut — corrected 2026-07-05, see `docs/ROADMAP.md` REL-03 note below) |
| Accessibility | APPLIES | WCAG **2.2 AA** target; structural `sprout a11y-check` gate is merge-blocking; axe/pa11y advisory-only and Lighthouse not yet wired (gap tracked); transcript view; ACR (VPAT 2.5 Rev 508) |
| Observability | APPLIES | **Tier C** (offline CLI) + **Tier A** (optional serverless); see section above; non-CLI Tier-A controls tracked |
| Internationalization | APPLIES | EN/ES key + placeholder parity; \|EN − ES\| ≤ 5 pp eval parity |
| AI Evaluation | APPLIES (RAG, red-team, model-card) | groundedness/safety/refusal/multilingual/calibration gates; judge ≠ answer model; κ + reliability; model/data cards |
| Documentation | APPLIES | Full `docs/` set; ADRs; dated, regenerated audit artifacts |
| Responsible-Tech Framework | APPLIES | `docs/RESPONSIBLE-TECH-AUDITS.md` §A–F + AI-EVAL + I18N; no audit is N/A; added to this table 2026-07-05 (was silently omitted — DOC-11) |

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

**Status: substantially done** (corrected 2026-07-05 — this was stale since 06-22 and had not
caught up with actual repo state per DOC-15).
- Done: hybrid retrieval (`retrieve.py` — BM25 + deterministic dense via reciprocal rank fusion,
  topic filter, `min_score` threshold gate), `guards.py` v1 (citation guard, never-certify-safe
  deny-list EN/ES, scope via retrieval threshold, PII redaction + injection labeling), ingest /
  chunk / store pipeline, config-over-code (`config/sprout.yaml`). The synthetic CC0 corpus is
  committed at `corpus/processed/` — **32 files** (16 species × EN/ES) with a dated, licensed
  `corpus/manifest.yaml` — not the "ships no passages yet" state a prior version of this line
  claimed.
- Outstanding: a dedicated CI smoke suite of corpus-derived questions beyond what the eval
  harness (Phase 2) already exercises.

### Phase 2 — eval first
*Runner, judges, report. Author 60 cases (groundedness, safety, refusal) from the corpus. Wire
the CI smoke suite. Commit a baseline scoreboard, mediocre numbers included.*

**Status: substantially done** (corrected 2026-07-05 — see the same DOC-15 staleness note above).
- Done: the eval engine — fail-closed dataset loader, run fingerprint (reproducible), all five
  suites registered (`eval/suites/`), deterministic + Anthropic judges behind one Protocol
  (judge ≠ answer model), report generation (MD + HTML + JSON; JUnit + SARIF), Wilson statistical
  gate, ECE/reliability calibration. **128 YAML cases** are committed under `eval/suites/`
  (exceeds the 120+ target). `docs/audits/eval-baseline.json` is committed and, as of 2026-07-05,
  actually gates `sprout eval` (previously computed but never loaded by the CLI — AIEV-26,
  fixed). The eval job (`eval-a11y` in `ci.yml`) is inside the required `ci-gate` check. The
  judge-calibration probe set (`eval/judge_probes.yaml`, 12 probes) is committed and its κ is
  measured, and as of 2026-07-08 (P0-4) **meets** the standard's threshold (agreement
  0.917 ≥ 0.80, κ 0.824 ≥ 0.60) after closing the judge's antonym-polarity gap; the CI step now
  passes `--gate` and is merge-blocking — see AI evaluation suites table above.
- Outstanding: the probe set is still small (12; target 50–100) and the one remaining
  disagreement (a Spanish morphological synonym the lexical judge doesn't fold) is a real,
  documented limit of a lexical judge — expand/re-label the probe set toward the 50–100 target
  as new cases are authored, and back the gate with the calibrated LLM judge
  (`--judge llm --gate`) once it has its own probe-set-backed calibration record.

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
