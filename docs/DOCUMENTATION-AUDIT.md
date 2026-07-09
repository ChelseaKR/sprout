# Documentation Audit

Last reviewed: 2026-07-08. Base branch: `main`.

This audit records the documentation sweep and remediation loop for this repository. It checks the docs as a system: entry points, root-level process and legal files, project scope, setup and validation notes, safety and privacy posture, architecture and planning docs, local links, and the places where code, tests, workflows, and docs meet.

## Audit Results

| Area | Result | Evidence |
| --- | --- | --- |
| Entry docs | pass | `README.md` present |
| Security/process docs | pass | CONTRIBUTING.md, SECURITY.md, CHANGELOG.md |
| Architecture/planning docs | pass | 15 architecture/interface docs; 24 planning/research docs |
| Safety/privacy/audit docs | pass | 12 safety/privacy/accessibility/audit docs |
| Validation surface | pass | 18 test files; 3 workflow files |
| Local doc links | pass | 244 authored-doc links checked; 0 unresolved |

## Root-Level Documentation Audit

This section covers hand-authored documentation at the repository root and root-adjacent GitHub templates. It is separate from the `docs/` inventory so README, process, legal, release, and project-specific root files do not get hidden inside the larger docs tree.

| Surface | Result | Evidence |
| --- | --- | --- |
| Root README | pass | Present: `README.md` |
| Root process docs | pass | Present: `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md` |
| Root legal, citation, and conduct docs | pass | Present: `LICENSE`, `NOTICE`, `CITATION.cff`, `CODE_OF_CONDUCT.md` |
| Other root project docs | info | `CLAUDE.md`, `DEFINITION_OF_DONE.md` |
| Root-adjacent GitHub templates | pass | `.github/PULL_REQUEST_TEMPLATE.md`, `.github/CODEOWNERS` |
| Root/template doc links | pass | 36 root-level/template links checked; 0 unresolved |

Root-level files checked:

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

Root-adjacent template files checked:

- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/CODEOWNERS`

## Remediation In This PR

- Added missing root-level remediation docs found by the audit loop, including legal, conduct, contribution, or security files where absent.
- Added `docs/PROJECT-SCOPE.md` as the plain-language project and boundary map.
- Added this audit record so future doc changes have a dated baseline.
- Added or refreshed the docs index so scope, audit, and primary docs are easy to find.
- Fixed or added root/doc remediation files: `docs/ARCHITECTURE.md`, `docs/ideation/02-large-scale-fixes.md`.

## Repo Surfaces Checked

Package and workspace metadata:

- Python package `sprout` (>=3.12).

Source and operations surfaces seen at the repo root:

- `config/`
- `Dockerfile`
- `eval/`
- `Makefile`
- `pyproject.toml`
- `scripts/`
- `src/`
- `tests/`
- `uv.lock`
- `web/`

Workflow files checked:

- `.github/workflows/ci.yml`
- `.github/workflows/codeql.yml`
- `.github/workflows/release.yml`

## Documentation Inventory

| Category | Count | Representative files |
| --- | ---: | --- |
| architecture and interfaces | 15 | `docs/ARCHITECTURE.md`, `docs/adr/0000-record-architecture-decisions.md`, `docs/adr/0001-offline-deterministic-generator-as-default.md`, `docs/adr/0002-hybrid-bm25-plus-dense-retrieval.md`, `docs/adr/0003-extractive-generation-and-citation-guard-for-100pct-groundedness.md`, `docs/adr/0004-never-certify-safe-output-guard.md`, `docs/adr/0005-calibrated-abstention-thresholds.md`, `docs/adr/0006-eval-harness-in-repo-as-sprout-eval.md`, plus 7 more |
| entry points and repo process | 10 | `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`, `CHANGELOG.md`, `CITATION.cff`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `LICENSE`, `NOTICE`, plus 2 more |
| other docs | 50 | `CLAUDE.md`, `DEFINITION_OF_DONE.md`, `corpus/processed/aloe.es.md`, `corpus/processed/aloe.md`, `corpus/processed/boston-fern.es.md`, `corpus/processed/boston-fern.md`, `corpus/processed/calathea.es.md`, `corpus/processed/calathea.md`, plus 42 more |
| planning and research | 24 | `corpus/processed/jade-plant.es.md`, `corpus/processed/jade-plant.md`, `corpus/processed/rubber-plant.es.md`, `corpus/processed/rubber-plant.md`, `corpus/processed/snake-plant.es.md`, `corpus/processed/snake-plant.md`, `corpus/processed/spider-plant.es.md`, `corpus/processed/spider-plant.md`, plus 16 more |
| safety, privacy, accessibility, and audits | 12 | `docs/DOCUMENTATION-AUDIT.md`, `docs/RESPONSIBLE-TECH-AUDITS.md`, `docs/THREAT-MODEL.md`, `docs/a11y/STATEMENT.md`, `docs/accessibility/ACR.md`, `docs/audits/ai-risk-register.md`, `docs/audits/eu-ai-act-classification.md`, `docs/audits/eval-report.md`, plus 4 more |

Full hand-authored doc inventory checked by this pass:

- `.github/CODEOWNERS`
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
- `corpus/processed/aloe.es.md`
- `corpus/processed/aloe.md`
- `corpus/processed/boston-fern.es.md`
- `corpus/processed/boston-fern.md`
- `corpus/processed/calathea.es.md`
- `corpus/processed/calathea.md`
- `corpus/processed/dracaena.es.md`
- `corpus/processed/dracaena.md`
- `corpus/processed/english-ivy.es.md`
- `corpus/processed/english-ivy.md`
- `corpus/processed/fiddle-leaf-fig.es.md`
- `corpus/processed/fiddle-leaf-fig.md`
- `corpus/processed/jade-plant.es.md`
- `corpus/processed/jade-plant.md`
- `corpus/processed/monstera.es.md`
- `corpus/processed/monstera.md`
- `corpus/processed/orchid.es.md`
- `corpus/processed/orchid.md`
- `corpus/processed/peace-lily.es.md`
- `corpus/processed/peace-lily.md`
- `corpus/processed/philodendron.es.md`
- `corpus/processed/philodendron.md`
- `corpus/processed/pothos.es.md`
- `corpus/processed/pothos.md`
- `corpus/processed/rubber-plant.es.md`
- `corpus/processed/rubber-plant.md`
- `corpus/processed/snake-plant.es.md`
- `corpus/processed/snake-plant.md`
- `corpus/processed/spider-plant.es.md`
- `corpus/processed/spider-plant.md`
- `corpus/processed/zz-plant.es.md`
- `corpus/processed/zz-plant.md`
- `docs/ADAPT.md`
- `docs/ARCHITECTURE.md`
- `docs/DOCUMENTATION-AUDIT.md`
- `docs/PROJECT-SCOPE.md`
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
- `src/sprout/data/corpus/processed/fiddle-leaf-fig.md`
- `src/sprout/data/corpus/processed/jade-plant.es.md`
- `src/sprout/data/corpus/processed/jade-plant.md`
- `src/sprout/data/corpus/processed/monstera.es.md`
- `src/sprout/data/corpus/processed/monstera.md`
- `src/sprout/data/corpus/processed/orchid.es.md`
- `src/sprout/data/corpus/processed/orchid.md`
- `src/sprout/data/corpus/processed/peace-lily.es.md`
- `src/sprout/data/corpus/processed/peace-lily.md`
- `src/sprout/data/corpus/processed/philodendron.es.md`
- `src/sprout/data/corpus/processed/philodendron.md`
- `src/sprout/data/corpus/processed/pothos.es.md`
- `src/sprout/data/corpus/processed/pothos.md`
- `src/sprout/data/corpus/processed/rubber-plant.es.md`
- `src/sprout/data/corpus/processed/rubber-plant.md`
- `src/sprout/data/corpus/processed/snake-plant.es.md`
- `src/sprout/data/corpus/processed/snake-plant.md`
- `src/sprout/data/corpus/processed/spider-plant.es.md`
- `src/sprout/data/corpus/processed/spider-plant.md`
- `src/sprout/data/corpus/processed/zz-plant.es.md`
- `src/sprout/data/corpus/processed/zz-plant.md`

## Link Check

- Checked 244 local links in authored Markdown and MDX docs.
- Unresolved authored-doc links after remediation: 0.
- Root-level/template unresolved links after remediation: 0.

Audit scope notes:

- Generated sites, deployed app routes, raw third-party HTML captures, and golden fixture websites were inventoried as product or data surfaces but excluded from authored-doc link failure counts.

## Validation Notes

- The audit was generated from a clean worktree based on `origin/main` for this PR branch.
- Ran a local relative-link check over hand-authored Markdown and MDX docs.
- Ran an explicit root-level documentation presence and link check for README, process, legal, project, and template docs.
- Ran `git diff --check` across the PR worktrees after remediation.
- Product test suites remain the authority for runtime behavior; this PR changes documentation only.
