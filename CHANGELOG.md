# Changelog

All notable changes to **Sprout** are documented here.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). Pre-1.0
(`0.y.z`): the public API may change in a `MINOR` release; breaking changes are called out here.
Per [`SECURITY.md`](SECURITY.md), only the latest minor on the latest major receives security
fixes. Security entries reference the advisory (GHSA) per the portfolio release standard.

## [Unreleased]

- **The published site could not say where its pages were.** A technical SEO
  audit of sprout.chelseakr.com found `/robots.txt` a 404, so the sitemap mkdocs
  already writes was advertised to nothing; the page served at `/` carrying no
  canonical and no share card, because `pages.yml` copies `web-static/public`
  over mkdocs' own index and nothing local reproduced that; all 52 published
  URLs shipping one identical `site_description`; and
  `/audits/eval-report.html` published, reachable, and in neither the sitemap
  nor a `noindex` beside `/audits/eval-report/`, which is the same run at a
  second address.

  - `docs/robots.txt` is copied to the site root by mkdocs and advertises the
    sitemap. Nothing is disallowed: every page this site publishes is a page it
    means to publish.
  - `web-static/public/index.html` carries a canonical and the OpenGraph and
    Twitter tags, repeating the page's own title and description rather than a
    second set written for a card. There is deliberately no `og:image`: the
    project ships no image asset, and an `og:image` naming a file that is not
    there is worse than none at all.
  - `docs_hooks/page_description.py` gives each documentation page the
    description its own opening paragraph already states. It writes no new copy,
    it leaves a page that declares its own description alone, and it escapes what
    it produces, because mkdocs-material interpolates the value straight into an
    attribute and an ADR quoting its own model card closed that attribute early.
    52 pages, 52 distinct descriptions.
  - The standalone HTML eval report is `noindex`. It opens from a CI download or
    a local checkout; the address worth indexing is the docs page rendered from
    its Markdown twin.
  - `sprout site-check` and `make site-check` are the gate, in the same shape as
    `sprout a11y-check`: a pure function over a built directory, no network. It
    checks self-referencing https canonicals, unique non-empty titles and
    descriptions, complete share cards that agree with the page, `robots.txt`
    naming the sitemap and no path the site does not serve, and every built page
    either listed in the sitemap or saying it is not for indexing. It is in
    `make verify` and in `pages.yml`, and unlike anything before it, `make
    site-check` builds what is actually deployed: mkdocs' output with
    `web-static/public` copied over it. `tests/test_site_meta.py` breaks one
    property at a time and asserts each is caught, including that an empty tree
    reports having checked nothing rather than reporting success.

- **The secret scanner was running with no rules at all (ISO 25010: Security /
  confidentiality).** `.gitleaks.toml` declared only an `[allowlist]`. gitleaks treats a
  config it finds as the *whole* configuration, so without `[extend] useDefault = true`
  the default rule set was never loaded: every gitleaks run in this repository — `make
  security`, the `gitleaks/gitleaks-action` CI job, and the pre-commit hook — scanned
  with zero detectors and reported "no leaks found" because there was nothing it could
  find. Measured with a control on 2026-08-28: a file holding a well-formed `ghp_` token
  is `leaks found: 1` under gitleaks' defaults and `no leaks found` under this
  repository's config. The full commit history is clean with the defaults restored, so
  nothing was missed; the gate simply could not have caught it.
  `tests/test_secret_scanning.py` now plants a synthetic credential and asserts the
  committed config finds it, and skips rather than passes where gitleaks is absent.

- **`make security` announced a real gitleaks finding as the tool being missing, and
  exited 0.** The recipe was `command -v gitleaks && gitleaks detect || <fallback>`, and
  a gitleaks that finds a secret exits 1 exactly like one that is not installed.
  Measured with a stub reporting `leaks found: 1`: the recipe printed "gitleaks not
  installed locally" and the target went green. The install check and the scan are now
  separate statements.

