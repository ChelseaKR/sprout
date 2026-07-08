.DEFAULT_GOAL := help
PY := uv run
CONFIG ?= config/sprout.yaml

.PHONY: help install dev fmt lint type test security ingest eval eval-baseline \
        a11y calibrate audits docs workflow-lint ci-parity-check demo verify clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install dev + serve dependencies
	uv sync --extra serve

dev: ingest ## Ingest the corpus and run the chat server locally
	$(PY) sprout serve --config $(CONFIG)

fmt: ## Auto-format the codebase
	$(PY) ruff format src tests

lint: ## Lint (format check + rules)
	$(PY) ruff format --check src tests
	$(PY) ruff check src tests

type: ## Strict type-check
	$(PY) mypy

test: ## Run the test suite with the coverage gate (>=90%)
	$(PY) pytest

security: ## Dependency + secret + SAST scanning — the same tools/thresholds CI enforces
	$(PY) pip-audit
	uvx semgrep scan --config p/python --error src
	@command -v gitleaks >/dev/null 2>&1 && gitleaks detect --no-banner --redact || \
	  ( [ -n "$$CI" ] && echo "gitleaks not installed — failing (CI=true; CI runs it via gitleaks-action instead of this target)" && exit 1 || \
	    echo "gitleaks not installed locally — install it (https://github.com/gitleaks/gitleaks) to run this check; CI enforces it regardless" )

ingest: ## Build the index from the bundled corpus (prereq for eval/a11y)
	$(PY) sprout ingest --config $(CONFIG)

eval: ingest ## Record the live engine, run the suites, regenerate the committed report
	$(PY) sprout eval --config $(CONFIG) --out docs/audits

eval-baseline: ingest ## Regenerate the eval report AND refresh the committed baseline
	$(PY) sprout eval --config $(CONFIG) --out docs/audits --update-baseline

calibrate: ## Calibrate the judge against human-labeled probes (agreement + kappa)
	$(PY) sprout calibrate eval/judge_probes.yaml --out docs/audits

a11y: ## Structural WCAG gate on the chat UI and the HTML eval report (merge gate)
	$(PY) sprout a11y-check web/dist/index.html
	$(PY) sprout a11y-check docs/audits/eval-report.html

audits: eval calibrate ## Regenerate the committed eval + calibration audit artifacts

docs: ## Build the docs site strictly (mirrors the CI docs gate)
	uv sync --group docs
	$(PY) mkdocs build --strict

workflow-lint: ## Workflow SAST (mirrors the CI zizmor gate)
	uvx zizmor --min-severity high .github/workflows/

ci-parity-check: ## Mechanically diff make verify's commands against the required ci-gate jobs
	$(PY) sprout ci-parity-check

demo: ingest ## Reproduce a short scripted session
	$(PY) sprout demo --config $(CONFIG)

verify: lint type test security eval a11y docs workflow-lint ci-parity-check ## Full local mirror of the CI gate set
	@echo "verify: all gates green"

clean: ## Remove caches, build, and runtime artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist *.egg-info \
	       var/index.json site
