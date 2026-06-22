# 6. Eval harness ships in-repo as `sprout.eval`

- Status: Accepted
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

The spec is blunt about priorities: the eval harness "is the actual product," and "the
assistant exists so the harness has something honest to measure." That framing forces a
question most RAG projects answer by accident: where does the harness live, and what is its
relationship to the thing it grades?

Three shapes were considered:

1. A **separate eval repo** that imports Sprout as a dependency.
2. An external eval *service* (LangSmith-style hosted runs).
3. The harness **in-repo**, versioned with the code it grades.

`AI-EVALUATION-STANDARD` rejects hosted-service gates ("ties CI to a hosted service and the
LangChain ecosystem") and requires the eval to run in `pytest`, offline, gating every
prompt/retrieval change. It also requires a committed, version-controlled benchmark
regenerated like any audit artifact. A separate repo would let the assistant and its grader
drift out of version lockstep — the exact failure that lets a regression ship green.

## Decision

The harness ships **in the same repo, as the `sprout.eval` subpackage** (`src/sprout/eval/`),
not as an external dependency or service. `pyproject.toml` records this explicitly: "The
eval harness ships in-repo … the headline artifact, not as an external dependency."

- **Five suites** (`eval/suites/`, 120+ YAML cases): groundedness, safety, calibration,
  refusal, multilingual. Cases carry id, question, expected behavior, required
  citation/fact, language tag, rationale, and provenance.
- **Blended scoring.** Deterministic checks (citation resolves to corpus; forbidden "safe"
  phrases absent; "as of" date present; language matches) blended with **LLM-as-judge** for
  groundedness/helpfulness; judge model ≠ answer model (ADR-0009).
- **Fail-closed everywhere** (`eval/dataset.py`, `eval/runner.py`): a dataset-hash mismatch
  against the committed `suites.sha256` sidecar, a malformed case (`extra='forbid'`), an
  empty suite, or malformed judge output **fails the run** rather than passing quietly. Any
  suite that raises is converted to a fail-closed FAIL, not an aborted run.
- **Reproducible.** The `RunFingerprint` (harness version, seed, dataset hash, judge config
  hash, target, suite names) deliberately excludes wall-clock time, so the JSON artifact is
  **byte-identical for identical inputs**, and the baseline diff is meaningful.
- **Multi-format report.** `EVALS.md`/HTML (accessible) + JUnit + SARIF, committed under
  `docs/audits/`. `make eval` regenerates it end to end, offline.

## Consequences

- **Positive.** The assistant and its grader move in version lockstep — a behavior change
  and the cases that pin it land in the same commit; a regression cannot ship green by
  grading against a stale external harness.
- **Positive.** No hosted dependency, no second repo to keep in sync; `make eval` runs with
  no account, satisfying the Definition of Done and the offline/self-sustaining attributes.
- **Positive.** The runner is corpus-agnostic (the spec's **reusability** attribute), so
  Phase 4 can point it at a different corpus via `config`.
- **Negative.** Co-locating grader and gradee invites the temptation to tune cases to pass;
  the discipline against that is the committed baseline (mediocre numbers included) and the
  10% human-agreement sample with Cohen's κ.
- **Neutral.** The fail-closed loader is a named guardrail — changes go through an ADR.