- **SAST read 80 of the repository's 142 Python files, then 0 of the tests.** `semgrep
  scan --config p/python --error src` named one directory, leaving `tests/`, `scripts/`,
  `eval/`, `examples/` and `infra/` — the gate machinery included — unscanned in both
  `make security` and CI. Adding them to the command was not enough: semgrep's default
  `.semgrepignore` excludes `tests/`, and `semgrep scan ... tests` reported success
  having scanned **0 files**. A committed `.semgrepignore` fixes that. The scan now
  reads 146 files. `tests/test_security_gate.py` derives the required roots from `git
  ls-files` and fails if one is missing from either side or re-excluded.

- **A toxicity fact could render in Spanish with no vet or poison-control routing
  ([#107](https://github.com/ChelseaKR/sprout/issues/107)).** The routing decision asked
  whether the answer cited a chunk whose topic was the literal `"toxicity"`. A chunk's
  topic is its slugified Markdown heading, and 8 of the 16 Spanish corpus documents head
  that section `## Toxicidad`, 7 of them ASPCA-listed as toxic to pets. For those, the
  content-based check could never fire, so the mandatory escort survived only where the
  keyword classifier also happened to fire. Reproduced on the committed corpus: a
  Spanish question about oral irritation and drooling rendered Monstera's toxicity
  paragraph with `is_safety_query=False` and no routing. `answer.py` and `answer.ts` now
  read a shared bilingual slug set (`chunk.SAFETY_TOPIC_SLUGS` /
  `web-static/src/topics.ts`), which `propose.py` already had for this exact hazard. The
  committed eval failure `safety-025` ("no vet/poison routing", Spanish, peace lily) now
  passes: the `safety` suite goes 0.976 to 1.000. Calibration ECE moves 0.126 to 0.134,
  still inside the 0.15 gate.

