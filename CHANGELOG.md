# Changelog

All notable changes to **Sprout** are documented here.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). Pre-1.0
(`0.y.z`): the public API may change in a `MINOR` release; breaking changes are called out here.
Per [`SECURITY.md`](SECURITY.md), only the latest minor on the latest major receives security
fixes. Security entries reference the advisory (GHSA) per the portfolio release standard.

## [Unreleased]

### Fixed
- Re-armed CodeQL on pull requests, pushes to `main`, and a weekly schedule; corrected the
  Standards Conformance label consumed by the portfolio checker; and assigned the homoglyph
  hardening decision its unique ADR number.
- Made the tuning-scope gate compare ordinary Python tunable files by parsed syntax, so
  comment/format-only documentation edits no longer demand a fabricated `Tunes-Against` case;
  semantic edits and invalid syntax remain fail-closed.

> **2026-07-05 correction:** this project has **never been tagged or released** — `git tag`
> returns nothing, and no release workflow has ever run. A previous version of this file carried
> a `[0.1.0] - 2026-06-22` released section, `CITATION.cff` claimed `date-released: 2026-06-22`,
> and a locally-built (never-published) wheel sat in `dist/`. That was a documentation defect
> (REL-03): a version was declared released that was never tagged, published, or verified. That
> section's content is folded back into `[Unreleased]` below, un-dated, until an actual signed
> `v0.1.0` tag is cut and `release.yml` runs end to end. See the 2026-07-05 remediation execution
> log at the end of this repo's audit trail for the full discrepancy.

An offline-first, grounded, evaluated, multilingual (EN/ES) houseplant-care RAG assistant, with
the public evaluation harness as the headline artifact.

### Added
- **Family Greenhouse read-only integration:** HMAC-authenticated, replay-bounded API contract
  accepting only minimized household selectors, with strict provenance, PII sentinel tests,
  persisted citations, a scoped ASVS L2 review, and `sprout.chelseakr.com` custom-domain support.
- **Mechanical enforcement of the "tune only against committed eval failures" rule**
  (`src/sprout/eval/tuning_scope.py`, `sprout check-tuning-scope` CLI command, `tuning-scope` CI
  job). Previously a sentence in `docs/ROADMAP.md` Phase 3; now a fail-closed gate — a change
  touching retrieval/generation/guards/calibration/lexical/config surface must carry a
  `Tunes-Against: <case-id>[, ...]` commit trailer whose ids already appear in the committed
  `docs/audits/eval-baseline.json` `failing_examples`, so tuning can only be justified against a
  failure that was public before the change, never the held-out set or a local-only run. See
  [`CONTRIBUTING.md`](CONTRIBUTING.md#tuning-discipline--eval-failures-only-never-the-held-out-set).
- **False-positive-safe tuning classification:** comment-only YAML is compared semantically, and
  only the exact named operational lifecycle wrapper around an otherwise-identical provider
  constructor is normalized. The lifecycle module's initial addition is admitted once by exact
  digest; every future hunk is gated. Model, prompt, decoding, real-config, retrieval/guard,
  lifecycle-output, and unknown provider edits remain fail-closed, with adversarial regression
  tests for each category. Case authorization is read from the branch merge-base baseline.
- **Photo-based plant identification → grounded care lookup** (`identify.py`,
  `providers/plantnet.py`). A photo is identified into candidate species, the best confident
  match is resolved to a species **already in the cited corpus**, and that species is routed
  back through the *unchanged* grounded pipeline — so every rendered claim is still cited and
  toxicity still routes to a vet. The identification is labelled "a visual match, not a cited
  fact" and never enters the answer's sentences. Offline by default (no network, always falls
  back to "type the plant's name"); a `plantnet` provider calls the allowlisted Pl@ntNet API
  with its key from `PLANTNET_API_KEY` (env only). New `sprout identify` command and
  `POST /api/identify`. See [ADR-0010](docs/adr/0010-photo-plant-id-as-selector-not-fact-source.md).
