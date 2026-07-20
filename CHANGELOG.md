# Changelog

All notable changes to **Sprout** are documented here.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). Pre-1.0
(`0.y.z`): the public API may change in a `MINOR` release; breaking changes are called out here.
Per [`SECURITY.md`](SECURITY.md), only the latest minor on the latest major receives security
fixes. Security entries reference the advisory (GHSA) per the portfolio release standard.

## [Unreleased]

### Added
- Deploy-grade app-level server hardening (FIX-10): security headers (CSP, HSTS,
  anti-framing/sniffing), a streaming-safe request-size cap, per-client-IP token-bucket rate
  limits (with a stricter bucket and a concurrency bound on `/api/identify`), all pure-stdlib
  and independent of any reverse proxy — delta checklist at `docs/audits/asvs-l2-delta.md`.

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
- **A deployed zero-server reference surface at
  `https://sprout.chelseakr.com`.** The custom-domain GitHub Pages workflow now builds
  the deterministic TypeScript pipeline and same-origin corpus bundle, publishes the
  interactive assurance UI at the site root, preserves every MkDocs route, and runs a
  structural accessibility check on the assembled artifact. Questions execute entirely
  in the browser and are never sent, saved, or logged; household state remains the
  Family Greenhouse product boundary described in ADR-0015.
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
- **`web-static/` — the deterministic pipeline ported to TypeScript, runnable with zero
  server** (EXP-08, `docs/ideation/03-expansions.md`). `text.ts`, `lexical.ts`
  (BM25), `sha256.ts` + `hashEmbedding.ts` (the hashing embedder), `store.ts`,
  `retrieve.ts` (hybrid dense+BM25 via RRF, species filter, dedup), `generator.ts`
  (extractive generation), `guards.ts` (citation guard, never-certify-"safe" deny-list,
  injection detection, PII redaction), `confidence.ts`, and `lang.ts` mirror their
  Python counterparts line-for-line, running entirely client-side over a static
  `index.json` + `config.json` pair exported by `scripts/export_web_bundle.py`. A
  **cross-language conformance test** (`web-static/test/conformance.test.ts`, fixtures
  generated by `scripts/generate_conformance_fixtures.py`) replays every question in
  `eval/suites/*.yaml` (142 cases across groundedness/safety/refusal/calibration/
  multilingual) through both implementations and asserts byte-identical answers,
  citations, and confidence — wired into CI (`web-static` job) as a merge gate. A
  static reference page (`web-static/public/`) with a web-app manifest and a
  cache-first service worker shows it working end to end; see `web-static/README.md`
  for what's shipped versus deferred (a dedicated browser WCAG/Lighthouse audit,
  PWA icon assets, and subresource integrity remain follow-up work).
- **Facet-coverage answer planner + a `completeness` eval metric** (EXP-01,
  `providers/deterministic.py`, `eval/suites/completeness.py`). The extractive generator now
  splits a multi-part question into per-clause "facets" (`text.extract_facets`) and selects
  sentences greedily to maximise *marginal* facet coverage before raw relevance score, so a
  two-part question ("how often should I water, and does that change in winter?") surfaces
  both clauses instead of three near-duplicate answers to the first one — a single-clause
  question is unaffected (verified byte-for-byte identical output). A new deterministic
  `completeness` suite measures the fraction of a case's authored `expected_facts` (for
  cases with two or more) that the rendered answer actually covers; three multi-facet cases
  were added to `eval/suites/groundedness.yaml` to exercise it. See EXP-01 in
  [`docs/ideation/03-expansions.md`](docs/ideation/03-expansions.md).

- **Tier-A observability for the optional serverless API** (`src/sprout/otel.py`,
  `infra/`). `observability.tier: A` now wires real OTel traces + RED-per-endpoint metrics
  (`REDMiddleware`, W3C `traceparent` propagation, the standard's fixed-second histogram
  buckets), trace-correlated JSON logs (`obs.py`), schema-checked SLO/burn-rate-alert files
  (`slos/*.yaml`, `alerts/burn-rate.yml`, `sprout slo-check`), and a deployable AWS CDK
  stack (`infra/sprout_stack.py`: Lambda via the AWS Lambda Web Adapter, an API Gateway
  HTTP API, a monthly budget alarm). Degrades to a no-op — never a crash — for tier B/C or
  when the `observability` extra isn't installed. See `docs/ROADMAP.md`'s Observability
  tier section for what is unit/e2e-tested versus not yet exercised (a live `cdk deploy`).
