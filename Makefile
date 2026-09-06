.DEFAULT_GOAL := help
PY := uv run --locked
CONFIG ?= config/sprout.yaml
# Set only by the release workflow (e.g. `make verify RELEASE_TAG=v1.2.3`): when non-empty,
# `eval` appends this run's scores to docs/audits/eval-history.jsonl and runs the
# consecutive-decline drift gate (EXP-13). Left unset for CI's per-PR `make verify`/`eval`
# runs so the ledger only ever grows one entry per release, never per PR.
RELEASE_TAG ?=

.PHONY: help install dev fmt lint type test security ingest eval eval-baseline \
        lock-check \
        smoke a11y site-check claims calibrate gate-inventory slo corpus-report propose-check \
        freshness audits docs \
        workflow-lint ci-parity-check demo verify clean web-static-bundle \
        web-static-fixtures web-static-test web-static-build

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install dev + serve dependencies
	uv sync --extra serve

dev: ingest ## Ingest the corpus and run the chat server locally
	$(PY) sprout serve --config $(CONFIG)

fmt: ## Auto-format the codebase
	$(PY) ruff format src tests

# `uv run` without `--locked` implicitly re-locks: with a pyproject edit in the tree it
# rewrites uv.lock in place and the gate it was running still exits 0. Measured on
# 2026-08-29: tightening one dependency constraint and then running `make lint` printed
# `ruff 0.16.3` and changed uv.lock's sha from 1c127747 to 88a9de81, silently. Every
# recipe now goes through `uv run --locked` (see PY above), and this target runs first in
# `verify` so a lockfile that no longer matches pyproject.toml fails before any other
# target has a chance to heal it in the working tree. `uv lock --check` resolves and
# compares; it never writes.
lock-check: ## Fail if uv.lock is not what pyproject.toml now resolves to (writes nothing)
	uv lock --check --offline

lint: ## Lint (format check + rules)
	$(PY) ruff format --check src tests docs_hooks
	$(PY) ruff check src tests docs_hooks

type: ## Strict type-check
	$(PY) mypy

test: ## Run the test suite with the coverage gate (>=90%)
	$(PY) pytest

# Every directory holding tracked Python. Naming only `src` left 62 of the repo's 142
# Python files — tests/, scripts/, eval/, examples/, infra/ — with no SAST pass ever run
# over them, including the gate machinery in scripts/. tests/test_security_gate.py fails
# if a Python root is missing here or if this list and ci.yml's disagree.
SAST_PATHS := src tests scripts eval examples infra docs_hooks

security: ## Dependency + secret + SAST scanning — the same tools/thresholds CI enforces
	$(PY) pip-audit
	uvx --with 'setuptools<81' semgrep scan --config p/python --error $(SAST_PATHS)
# `cmd && scan || fallback` sent a *finding* down the fallback branch, because a gitleaks
# that finds a secret exits 1 exactly like a gitleaks that is not there. Measured: with a
# gitleaks reporting "leaks found: 1", the old recipe printed "gitleaks not installed
# locally" and exited 0. The install check and the scan are separate statements now, so a
# finding fails this target and a missing tool says so in its own words.
	@if command -v gitleaks >/dev/null 2>&1; then \
	  gitleaks detect --no-banner --redact; \
	elif [ -n "$$CI" ]; then \
	  echo "gitleaks not installed — failing (CI=true; CI runs it via gitleaks-action instead of this target)"; \
	  exit 1; \
	else \
	  echo "gitleaks not installed locally — install it (https://github.com/gitleaks/gitleaks) to run this check; CI enforces it regardless"; \
	fi

ingest: ## Build the index from the bundled corpus (prereq for eval/a11y)
	$(PY) sprout ingest --config $(CONFIG)

eval: ingest ## Record the live engine, run the suites, regenerate the committed report
	$(PY) sprout eval --config $(CONFIG) --out docs/audits $(if $(RELEASE_TAG),--release '$(RELEASE_TAG)')

