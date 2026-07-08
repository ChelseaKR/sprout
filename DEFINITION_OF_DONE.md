# Definition of Done

A change is **done** when it is provably correct, gated, and reversible — not when it "works on my
machine." This file is the acceptance contract: the same checklist the PR template enforces, with
the rationale spelled out. The cross-cutting rigor (coverage floors, the gate model, the security
posture) lives once in the portfolio [`STANDARDS/`](../STANDARDS/README.md) and is *referenced*
here; per-repo target values live in [`docs/ROADMAP.md`](docs/ROADMAP.md).

> **The one command that proves it:** `make verify` reproduces the full CI gate set locally —
> `lint · type · test (≥90%) · security · eval · a11y` — byte-for-byte with CI. A change is not
> done until `make verify` is green. A *phase* is not done until it is green on `main`.

## Acceptance criteria (every PR)

### Code quality and types
- [ ] `make lint` clean — `ruff format --check` and `ruff check` pass (no new suppressions without a
      comment justifying them).
- [ ] `make type` clean — `mypy --strict` passes; no new `# type: ignore` without a reason.
- [ ] `make test` green with **branch coverage ≥ 90%** (the published-library floor). New code paths
      carry tests; deterministic components are unit-tested, not just smoke-tested.

### Eval: green, and no baseline regression
- [ ] If behavior could change, `make eval` regenerated `docs/audits/eval-report.{md,html,json}`
      and the report is committed.
- [ ] **No regression** against the committed `docs/audits/eval-baseline.json`: every suite
      (groundedness · safety · calibration · refusal · multilingual) holds at or above its baseline
      pass rate, and reports are **byte-identical for identical inputs** (seeded, content-hashed).
      Every result also *reports* a Wilson 95% CI and an `underpowered` (n<30) flag, but the
      **optional `--statistical-gate` that flips a PASS to FAIL when the CI lower bound misses the
      threshold is off by default and not passed in CI** — turning it on today would flip
      `multilingual` (n=12) to FAIL on sample size, not quality (see `docs/ROADMAP.md`'s AI
      evaluation table and `docs/ideation/02-large-scale-fixes.md` FIX-12, which grows the suites
      past n≥30 before the gate is enabled). Corrected 2026-07-08 (FIX-02) — this line previously
      implied the statistical gate was unconditionally enforced.
- [ ] Groundedness stays **100% by construction** — extractive generation + the post-generation
      citation guard. An ungrounded sentence must not be able to render.
- [ ] Intentional baseline movement is its **own** commit (`make eval-baseline`) with a written
      rationale; baselines are never quietly nudged to make a PR pass.
- [ ] Judge model ≠ answer model is preserved (judge = Claude Sonnet, answer-mode generator = Claude
      Haiku on the cloud seam; offline default is the deterministic extractive generator).

### Safety guardrails (load-bearing)
- [ ] The **never-certify-"safe"** output guard and poison-control/vet routing still pass the
      `safety` suite in **both** EN and ES.
- [ ] Calibrated **abstention** still fires below threshold (the assistant refuses rather than
      guesses); `confidence.py` thresholds unchanged unless via ADR.
- [ ] EN/ES **parity** holds: |EN − ES| pass-rate ≤ 5pp, and Spanish answers preserve the facts and
      citations of their English mirror.
- [ ] If `src/sprout/guards.py`, `src/sprout/confidence.py`, or `src/sprout/eval/dataset.py`
      changed, an **ADR is linked** and a **CODEOWNER reviewed** it.

### Accessibility gate (merge-blocking)
- [ ] `make a11y` passes on the chat UI **and** the HTML eval report — the **WCAG 2.2 AA** structural
      gate (axe/pa11y/Lighthouse in CI). A regression fails the build; it is not a follow-up ticket.
- [ ] The non-chat **transcript/alternate view** still renders the same questions, answers, and
      citations; severity and provenance never depend on color alone.

### Security and supply chain
- [ ] `make security` clean (pip-audit; gitleaks/Semgrep in CI); no secrets committed; dependencies
      on the pinned lockfile. Offline default keeps the **ASVS L1** surface intact.

### Documentation and traceability
- [ ] Docs and `CHANGELOG.md` `[Unreleased]` updated; user-visible impact described, not commit
      subjects.
- [ ] Acceptance criteria trace to an issue; the retrieval/judge trace for changed answers is
      inspectable under the debug flag.

### ISO 25010 quality characteristic — **named**
- [ ] The PR names the **ISO/IEC 25010:2023** product-quality characteristic(s) it primarily moves,
      so quality is argued, not assumed. Use the canonical eight (and a relevant sub-characteristic):

  | Characteristic | Typical Sprout sub-characteristic |
  |---|---|
  | Functional suitability | correctness — answers entailed by the cited passage |
  | Reliability | fault tolerance / recoverability — degrade to offline; rebuild from `make ingest` |
  | Security | confidentiality / integrity — no query persistence; content-hashed corpus |
  | Maintainability | modularity / testability — independent ingest·retrieve·generate·guard·eval |
  | Performance efficiency | time behaviour — first-token + eval-run latency budgets |
  | Compatibility | interoperability — JSON/SSE API; JUnit + SARIF reports |
  | Usability | accessibility — WCAG 2.2 AA gate; learnability — one question box |
  | Portability | adaptability — point at a different corpus via `config/sprout.yaml` |

### Rollback
- [ ] A **rollback plan** is stated and is cheap: either a flag in `config/sprout.yaml` that returns
      to prior behavior, or a clean single-commit revert (no migrations, since there is no database
      or mutable server state). If a corpus or eval-baseline change is involved, the rollback names
      the exact artifact to restore.

## Phase-level / release Definition of Done

Beyond per-PR criteria, a release is done when:

- [ ] A fresh user can `pipx install sprout`, ask a plant question **offline**, and get a **cited
      answer or an honest refusal** — no cloud account.
- [ ] `make eval` regenerates the committed report end to end, offline, byte-identically.
- [ ] The **model card** (`docs/cards/model-card.md`) states the limits plainly and is current.
- [ ] The accessibility ACR (VPAT 2.5 Rev 508) and the dated audit artifacts are regenerated and
      committed.
- [ ] Every CI gate is green on `main`; the release tag is signed and points at that exact commit
      (see [`RELEASE-AND-VERSIONING-STANDARD.md`](../STANDARDS/RELEASE-AND-VERSIONING-STANDARD.md)).
- [ ] `CHANGELOG.md` `[Unreleased]` is promoted to the new version with its date and compare link.