- **Explicit season/light context qualifiers** (EXP-05, `answer.py`, `providers/`). Optional
  `--season`/`--light` CLI flags (and matching `season`/`light` fields on `POST /api/chat` and
  `GET /api/chat/stream`) let a user state context like "winter" or "north window" for a single
  request. The words are taken exactly as given — never inferred from locale or the system
  clock — and only nudge which already-cited, already-supported sentence the generator selects;
  they never admit an otherwise-ungrounded sentence, are never treated as a citation, and are
  never persisted anywhere. The same selector-not-fact contract [ADR-0010](docs/adr/0010-photo-plant-id-as-selector-not-fact-source.md)
  built for photo-ID, generalized. The qualifier is echoed back on `Answer.season`/`Answer.light`
  and a localized `Answer.context_note` ("As you stated (winter) — your own context, not a cited
  fact, and not saved."), rendered by the CLI and available to the UI, never folded into the
  answer's cited prose.
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
- **Offline static-vector semantic embedding provider** (`providers/static_embedding.py`,
  `embedding_provider: static`, EXP-03). A third, fully offline, deterministic
  `EmbeddingProvider`: a curated EN/ES plant-care vocabulary table
  (`data/embeddings/clusters.yaml` → `scripts/generate_static_vectors.py` →
  `static_vectors.json`) with a hashing fallback for out-of-vocabulary tokens, so
  synonym/paraphrase and EN/ES cross-lingual questions can score higher than the hashing
  baseline without any network or cloud account. Opt-in, not the offline default — see
  [ADR-0017](docs/adr/0017-offline-static-vector-semantic-embedding-provider.md) for the
  measured eval delta (refusal 0.9118 → 0.9412, over-refusal 10% → 0%, groundedness
  unchanged at 1.000) and why it doesn't yet clear the 0.95 excellence bar.
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
- **Exposure-type detection for the escalation card (FIX-13, scaffold)** (`guards.detect_exposure_type`):
  classifies a safety query's audience — child/human, animal, both, or unspecified — by
  exact-token matching against explicit audience keyword lists (EN + ES, including
  son/daughter/hijo/hija family terms), and a human-poison-control card variant
  (`PromptConfig.human_escalation_card_by_lang`, US Poison Control 1-800-222-1222) exists in
  config for child/human exposure. **Gated off by default** (`human_card_reviewed = False`): the
  animal-line card (ASPCA APCC, Pet Poison Helpline) keeps rendering unchanged for every query,
  including child-ingestion ones, until a poison-control clinician / medical toxicologist signs
  off on the human card's copy in both languages — see
  `docs/audits/human-poison-control-card-review.md` (currently a pending stub, not a completed
  review).
- **Calibrated uncertainty** (`confidence.py`): stated confidence the assistant is held to;
  abstains below threshold rather than guessing.
- **Verbalized, screen-reader-first confidence bands** (`confidence.py`, EXP-06): the raw
  confidence float is joined by a calibrated-language band — "well-supported" or "partially
  supported — verify" — derived from the committed reliability diagram (`derive_band_cutoff`),
  never invented. The band leads and the number follows in every surface (`sprout ask`, the
  `/api/chat/stream` `done` event, the chat UI's `aria-live` meta line), so a screen reader
  announces the calibrated language first while the number stays visible; localized in EN/ES via
  `Config.prompts.confidence_band_labels`.
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
- **Eval score trend ledger across releases** (`eval/history.py`). `sprout eval --release <tag>`
  appends this run's fingerprinted per-suite scores to `docs/audits/eval-history.jsonl`
  (append-only, one line per release — never per PR) and the report gains a trend section
  (per-suite sparkline plus its required accessible data-table equivalent, in both the
  Markdown and HTML reports). A drift rule fails the release gate if any suite declined for
  `--drift-k` (default 3) consecutive releases in a row, even when every individual decline
  was inside `diff_against_baseline`'s tolerance — the single pinned-baseline diff cannot see
  a slow, multi-release bleed. `make eval RELEASE_TAG=<tag>` wires this into the release flow;
  `release.yml`'s tag-triggered re-verification runs the same gate at the tagged commit. See
  `docs/ideation/03-expansions.md` EXP-13.

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

### Fixed
- **Gate-inventory audit (FIX-02, `docs/ideation/02-large-scale-fixes.md`).** New `sprout
  gate-inventory` command (wired into `make verify`/`make audits` and CI) parses
  `docs/ROADMAP.md`'s ledger fresh on every run and fails if any `AUTO` row's `Measured by`
  cell cannot be mechanically resolved to a real Makefile target, CI step, or repo file — the
  "declared but unenforced gate" class of defect this repo has otherwise caught only by manual
  audit. Closed the gaps it found: the `Conformance level` accessibility row overclaimed axe/
  pa11y/Lighthouse as unconditional `AUTO` (only the structural `sprout a11y-check` is
  merge-blocking; corrected to say so, matching `RESPONSIBLE-TECH-AUDITS.md` §E); the optional
  Wilson `--statistical-gate` was described in `DEFINITION_OF_DONE.md` as if always enforced
  when it is off by default in CI (turning it on today fails `multilingual` on sample size, not
  quality — sequenced behind FIX-12); and roughly a dozen `Measured by` cells named a mechanism
  in prose only (e.g. "per-language bundle diff", "transcript-view check") with no such check
  ever wired — each now names its real, resolvable mechanism, including a new
  `tests/test_i18n_parity.py` that actually implements the previously-nonexistent EN/ES
  key-and-placeholder-parity diff.
- **Retrieval scale architecture (FIX-07).** `BM25Index` is now an inverted-postings structure
  (`term -> {doc_index: term_freq}`, `lexical.py`) built **once per corpus** instead of being
  retokenised on every query: `ingest.py` builds it over every chunk and `store.py` persists it in
  `index.json` (format version bumped to 2; a v1 file now fails to load with a message pointing at
  `sprout ingest`). `VectorStore.search` accepts a `candidate_ids` filter and selects with
  `heapq.nlargest` instead of a full sort, so a species-scoped query's dense scan and BM25 scoring
  are both bounded by that species' chunk-id group rather than the whole corpus, and an unfiltered
  query no longer requests `top_k=len(store)`. See `docs/ideation/02-large-scale-fixes.md` (FIX-07)
  and `tests/test_retrieval_scale.py`.

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
