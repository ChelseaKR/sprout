# Project Scope

Last reviewed: 2026-07-08. Base branch: `main`.

This file is a plain-language map of the project as it exists on `main`. It does not replace the README, roadmap, audit docs, or source comments. It points to them so a reviewer can see the whole shape without reading every file first.

## What This Project Is

Sprout is a plant-care answer engine built around a controlled corpus. It produces grounded care guidance, supports English and Spanish content, evaluates answer behavior, and refuses unsupported or unsafe claims.

Package metadata checked in this pass:

- Python package `sprout` for Python `>=3.12`.

## Who It Serves

- Plant owners asking care questions from a bounded, cited source set.
- Maintainers testing deterministic RAG-style answer behavior without a cloud dependency.
- Reviewers checking toxicity, safety language, accessibility, and evaluation reports.

## What It Covers

- A plant-care corpus with English and Spanish files.
- Configuration for retrieval, answer behavior, and evaluation.
- Source code for deterministic answers, retrieval, rendering, and checks.
- Docs for architecture, roadmaps, threat model, audits, ADRs, a11y, and research.
- Model/data cards, eval reports, and tests.

## How It Is Put Together

- corpus/ contains plant care facts and manifests.
- config/ holds runtime settings.
- src or package code contains retrieval, answer, and evaluation paths.
- docs/ contains architecture, ADRs, audits, accessibility, and planning docs.
- tests/ covers answer behavior and safety checks.

Observed source and operations surfaces:

- `Dockerfile`
- `Makefile`
- `config/`
- `corpus/`
- `eval/`
- `pyproject.toml`
- `scripts/`
- `src/`
- `web/`

GitHub workflow files checked:

- `.github/workflows/ci.yml`
- `.github/workflows/codeql.yml`
- `.github/workflows/release.yml`

## Trust Boundaries

- Care answers should stay within the corpus and cite what supports them.
- Plant toxicity language is conservative and does not certify safety.
- Spanish parity and accessibility are part of the user surface, not launch extras.

## Outside This Scope

- It is not veterinary, medical, or emergency guidance.
- It does not identify plants from photos as a fact source unless a future feature explicitly limits that role.
- Real expert review is still needed before treating safety copy as final.

## Docs And Evidence Checked

This pass checked 76 hand-authored doc or metadata files, 19 test files, and 3 workflow files on `main`. The count excludes vendored provider licenses, dependency folders, generated cache files, and large generated artifact history.

Large content groups were counted rather than listed file by file:

- `corpus/processed/`: 32 files

Primary docs checked:

- `.github/PULL_REQUEST_TEMPLATE.md`
- `CHANGELOG.md`
- `CITATION.cff`
- `CLAUDE.md`
- `CODE_OF_CONDUCT.md`
- `CONTRIBUTING.md`
- `DEFINITION_OF_DONE.md`
- `LICENSE`
- `NOTICE`
- `README.md`
- `SECURITY.md`
- `docs/ADAPT.md`
- `docs/ARCHITECTURE.md`
- `docs/RESEARCH-ROADMAP.md`
- `docs/RESPONSIBLE-TECH-AUDITS.md`
- `docs/ROADMAP.md`
- `docs/THREAT-MODEL.md`
- `docs/USER-RESEARCH.md`
- `docs/a11y/STATEMENT.md`
- `docs/accessibility/ACR.md`
- `docs/adr/0000-record-architecture-decisions.md`
- `docs/adr/0001-offline-deterministic-generator-as-default.md`
- `docs/adr/0002-hybrid-bm25-plus-dense-retrieval.md`
- `docs/adr/0003-extractive-generation-and-citation-guard-for-100pct-groundedness.md`
- `docs/adr/0004-never-certify-safe-output-guard.md`
- `docs/adr/0005-calibrated-abstention-thresholds.md`
- `docs/adr/0006-eval-harness-in-repo-as-sprout-eval.md`
- `docs/adr/0007-src-layout-and-90pct-coverage-floor.md`
- `docs/adr/0008-asvs-l1-for-offline-mode.md`
- `docs/adr/0009-judge-model-differs-from-answer-model.md`
- `docs/adr/0010-photo-plant-id-as-selector-not-fact-source.md`
- `docs/adr/0011-local-first-reminder-scheduler.md`
- `docs/adr/0012-deny-list-homoglyph-folding.md`
- `docs/adr/0012-recalibrated-abstention-thresholds-supersedes-0005.md`
- `docs/audits/ai-risk-register.md`
- `docs/audits/eu-ai-act-classification.md`
- `docs/audits/eval-report.md`
- `docs/audits/iso42001-soa.md`
- `docs/audits/judge-calibration.md`
- `docs/audits/red-team-2026-06-22.md`
- `docs/cards/data-card-corpus.md`
- `docs/cards/model-card.md`
- `docs/ideation/02-large-scale-fixes.md`
- `docs/index.md`
- `src/sprout/data/corpus/processed/aloe.es.md`
- `src/sprout/data/corpus/processed/aloe.md`
- `src/sprout/data/corpus/processed/boston-fern.es.md`
- `src/sprout/data/corpus/processed/boston-fern.md`
- `src/sprout/data/corpus/processed/calathea.es.md`
- `src/sprout/data/corpus/processed/calathea.md`
- `src/sprout/data/corpus/processed/dracaena.es.md`
- `src/sprout/data/corpus/processed/dracaena.md`
- `src/sprout/data/corpus/processed/english-ivy.es.md`
- `src/sprout/data/corpus/processed/english-ivy.md`
- `src/sprout/data/corpus/processed/fiddle-leaf-fig.es.md`
- Plus 21 more files in the same inventory.

Representative test files checked:

- `tests/conftest.py`
- `tests/test_a11y_and_judge.py`
- `tests/test_cli.py`
- `tests/test_eval_core.py`
- `tests/test_eval_suites.py`
- `tests/test_foundation.py`
- `tests/test_freshness.py`
- `tests/test_guard_fuzzing.py`
- `tests/test_identify.py`
- `tests/test_ingest.py`
- `tests/test_latency.py`
- `tests/test_marker_hygiene.py`
- `tests/test_model_card.py`
- `tests/test_providers_and_extras.py`
- `tests/test_rag.py`
- `tests/test_reminders.py`
- `tests/test_resources.py`
- `tests/test_review_hardening.py`
- `tests/test_server.py`

## Validation Notes

For this docs PR, validation means the scope file was generated from the clean `origin/main` worktree, reviewed against repo metadata and docs inventory, and checked with `git diff --check`. Project test suites are still the authority for code behavior, because this PR changes documentation only.
