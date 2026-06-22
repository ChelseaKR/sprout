# 7. `src/` layout and a 90% branch-coverage floor

- Status: Accepted
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

Sprout is published to PyPI (`pipx install sprout`) and is meant to be `pip install`-ed by
strangers. That changes the bar in two specific ways a script or an app does not face:

1. **Import correctness.** A flat layout (package importable directly from the repo root)
   lets tests pass against the *source tree* while the *installed wheel* is subtly broken —
   a missing `py.typed`, a module not declared in the build target, a relative-import bug.
   The classic fix is the `src/` layout: tests run against the installed package, so "it
   works on my machine" and "it works for a `pip install` user" are the same statement.
2. **Coverage floor.** `CODE-QUALITY-STANDARD` sets the branch-coverage floor at **≥85% for
   applications** and **≥90% for published libraries**. Sprout is a published library *and*
   its guardrails (citation guard, never-certify-safe filter, abstention, fail-closed
   loader) are exactly the code where an untested branch is a safety regression.

## Decision

- **`src/` layout.** All importable code lives under `src/sprout/`, declared as the wheel
  package (`[tool.hatch.build.targets.wheel] packages = ["src/sprout"]`), with a `py.typed`
  marker so downstream `mypy` sees the types. CI and `make verify` run tests against the
  installed package, not the working tree.
- **≥90% branch coverage**, enforced as an AUTO-GATE (`pytest-cov`, `branch = true`,
  `--cov-fail-under`), the published-library floor. Coverage exclusions are narrow and
  justified in-line: the live-network paths that require an API key
  (`# pragma: no cover` on the default Anthropic/Bedrock completion and defensive
  `raise ValueError(...)` branches in the provider/judge factories).
- The toolchain is the portfolio-canonical stack referenced in the README's standards
  table: `ruff` (lint + format) and `mypy --strict`, single root `pyproject.toml`, committed
  `uv.lock`, `uv sync --frozen` in CI — no per-tool config files.

## Consequences

- **Positive.** Packaging bugs surface in CI, not in a user's `pipx install`. The
  `make verify` gate (lint · type · test ≥90% · security · a11y · eval) is the one command
  that reproduces the full bar locally, byte-for-byte with CI.
- **Positive.** The 90% floor lands hardest on the guardrail modules, which is exactly where
  we want it — an untested branch in `guards.py` or `confidence.py` fails the build.
- **Negative.** `src/` layout is marginally less convenient for ad-hoc `python -c` against
  the working tree (you must install, ideally `pip install -e .`); the payoff is
  install-fidelity and it is worth it for a published package.
- **Negative.** A 90% floor has a real authoring cost and can tempt coverage-padding tests;
  the mitigation is that the deterministic offline mode (ADR-0001) makes meaningful tests
  cheap, so coverage comes from real assertions rather than smoke tests.
- **Neutral.** The narrow `# pragma: no cover` exclusions are auditable and limited to the
  network seams that cannot run in offline CI.
