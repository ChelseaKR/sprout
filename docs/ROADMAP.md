# Sprout — roadmap, metrics ledger, and conformance declarations

> This file records Sprout's public targets, measured numbers, declared tiers, and any
> justified deviation from the named engineering standards. Silent
> deviation from a standard is a defect, not a footnote.

Author: Chelsea Kelly-Reif · Last updated: 2026-07-12 (GenAI lifecycle telemetry and weekly
corpus-freshness gate; conformance-audit remediation pass began 2026-07-05 —
corrected several rows below that had gone stale since 2026-06-22; see the dated erratum/gap
notes throughout) · Status: `In build` (Phase 3).

---

## AI-Evaluation-Standard: APPLIES  (tiers: RAG, red-team, model-card)

Sprout retrieves-then-generates over a cited corpus and consults an LLM-as-judge, so the
AI Evaluation Standard binds in full. The three
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

### Code quality and coverage — `CODE-QUALITY-STANDARD`

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| Lint | zero findings | `ruff format --check` + `ruff check src tests` | AUTO |
| Type safety | zero errors, strict | `mypy` (strict; `py.typed` shipped) | AUTO |
| Branch coverage | **≥ 90%** (published-library floor) | `pytest --cov=sprout --cov-fail-under=90` | AUTO |
| Layout | `src/` layout, importable as `sprout` | packaging test + import | AUTO |

### AI evaluation suites — `AI-EVALUATION-STANDARD`

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
| Judge ↔ human agreement (deterministic judge, CI floor) | ≥ 0.80 raw · Cohen’s κ ≥ 0.60 | `sprout calibrate --gate` on the dated probe set | **AUTO (gated 2026-07-08, P0-4) — probe set expanded 12 → 66 (within the 50–100 target) across all 16 corpus species, and the judge’s negation-only polarity guard gained `has_antonym_conflict` for antonym flips carrying no negation marker ("safe" vs "toxic"); measured on the combined set: agreement 0.955, κ 0.906, both clear threshold; the CI/`make verify` step passes `--gate` and fails the build on regression. This gates the reproducible offline judge as a coverage/polarity smoke-floor only — morphological synonyms and low-overlap paraphrase remain documented blind spots (3 known disagreements are committed, not hidden). See `docs/audits/judge-calibration.md`.** |
| Judge ↔ human agreement (LLM judge, production gate) | ≥ 0.80 raw · Cohen’s κ ≥ 0.60 | `sprout calibrate --judge llm` | **not yet done — the LLM judge needs a live Anthropic credential and is deliberately never invoked in CI (see `eval/llm_judge.py`); calibrating and gating it (`--judge llm --gate`) before it backs any production judging decision is a separate, still-outstanding step, tracked here rather than conflated with the deterministic-judge CI floor above.** |
| Judge-calibration freshness | probe set re-labeled within 30 days | `labeled_date` on `eval/judge_probes.yaml`, checked by `sprout calibrate` | **warn-only (wired 2026-07-05, P1-19) — re-labeled 2026-07-08 alongside the 12→66 expansion; `sprout calibrate` prints a warning past 30 days but does not yet fail the command (ties to P0-4: flips to a hard failure once the LLM judge is calibrated and `--gate` is enabled)** |
| Fail-closed loader | hash mismatch / malformed case / empty suite / bad judge output → FAIL | `eval/dataset.py` + `runner.fail_closed` | AUTO |
| Model card completeness | required HF front-matter present | `tests/test_model_card.py` | AUTO (wired 2026-07-05 — see P1-11; previously declared AUTO with no lint) |
| Card honesty / limits framing | truthful, not box-ticking | owner review per release | REVIEW |
| Red-team (OWASP LLM01–LLM10) | 0 open critical findings | Promptfoo `redteam` on prompt/model PRs | **config committed 2026-07-08 (`eval/redteam/promptfooconfig.yaml`, `eval/redteam/README.md`) — covers OWASP LLM01–LLM10 against the live `POST /api/chat` pipeline in EN+ES; wired as an advisory, non-blocking `redteam` CI job (`.github/workflows/ci.yml`) that needs `ANTHROPIC_API_KEY`; gap now: the key is not yet provisioned as a repo secret and no run has completed, so it is not yet in `ci-gate` and "0 open critical findings" is not yet a measured number — the refusal/adversarial eval suite plus the manual dated red-team report (`docs/audits/red-team-2026-06-22.md`) remain the standing substitute until a run is observed clean and the job is promoted to blocking** |
| Garak (LLM vulnerability scanner) | n/a | — | **N/A-with-reason** — the offline deterministic default has no LLM to scan (extractive generation, no model in the loop); revisit when the Bedrock/Anthropic generator seam is activated in a production configuration. Added 2026-07-05 (previously unrecorded — AIEV-14). |