- **The browser could not receive a fitted confidence logistic
  ([#108](https://github.com/ChelseaKR/sprout/issues/108)).** `confidence.py` reads
  `cfg.confidence.fit` when `sprout fit-confidence` (ADR-0016) has written one, but
  `export_web_bundle.py` never emitted it, TypeScript's `ConfidenceConfig` had no field
  for it, and `scoreConfidence()` never read config at all. No fit is committed, so
  nothing diverged yet; the first use of the documented workflow would have made
  sprout.chelseakr.com compute a different confidence, and different abstain decisions,
  than the CLI for the same question, silently. The fit is exported, declared, and read,
  with the ADR-0012 defaults as the fallback on both sides.

- **`sprout ci-parity-check` lost a recipe at a comment, and could not read a Makefile
  variable.** `_make_target_recipes` treated any column-zero line as the end of a
  recipe, so a `#` comment between two recipe lines dropped everything after it from the
  diff — `make` does not end a recipe there, so the two disagreed about what the recipe
  even was. `_resolve_make_vars` read exactly `PY` and `CONFIG`, so any other `$(VAR)`
  reached the diff unexpanded and could never match CI's expansion of it. Both are
  fixed, and the gitleaks allowlist entry is narrowed to the `if`-form so the old
  `&&`/`||` shape cannot return unnoticed.

- **`release.yml` ran the tagged commit's own gate inside main's Actions cache scope
  (ISO 25010: Security / integrity).** The `codeql` workflow has been failing on the default
  branch since the 2026-08-24 scheduled run with one error-severity finding:
  `actions/cache-poisoning/poisonable-step` at `.github/workflows/release.yml:50` — "Potential
  cache poisoning in the context of the default branch due to privilege checkout of untrusted
  code from `needs.authorize.outputs.release-commit` (`workflow_dispatch`)". A
  `workflow_dispatch` run executes in the context of the default branch and therefore holds
  **write** access to main's cache scope; the `verify` job then checks out the release commit
  and runs that commit's `make verify`, so checked-out code executed somewhere every branch cut
  from main can later restore from. GitHub's guidance for this query is explicit: "Never run
  untrusted code in the context of the default branch."
  The trigger is now `push: tags: ["v*"]`, which scopes the run's cache to `refs/tags/<tag>`,
  so the gate cannot write anything main will restore. This restores the trigger the file's own
  comments still described (`# ... this whole workflow triggers on 'push: tags'`), stale since
  `719c8db` (#79) switched to `workflow_dispatch` and introduced the finding. **The `authorize`
  trust boundary is unchanged** and remains the real control: the tag must still be annotated,
  signed by an allowed signer, stable SemVer, and on main before it resolves to a release
  commit; only the tag name's source changes (`inputs.tag` → `github.ref_name`).
  Note this is a release-process change: a release now starts when a `v*` tag is pushed rather
  than from a manual dispatch. Verified with the CodeQL 2.26.3 bundle locally against
  `scripts/codeql_gate.py`: 1 error-severity finding before, 0 after. An `environment:` gate was
  tested first and does **not** clear it — every `ControlCheck` in the query only covers
  `pull_request_target`/`workflow_run`/`issue_comment`-class events, never `workflow_dispatch`.
  The alert was not dismissed or suppressed.
- **The container image carried five fixable HIGH CVEs, and could not start
  (ISO 25010: Security / vulnerability management, plus Reliability).** `container-scan`
  had been red on both of its last two weekly runs (2026-08-19, 2026-08-26) on
  `Total: 3 (HIGH: 3)` from Debian and `Total: 2 (HIGH: 2)` from Python packages:
  - `CVE-2026-14456` (HIGH) in `libssl3t64`, `openssl`, and `openssl-provider-legacy`
    `3.5.6-1~deb13u2`. `trixie-security` already publishes the fixed `3.5.7-1~deb13u2`;
    the upstream `python:3.12-slim` tag simply lags it (a freshly pulled base image on
    2026-08-26 still shipped 3.5.6). The Dockerfile now applies pending Debian security
    updates, so this is fixed rather than waited on.
  - `CVE-2025-47273` (setuptools 70.3.0) and `GHSA-6v7p-g79w-8964` (msgpack 1.1.2). These
    were never direct dependencies -- `uv.lock` already pins the fixed msgpack 1.2.1 and
    does not carry setuptools at all. They came from **pip's vendored copies**: the base
    image's bundled pip 25.0.1 and, in the venv, pip 26.2.1 pulled in transitively by
    `pip-audit`, both of whose `_vendor/vendor.txt` pin `setuptools==70.3.0`. The image
    was installing the entire dev toolchain (pytest, mypy, ruff, coverage, hypothesis,
    cyclonedx, pip-audit) into a *runtime* container, because `uv sync` installs the dev
    group by default. Both syncs are now `--no-dev`, and the interpreter's bundled pip is
    removed, since uv is the only installer this image uses. Nothing that runtime code can
    reach is lost: httpx, sigstore, and opentelemetry are all imported lazily inside the
    optional cloud-provider, corpus-signing, and observability seams.

  Verified by building the image and scanning it with the same Trivy 0.70.0 and the same
  flags CI uses: **5 HIGH before, 0 after**. No `.trivyignore` and no `ignore-unfixed`
  widening were used; every finding is fixed at the package level.

  While verifying, the image turned out to be **non-startable on `main`, and to have been
  so for every build**: the `sprout` user is created with `--no-create-home`, so `$HOME`
  (`/home/sprout`) does not exist, and the `uv run` entry point died on
  `Failed to initialize cache at /home/sprout/.cache/uv: Permission denied` before the
  server started. `container-scan` only builds and scans, so nothing ever ran the image
  and nothing caught it. The entry point is now the already-built venv console script,
  which also removes `uv run`'s attempt to re-sync the environment at container start (a
  network call in an image explicitly built to need none). Confirmed by running the image
  with `--network none`: `/livez`, `/readyz`, and `/health` return 200 and `/api/chat`
  returns a grounded, cited toxicity answer.

- **Fixed a stale-claim bug class in the README (issue #97): the enforced CI floor and the
  last measured value were collapsed into one number.** `README.md`'s AI Evaluation row read
  "judge-calibration ... gated at agreement 0.955 / κ 0.906" — those are the values the last
  run *achieved*, not the thresholds it had to clear (`MIN_AGREEMENT = 0.8`, `MIN_KAPPA = 0.6`
  in `src/sprout/eval/calibration.py`). A regression from 0.955/0.906 down to 0.81/0.61 would
  still pass CI and the README would still claim the gate sits at 0.955/0.906 — a 15-point and
  30-point margin between what the README promised and what the pipeline enforced. Every other
  doc in the repo already stated floor and measurement separately (`docs/ROADMAP.md`,
  `docs/audits/judge-calibration.md`, `docs/audits/gate-inventory.md`); the README was the one
  exception, and the one document `docs/claims.yaml`'s drift guard did not reach.
  `README.md:139` now states the enforced floor (agreement ≥ 0.80, κ ≥ 0.60) and the last
  measured value (0.955 / 0.906) as separately labeled claims. A second, same-root-cause drift
  in the same section — "120+ YAML cases across five suites" — undercounted: the harness
  gates on **8** suites (`calibration, completeness, conversation, groundedness, multilingual,
  refusal, safety, toxicity-coverage`, per `docs/audits/eval-report.json`), not 5; the suite
  table and repo-layout tree diagram are corrected and the table no longer omits
  `completeness`, `conversation`, and `toxicity-coverage`.
  `sprout claims-check` (`docs/claims.yaml`) now covers the README: six new claims
  (`readme-refusal-target`, `readme-judge-calibration-floor-agreement`,
  `readme-judge-calibration-floor-kappa`, `readme-coverage-floor`, `readme-eval-suite-count`,
  `readme-eval-suite-names`) pin these values to their live source of truth, gaining two new
  resolver kinds along the way: a generalized `suite:` source (`suite:calibration.min_agreement`
  / `suite:calibration.min_kappa`, alongside the existing `suite:refusal.threshold`) and
  `eval-report:suites.names` / `eval-report:suites.count` (the report's real suite list/count)
  and `pytest:cov-fail-under` (the real `--cov-fail-under` value in `pyproject.toml`). The
  registry deliberately does **not** pin the *measured* 0.955/0.906 — unlike a floor, a
  measurement is expected to legitimately drift run to run; pinning it would make the gate
  brittle rather than honest. `docs/claims.yaml`'s header comment documents all three new
  source kinds for the next claim added against them.

- Every `uv sync --frozen` is now `uv sync --locked`, across `ci.yml`,
  `release.yml`, `pages.yml`, `corpus-freshness.yml`, `redteam.yml`, both
  Dockerfiles, and the CI-parity test fixture. `--frozen` never reads
  `pyproject.toml`, so it installs the locked set and exits 0 when the lock no
  longer satisfies the manifest; `--locked` makes the comparison and exits 1.
  Nineteen invocations across the repository were the weaker flag, which means
  a drifted lock could have gone through CI, the docs build, the red-team run,
  the release, and both images without one of them saying so.
- The README standards-conformance table declares all fifteen standards and is
  now machine-readable. Performance, Incident Response, Data Governance, and AI
  Development Measurement had no row, so none of the four was recorded as met,
  exempt, or a gap; the first three point at gates and artifacts already in the
  repository (`tests/test_latency.py`, `slos/`, `SECURITY.md`, `docs/cards/`)
  with their remaining shortfalls named, and AI Development Measurement is
  declared an open gap. The state column was headed "Applies" and filled with
  check marks, and the Quality & Metrics row carried a parenthetical in its
  label, which together made the table unparseable; the header is "State", the
  verdicts are the word "Applies", and the parenthetical moved into the posture
  cell. The phrase "gap tracked" reads as a reference to an issue tracker,
  which is not where this repository records gaps, so those notes now say
  "open gap" and name `docs/ROADMAP.md`. No row's meaning changed.

- Release authorization now runs from reviewed `main` through the immutable
  portfolio authorizer; verification and builds use the exact selected commit,
  while separate checkout-free jobs recheck the tag object before PyPI and
  GitHub Release publication.

### Changed
- Moved the offline deterministic quickstart into the README's opening screen,
  before the product and safety deep dive.

### Added
- **The SME corpus-contribution path (research item E5): `sprout propose`.** A contributor
  proposes a new species as one self-contained YAML file — the passage in every supported
  language, its provenance (source, license, `fetch_date`, topic), the eval case the passage
  must satisfy, and a representational-harm checklist — from `sprout propose template`, or via
  the new no-code **corpus proposal issue form**, which collects the parts only a contributor
  can supply and which a maintainer transcribes into a proposal file (a deliberate subset of
  the schema, not a field-for-field mirror of it). `sprout propose check` reviews it offline and
  deterministically: license allowlist, ISO dates, E7's citation-freshness SLA applied against
  the topic the *passage* carries so toxicity prose gets the stricter SLA, every-language
  coverage with EN/ES structural parity, the corpus's canonical topic taxonomy, EXP-12's chunk
  lint reused rather than reimplemented, the shipped never-certify-"safe" guard run over every
  proposed sentence, an EN/ES medicinal-or-edibility claim scan that *cross-checks* the harm
  checklist instead of trusting it, and an eval case that must load, cite one of the proposed
  documents, and assert only facts appearing verbatim in the passage. Merge-blocking on errors
  for **every submitted proposal, not only the committed example**: `make propose-check` and the
  `propose-check` step of the `eval-a11y` CI job run `sprout propose check` with no arguments,
  which discovers every proposal-shaped file in the repository, reports one filed outside the
  declared submission locations (`proposals/`, `examples/corpus-proposal/`) as an error rather
  than skipping it, and fails rather than passing if it discovers nothing at all. A mechanically
  clean proposal carrying toxicity prose reports `ready-for-expert-review` — the veterinary
  toxicologist / native-Spanish review this repo already requires, recorded as a machine-checked
  state rather than assumed; the `expert_review` sign-off that clears it must be a committed
  Markdown artifact under `docs/audits/` naming the species, reviewer, and sign-off date, so the
  strongest gate cannot be discharged by pointing at any file that happens to exist. Worked
  example: `examples/corpus-proposal/` (*Chamaedorea elegans*, EN + ES, zero findings). Nothing
  is ever written to `corpus/`.
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
- **Local review console for flagged/refused answers** (`review.py`, EXP-17). An opt-in,
  **off-by-default** queue that captures `Answer.low_confidence`/`Answer.refused` traces for
  maintainer labeling ({correct, incomplete, wrong-plant, should-have-refused}), plus three
  exporters that turn labeled traces into `eval/judge_probes.yaml`-shaped judge probes, a
  confidence re-fit dataset (feeds FIX-08), and draft eval cases for `eval/suites/` curation —
  never written directly, always a standalone file for a maintainer to review and hand-merge.
  New `sprout review` sub-commands (`queue`/`show`/`label`/`run`/`export`), wired into `sprout
  ask` behind `ReviewConfig.enabled` (`config.py`). Stores question text locally on the
  maintainer's own machine only; see its own DPIA delta in
  [`RESPONSIBLE-TECH-AUDITS.md`](docs/RESPONSIBLE-TECH-AUDITS.md) §C and
  [ADR-0020](docs/adr/0020-local-review-console-for-flagged-answers.md).
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
- **`sprout.eval` as a plugin-based package** (`eval/suite.py`, ADR-0019): third-party suites are
  discovered via the `sprout.eval.suites` `importlib.metadata` entry-point group, alongside the
  five built-in suites, fail-closed on a name collision. The public plugin surface — `Dataset`,
  `Judge`, `Suite`/`EvalContext`, `SuiteResult`, `MetricDefinition`, and the registry — is frozen
  and re-exported with an explicit `__all__` from `sprout.eval`, with a semver commitment. Proven
  by a worked, independently pip-installable second-domain example at
  `examples/herb-garden-plugin/` (a culinary-herb corpus + a domain-specific suite, zero changes
  to this repo's source, committed reproducible report).
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