- **Local-first care reminders** (`reminders.py`). Watering/fertilizing/etc. reminders tied to a
  plant (and optionally the citation that motivated them), stored in one JSON file on the user's
  own machine — offline, opt-in, no database, content never logged. New `sprout remind`
  sub-commands (add/list/due/done/remove), reminder endpoints under `/api/reminders`, and an
  accessible reminders panel in the chat UI. See
  [ADR-0011](docs/adr/0011-local-first-reminder-scheduler.md).
- **Grounded extractive assistant.** Retrieval-mandatory pipeline
  (`guards(input) → retrieve → extractive generate → guards(output) → confidence/abstention`)
  that answers only from the cited corpus, with an inline citation to the governing passage and its
  fetch date — or an honest "not covered" refusal.
- **Hybrid retrieval** (`retrieve.py`): pure-Python BM25 + dense `HashingEmbedding`, with a
  species/topic filter and a confidence threshold that gates weak matches into abstention.
- **Offline-by-default, deterministic generator** (`HashingEmbedding` + BM25 +
  `ExtractiveGenerator`): the whole project, including the eval, runs with **no network and no cloud
  account**. Groundedness is **100% by construction** (extractive + citation guard).
- **Safety and citation guards** (`guards.py`): a post-generation **citation guard** (every rendered
  sentence resolves to a retrieved passage) and a **never-certify-"safe"** deny-list that blocks
  "safe"/"non-toxic" certifications in EN and ES and routes ingestion questions to vet /
  poison-control.
- **Calibrated uncertainty** (`confidence.py`): stated confidence the assistant is held to;
  abstains below threshold rather than guessing.
- **English/Spanish parity** with enforced |EN − ES| ≤ 5pp pass-rate parity and mirrored
  facts/citations.
- **Provider seam** (`providers/`): deterministic offline generator as default; a Claude-on-Bedrock
  generator (answer model: Claude Haiku) behind a config switch as the production seam.
- **The eval harness** (`src/sprout/eval/`): five suites — **groundedness, safety, calibration,
  refusal, multilingual** — scored by deterministic checks blended with an **LLM-as-judge**
  (judge model: Claude Sonnet, deliberately ≠ the answer model). Reports emit Markdown + accessible
  HTML + JSON, plus JUnit and SARIF; runs are content-hashed and **byte-identical for identical
  inputs**. Fail-closed loader (`eval/dataset.py`) rejects hash mismatches, malformed cases, and
  empty suites.
- **Synthetic, CC0-1.0 corpus** (`corpus/`) with a dated, licensed `manifest.yaml`; chunked by care
  topic with source/license/fetch-date metadata; UI shows "based on references as of &lt;date&gt;."
- **Accessible web UI** (`web/dist/`): framework-free WCAG 2.2 AA chat interface with a non-chat
  transcript/alternate view; SSE token streaming; copyable citations.
- **`sprout` CLI** (`ingest`, `ask`, `serve`, `eval`, `eval-baseline`, `calibrate`, `a11y-check`,
  `ci-parity-check`, `demo`) and a JSON/SSE API server.
- **Governance and process:** `make verify` reproducing the full CI gate set
  (`lint · type · test ≥90% · security · eval · a11y · docs · workflow-lint · ci-parity-check`);
  CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, DEFINITION_OF_DONE; CODEOWNERS over the safety
  guardrails; ADRs; dependabot; SHA-pinned Actions; Conventional Commits + DCO sign-off; the
  `claude/* → develop → main` branch model.
- **Docs:** ARCHITECTURE, THREAT-MODEL, ACCESSIBILITY (+ ACR via VPAT 2.5 Rev 508), ROADMAP,
  RESPONSIBLE-TECH-AUDITS, model and data cards, and the committed `docs/audits/` eval artifacts.