**Provider note (per standard §0):** Sprout standardizes on Anthropic Claude — Haiku to answer,
Sonnet to judge — behind a config switch; the deterministic offline generator is the default and
is what CI exercises (no network, no key). No "rejected because" deviation is recorded.

### GenAI lifecycle measurement

The optional Anthropic and Bedrock paths adopt the shared OpenTelemetry GenAI runtime vendored
byte-for-byte under `src/sprout/_vendor/genai_telemetry/` from immutable STANDARDS commit
`e8150c82fc35267f022af46ac71fe5a851e2d042`; `.standards-version` pins the boundary and
`src/sprout/genai_telemetry.py` is only the Sprout record/sink wrapper. Native
Anthropic answers, Bedrock Claude answers, Titan embeddings, and the native Anthropic judge all
record success/error duration, the locally selected request model, allowlisted protocol finish
reasons, and normalized usage fields, without reflecting provider strings or capturing content.
Claude answer/judge calls and Titan embeddings receive shared-table estimates;
Titan's AWS catalog price is selected by the configured Bedrock region carried on `Usage`.
The operational provider wrapper rejects answer calls before transport when the model is unpriced
or the estimate exceeds `generation.max_cost_usd`; Titan activation likewise rejects a missing or
unsupported region rather than borrowing a false rate. The wrapper forwards the original
query/context/limit into the behavior-bearing provider unchanged. Provider-separated fresh,
cache-creation, and cache-read tokens are summed into canonical total input before cache-hit and
Claude cost math; Titan's input-only row rejects unsupported output/cache usage.
Streaming first-chunk latency is N/A because none of these adapters streams. The implementation
and privacy proof are recorded in
`docs/audits/genai-lifecycle-telemetry-2026-07-12.md` and gated by
`tests/test_genai_telemetry.py`.

The offline eval/calibration loop remains merge-blocking, and the corpus has a weekly scheduled
freshness gate. The production trace-to-weekly-judge loop remains an explicit external launch
gate until the optional cloud API, credentials, and trace store exist; it cannot produce an
honest measured distribution before there is production traffic.

### Accessibility — `ACCESSIBILITY-STANDARD`

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| Conformance level | **WCAG 2.2 AA** | axe + pa11y (merge-blocking) and Lighthouse accessibility (merge-blocking, threshold 0.95) on the reference question UI + HTML eval report; transcript view not yet built (see row below) | AUTO |
| Structural a11y check | zero violations | `sprout a11y-check` on `web/dist/index.html` + `docs/audits/eval-report.html` | AUTO |
| Non-chat alternate view | static, paginated Q/A/citations renders | transcript-view check | AUTO |
| Color independence | severity + provenance never color-only | manual SR review (NVDA, VoiceOver) | REVIEW |
| ACR (VPAT 2.5 Rev 508) | committed, regenerated on release | `docs/accessibility/ACR.md` | REVIEW |