eval-baseline: ingest ## Regenerate the eval report AND refresh the committed baseline
	$(PY) sprout eval --config $(CONFIG) --out docs/audits --update-baseline

calibrate: ## Calibrate the judge against human-labeled probes (agreement + kappa; gated, mirrors CI)
	$(PY) sprout calibrate eval/judge_probes.yaml --out docs/audits --gate

freshness: ## Fail on citations past their configured freshness SLA (offline, deterministic)
	$(PY) sprout freshness --config $(CONFIG)

smoke: ingest ## Phase 1 CI smoke suite: corpus-derived questions, no hand-authored YAML
	$(PY) sprout smoke --config $(CONFIG) --out docs/audits

a11y: ## Structural WCAG gate on the chat UI and the HTML eval report (merge gate)
	$(PY) sprout a11y-check web/dist/index.html
	$(PY) sprout a11y-check docs/audits/eval-report.html

# The published tree is not `mkdocs build`'s output: `pages.yml` copies
# web-static/public over it afterwards, so the page served at / is the reference
# surface and not mkdocs' own index. Nothing local reproduced that, which is how
# the root page came to be the one published page with no canonical on it. This
# target builds what is actually deployed and then reads it.
site-check: docs web-static-build ## Metadata gate on the deployed tree: canonicals, robots.txt, sitemap
	cp -R web-static/public/. site/
	$(PY) sprout site-check site --origin https://sprout.chelseakr.com

claims: ## Claims-integrity gate: docs/claims.yaml vs code/config source of truth
	$(PY) sprout claims-check

gate-inventory: ## FIX-02: fail if any ledger AUTO row has no real enforcement mechanism
	$(PY) sprout gate-inventory --out docs/audits

slo: ## Schema-check the Tier-A SLO + burn-rate-alert files
	$(PY) sprout slo-check

# Defined once. It was defined twice, and make silently discarded the first recipe (the
# one carrying --config), so `make verify CONFIG=other.yaml` ran this one gate against the
# default config and printed an "overriding commands" warning on every invocation.
corpus-report: ## EXP-12: species x topic x language completeness, EN/ES parity, chunk lint
	$(PY) sprout corpus-report --config $(CONFIG) --out docs/audits

propose-check: ## E5: review every committed corpus proposal, wherever it was filed
	$(PY) sprout propose check

audits: eval calibrate gate-inventory corpus-report ## Regenerate the committed eval + calibration + gate-inventory + corpus audit artifacts

docs: ## Build the docs site strictly (mirrors the CI docs gate)
	uv sync --group docs
	$(PY) mkdocs build --strict

workflow-lint: ## Workflow SAST (mirrors the CI zizmor gate)
	uvx zizmor --offline --min-severity high .github/workflows/

ci-parity-check: ## Mechanically diff make verify's commands against the required ci-gate jobs
	$(PY) sprout ci-parity-check

demo: ingest ## Reproduce a short scripted session
	$(PY) sprout demo --config $(CONFIG)

web-static-bundle: ingest ## Export index.json + config.json for the TS port (EXP-08)
	$(PY) python scripts/export_web_bundle.py --config $(CONFIG)

web-static-fixtures: ingest ## Regenerate the Python-side cross-language conformance fixtures
	$(PY) python scripts/generate_conformance_fixtures.py

web-static-test: web-static-bundle web-static-fixtures ## Run the TS port's conformance test over every committed eval-suite case
	cd web-static && npm ci && npm test

web-static-build: web-static-bundle ## Build the deployable static site (web-static/public/)
	cd web-static && npm ci && npm run build:site

verify: lock-check lint type test security eval smoke a11y site-check claims calibrate gate-inventory slo corpus-report propose-check docs workflow-lint ci-parity-check web-static-test ## Full local mirror of the CI gate set
	@echo "verify: all gates green"

clean: ## Remove caches, build, and runtime artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist *.egg-info \
	       var/index.json site web-static/dist web-static/public/data web-static/public/assets \
	       web-static/public/styles.css web-static/test/fixtures web-static/node_modules