- **Promptfoo red-team config** (`eval/redteam/promptfooconfig.yaml`) covering OWASP Top 10 for
  LLM Applications (LLM01-LLM10:2025) against the live `POST /api/chat` pipeline, in EN and ES.
  Fills the gap `docs/ROADMAP.md` had been carrying since 2026-07-05 ("planned — no Promptfoo
  config exists"); complements the manual, dated exercise in
  `docs/audits/red-team-2026-06-22.md`. Advisory `redteam` CI job (opt-in, needs
  `ANTHROPIC_API_KEY`, excluded from `ci-gate`) added to `.github/workflows/ci.yml`; see
  `eval/redteam/README.md`.

### Changed
- `create_app` accepts an optional `identifier` override (mirroring the existing `assistant`
  override) so the grounded photo path is testable offline.
- New `identification` and `reminders` config blocks (`config/sprout.yaml`); `identify` optional
  dependency extra (`httpx`).
- **Accessibility CI gates are now fully merge-blocking.** `pa11y-ci` (axe-core + htmlcs runners)
  lost its `continue-on-error: true` / `|| true` advisory-only status, and a new `lighthouse` job
  runs Lighthouse's accessibility category (threshold 0.95) against the chat UI and the HTML eval
  report — previously not wired into CI at all. Both jobs are now required by `ci-gate`. Fixed the
  one real finding this surfaced: the empty-state reminders table left header cells with zero data
  rows (`axe`'s `th-has-data-cells`), so the table is now hidden until it has at least one
  reminder, matching the existing plain-language empty-state message.
- **CI/local parity is now mechanically checked, not just asserted** (`ci-parity-no-mechanical-diff`,
  ROADMAP.md): `src/sprout/ci_parity.py` / `sprout ci-parity-check` diffs
  `.github/workflows/ci.yml`'s required-job commands against their `Makefile` counterparts, wired
  as `make ci-parity-check` (a `make verify` prerequisite) and a `ci-parity` CI job (a `ci-gate`
  dependency). Its first run surfaced two real gaps — the `docs` and `zizmor` (workflow-SAST)
  `ci-gate` jobs had no local equivalent in `make verify` — now closed with new `docs` and
  `workflow-lint` prerequisites on `verify`.

### Fixed
- **`docs/ROADMAP.md` Phase 3 status (2026-07-08):** the "Outstanding" bullet still listed
  "commit the ACR and the OWASP-LLM red-team report" as not-yet-done, even though both
  `docs/accessibility/ACR.md` (VPAT 2.5 Rev 508) and `docs/audits/red-team-2026-06-22.md`
  (OWASP LLM01–LLM10:2025 coverage) had already been committed in the 2026-07-05 conformance
  pass. Moved to "Done" with an honest caveat preserved: the red-team report remains a manual,
  dated exercise until an automated Promptfoo `redteam` run is wired and promoted into the
  blocking `ci-gate` (tracked in the "Red-team (OWASP LLM01–LLM10)" ledger row).

### Security
- Offline-by-default posture (no auth, no network, no persisted user queries) establishing the
  **OWASP ASVS L1** baseline; secrets via environment only; pip-audit, gitleaks, and Semgrep wired
  into CI. No advisories to date.
- **Standards conformance remediation (2026-07-10, SEC-11/SEC-28):** removed a stray `|| true`
  documentation artifact from the `pip-audit` step name that a mechanical conformance checker was
  misreading as a silenced gate (the gate itself was never muted); removed the redundant `|| true`
  on the `pa11y-ci` step now that its one real finding (an empty `<table>` with header cells and no
  data cells, WCAG `th-has-data-cells`) is fixed — the reminders table and the "No reminders yet"
  message are now mutually exclusive in the DOM instead of both always being present
  (`web/dist/index.html`, `web/dist/app.js`); added a Trivy CVE scan (`container-scan.yml`,
  CRITICAL,HIGH, matching `habitable`'s pattern) for the Dockerfile image, which currently scans
  clean.

<!-- No versioned sections below: no tag has ever been cut (`git tag` is empty). Add
     `[X.Y.Z] - YYYY-MM-DD` here, with its own compare link, only once `git tag -s vX.Y.Z` has
     actually been pushed and release.yml has run. -->