### Security and supply chain — `SECURITY-AND-SUPPLY-CHAIN-STANDARD`

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| App-security level | **OWASP ASVS L1** (offline mode; no auth, no persistence, no network) | review-gate checklist | REVIEW |
| Dependency audit | zero unresolved advisories | `pip-audit` (blocking in CI; **never** `\|\| true`) | AUTO |
| Secret scanning | zero leaks | `gitleaks` | AUTO |
| Static analysis | zero high findings | Semgrep / CodeQL | AUTO |
| Actions pinning | SHA-pinned, least-privilege tokens | CI policy lint | AUTO |
| SBOM | emitted on release | release workflow | AUTO |
| PII in logs | **zero** — logger whitelists low-cardinality fields only, never question text | `obs.py` `_ALLOWED_FIELDS` + Semgrep/bandit | AUTO (never N/A) |

### Internationalization — `INTERNATIONALIZATION-STANDARD`

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| EN/ES key + placeholder parity | complete, no orphan keys | per-language bundle diff | AUTO |
| EN/ES eval pass-rate parity | **\|EN − ES\| ≤ 5 pp** | multilingual suite (also in the AI ledger above) | AUTO |

### Quality, release, CI/CD — `QUALITY-AND-METRICS` · `RELEASE-AND-VERSIONING` · `CI-CD-STANDARD`

| Metric | Target | Measured by | Gate |
|---|---|---|---|
| First-token latency (offline) | p95 < 200 ms | `tests/test_latency.py` | AUTO (wired 2026-07-05 — previously declared AUTO with no test; see P1-10) |
| Reproducibility | byte-identical report from identical inputs | run fingerprint excludes wall-clock | AUTO |
| Versioning | SemVer; Keep-a-Changelog; signed tags on first release | release workflow | AUTO (mechanism wired; **never yet exercised** — no tag has ever been cut, corrected 2026-07-05; see CHANGELOG.md) |
| Publish | PyPI Trusted Publishing (OIDC) | release workflow | AUTO (wired; unexercised — same caveat) |
| CI parity | `make verify` uses the same tools/thresholds as the required `ci-gate` checks | `sprout ci-parity-check` (`src/sprout/ci_parity.py`, `tests/test_ci_parity.py`) mechanically diffs `.github/workflows/ci.yml`'s required jobs against their `Makefile` target(s); run via `make ci-parity-check` (also a `make verify` prerequisite) and the `ci-parity` CI job (a `ci-gate` dependency) | AUTO (wired 2026-07-08, closing `ci-parity-no-mechanical-diff`; the checker's first run also surfaced two real gaps — `docs` and the `zizmor` workflow-SAST scan were required by `ci-gate` but absent from `make verify` — now closed via new `docs`/`workflow-lint` prerequisites) |

---

## Observability tier

Per the Observability Standard §0, the tier is
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
| Accessibility | APPLIES | WCAG **2.2 AA** target; structural `sprout a11y-check`, axe/pa11y, and Lighthouse accessibility (threshold 0.95) are all merge-blocking as of 2026-07-08 (previously axe/pa11y advisory-only and Lighthouse unwired); transcript view; ACR (VPAT 2.5 Rev 508) |
| Observability | APPLIES | **Tier C** (offline CLI) + **Tier A** (optional serverless); see section above; non-CLI Tier-A controls tracked |
| Internationalization | APPLIES | EN/ES key + placeholder parity; \|EN − ES\| ≤ 5 pp eval parity |
| AI Evaluation | APPLIES (RAG, red-team, model-card) | groundedness/safety/refusal/multilingual/calibration gates; judge ≠ answer model; κ + reliability; model/data cards |
| Documentation | APPLIES | Full `docs/` set; ADRs; dated, regenerated audit artifacts |
| Responsible-Tech Framework | APPLIES | `docs/RESPONSIBLE-TECH-AUDITS.md` §A–F + AI-EVAL + I18N; no audit is N/A; added to this table 2026-07-05 (was silently omitted — DOC-11) |

