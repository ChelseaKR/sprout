# Changelog

All notable changes to **Sprout** are documented here.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). Pre-1.0
(`0.y.z`): the public API may change in a `MINOR` release; breaking changes are called out here.
Per [`SECURITY.md`](SECURITY.md), only the latest minor on the latest major receives security
fixes. Security entries reference the advisory (GHSA) per the portfolio release standard.

## [Unreleased]

### Added
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

### Changed
- `create_app` accepts an optional `identifier` override (mirroring the existing `assistant`
  override) so the grounded photo path is testable offline.
- New `identification` and `reminders` config blocks (`config/sprout.yaml`); `identify` optional
  dependency extra (`httpx`).

## [0.1.0] - 2026-06-22

Initial reference-implementation release: an offline-first, grounded, evaluated, multilingual
(EN/ES) houseplant-care RAG assistant, with the public evaluation harness as the headline artifact.

### Added
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
  `demo`) and a JSON/SSE API server.
- **Governance and process:** `make verify` reproducing the full CI gate set
  (`lint · type · test ≥90% · security · eval · a11y`); CONTRIBUTING, SECURITY, CODE_OF_CONDUCT,
  DEFINITION_OF_DONE; CODEOWNERS over the safety guardrails; ADRs; dependabot; SHA-pinned Actions;
  Conventional Commits + DCO sign-off; the `claude/* → develop → main` branch model.
- **Docs:** ARCHITECTURE, THREAT-MODEL, ACCESSIBILITY (+ ACR via VPAT 2.5 Rev 508), ROADMAP,
  RESPONSIBLE-TECH-AUDITS, model and data cards, and the committed `docs/audits/` eval artifacts.

### Security
- Offline-by-default posture (no auth, no network, no persisted user queries) establishing the
  **OWASP ASVS L1** baseline; secrets via environment only; pip-audit, gitleaks, and Semgrep wired
  into CI. No advisories in this release.

[Unreleased]: https://github.com/ChelseaKR/sprout/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ChelseaKR/sprout/releases/tag/v0.1.0