**Family Greenhouse personalization.** Phase A is implemented behind a feature flag: strict
minimized context, HMAC authentication, provenance labeling, sentinel-PII proofs, and a scoped
**ASVS L2** review. Corpus-only remains the privacy-preserving default. Phases B (proactive
notifications) and C (confirmed write-back) remain deferred. See **Family Greenhouse integration** in
[`../CLAUDE.md`](../CLAUDE.md) for the full plan and phasing (A → B → C).

---

## Build plan and current status

The four phases from the spec, with honest status as of 2026-06-22. A phase is **done** only
when `make verify` is green for its scope.

### Phase 1 — corpus + retrieval
*Fetch and snapshot open-licensed care/toxicity references with a dated manifest; chunk by care
topic; hybrid retrieval against smoke questions; `guards.py` v1 (safety-assertion ban, scope,
PII).*

**Status: done** (corrected 2026-07-08 — the dedicated smoke suite below closed the last
outstanding Phase 1 gap; corrected 2026-07-05 — this was stale since 06-22 and had not caught
up with actual repo state per DOC-15).
- Done: hybrid retrieval (`retrieve.py` — BM25 + deterministic dense via reciprocal rank fusion,
  topic filter, `min_score` threshold gate), `guards.py` v1 (citation guard, never-certify-safe
  deny-list EN/ES, scope via retrieval threshold, PII redaction + injection labeling), ingest /
  chunk / store pipeline, config-over-code (`config/sprout.yaml`). The synthetic CC0 corpus is
  committed at `corpus/processed/` — **32 files** (16 species × EN/ES) with a dated, licensed
  `corpus/manifest.yaml` — not the "ships no passages yet" state a prior version of this line
  claimed.
- Done: a dedicated CI smoke suite of corpus-derived questions, beyond what the eval harness
  (Phase 2) already exercises — `sprout smoke` (`src/sprout/smoke.py`), wired as its own
  merge-blocking `smoke` job in `ci.yml`. Every case is templated mechanically from the
  ingested corpus's own species slugs and `## <topic>` headings (one question per
  (species, topic) pair actually present in the store), not hand-authored, so coverage tracks
  the corpus automatically as species/topics are added. Runs the offline deterministic
  generator only (no judge, no network) — a fast, judge-free canary distinct from the
  hand-authored 142-case Phase 2 harness. 80 cases pass over the shipped corpus; report
  committed at `docs/audits/smoke-report.md`.

### Phase 2 — eval first
*Runner, judges, report. Author 60 cases (groundedness, safety, refusal) from the corpus. Wire
the CI smoke suite. Commit a baseline scoreboard, mediocre numbers included.*

**Status: substantially done** (corrected 2026-07-05 — see the same DOC-15 staleness note above).
- Done: the eval engine — fail-closed dataset loader, run fingerprint (reproducible), all five
  suites registered (`eval/suites/`), deterministic + Anthropic judges behind one Protocol
  (judge ≠ answer model), report generation (MD + HTML + JSON; JUnit + SARIF), Wilson statistical
  gate, ECE/reliability calibration. **142 YAML cases** are committed under `eval/suites/`
  (exceeds the 120+ target). `docs/audits/eval-baseline.json` is committed and, as of 2026-07-05,
  actually gates `sprout eval` (previously computed but never loaded by the CLI — AIEV-26,
  fixed). The eval job (`eval-a11y` in `ci.yml`) is inside the required `ci-gate` check. The
  judge-calibration probe set (`eval/judge_probes.yaml`, expanded 2026-07-08 from 12 to **66
  probes** across all 16 corpus species — within the 50–100 target) is committed and its κ is
  measured, and now **clears** the standard’s threshold (agreement 0.955 ≥ 0.80, κ 0.906 ≥ 0.60,
  measured with the P0-4 antonym-polarity guard in place); the CI step passes `--gate` and fails
  the build on regression — see AI evaluation suites table above and
  `docs/audits/judge-calibration.md`.
- Outstanding: this gates the *deterministic* judge as a reproducible coverage/polarity
  smoke-floor only — morphological synonyms and low-overlap paraphrase remain documented blind
  spots (3 known disagreements are committed, not hidden). Calibrating and gating the *LLM*
  judge (`--judge llm --gate`) before it backs a real production judging decision is separate,
  still-outstanding work that needs a live Anthropic credential and cannot run in CI.

### Phase 3 — quality + multilingual
*Tune retrieval/prompts against eval failures only; add calibration suite and abstention; Spanish
to parity; model card. Deploy the accessible, stateless reference-and-assurance web surface behind
a real URL.*

**Status: in progress (current phase).**
- Done: calibration suite + two-threshold abstention (`confidence.py`), EN/ES throughout
  (`lang.py`, per-language bundles, parity suite), framework-free WCAG 2.2 reference surface
  shipped at `https://sprout.chelseakr.com` through the zero-server TypeScript port (one
  stateless corpus question, claim chain, evaluation evidence, and docs;
  household/photo/reminder workflows excluded per ADR 0015), structural a11y check,
  structured PII-free logging, the **ACR**
  (`docs/accessibility/ACR.md`, VPAT 2.5 Rev 508) and a dedicated **OWASP-LLM red-team report**
  (`docs/audits/red-team-2026-06-22.md`, LLM01–LLM10:2025 coverage table, 0 open critical
  findings) — both committed in the 2026-07-05 conformance pass. Corrected here 2026-07-08: this
  bullet previously still listed the ACR and the red-team report as *outstanding* after they had
  already been committed (DOC-defect, same class as the other 2026-07-05/07-08 "declared vs.
  actual" corrections in this file). **Caveat that remains real:** the red-team report is a
  structured *manual* exercise, not yet backed by an automated, per-PR mechanical check — see the
  "Red-team (OWASP LLM01–LLM10)" row in the AI evaluation ledger above, which honestly carries
  that gap (no Promptfoo run has completed against a provisioned key yet).
- Done: tuning only against committed eval failures is mechanically enforced by `sprout
  check-tuning-scope`, a required CI job. Changes to retrieval, generation, guards,
  calibration, lexical logic, or config must cite a case already recorded in the committed
  eval baseline via a `Tunes-Against:` commit trailer. Comment-only YAML and the exact named
  operational lifecycle wrapper are excluded by semantic/AST comparison. The initial lifecycle
  module is pinned to one reviewed bootstrap digest; all later lifecycle hunks are gated.
  Authorization comes from the merge-base baseline, and adversarial tests keep model, prompt,
  decoding, real-config, retrieval/guard, lifecycle-output, and unknown provider edits fail-closed.
- Outstanding: get a clean Promptfoo `redteam` run wired and
  promoted into the blocking `ci-gate` so the committed OWASP-LLM report is backed by a mechanical
  check rather than only the manual, dated one (tracked in the ledger row above).

### Phase 4 — generalize
*A `corpus.yaml` so any care corpus can be swapped in; "adapt this to your domain" doc.*

**Status: guide and read-only personalization Phase A done; Phases B–C deferred.**
- The seam exists (`config/sprout.yaml` already points the whole system at a corpus path,
  manifest, languages, models, and thresholds; the eval runner is corpus-agnostic). The
  "adapt this to your domain" guide is written ([`docs/ADAPT.md`](ADAPT.md), linked in the site
  nav) and walks an adopter through swapping the corpus, manifest, domain vocabulary,
  retrieval/abstention tuning, languages, and generator/embedding provider using only that
  config seam. Remaining Phase 4 scope is Family Greenhouse notification and confirmed-write
  phases B–C.

---

## Definition of done (the bar each phase is held to)

A fresh user can install Sprout from source (and, after the first release, via `pipx`), ask a
plant question **offline**, get a cited answer (or
an honest refusal), run `make eval` to regenerate the committed report with no cloud account, and
read a model card that states the limits plainly — with every CI gate green. `make verify`
reproduces the full gate set locally; if it is not green, the phase is not done.
