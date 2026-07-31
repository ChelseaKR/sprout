# 19. Frozen plugin API + entry-point suite discovery for `sprout.eval`

- Status: Accepted
- Date: 2026-07-08
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

ADR-0006 chose to ship the eval harness in-repo, as `sprout.eval`, and named "the runner
is corpus-agnostic" as a positive consequence — but that claim was, until now, asserted
rather than demonstrated. `CLAUDE.md` already gestures at the intended shape ("new eval
suites via entry points"), and `docs/ideation/03-expansions.md` (EXP-14) names the gap
directly: suites self-register at import time inside `eval/suites/__init__.py`, so a
third party cannot add one without forking this repo, and there is no worked proof that
the runner survives being pointed at a different corpus and a different domain-specific
suite at the same time.

That matters beyond this repo. `docs/ideation/04-impact-and-sequencing.md` calls out that
"a frozen public API and proven plugin seam" is a precondition for later, more ambitious
plugin-shaped work (signed corpus registries, a review console), and the portfolio has
other, unpublished eval-shaped projects that could consume the same runner if the
seam were real instead of aspirational.

## Decision

**1. `importlib.metadata` entry-point discovery**, alongside the existing in-tree
registry. Third-party packages register a suite in their own `pyproject.toml`:

```toml
[project.entry-points."sprout.eval.suites"]
my-suite = "my_package.suite:build_suite"
```

The entry point must resolve (`.load()`) to a ready `Suite` instance or a zero-argument
callable returning one. `sprout.eval.suite.load_entry_point_suites()` scans the
`sprout.eval.suites` group once per process (cached) and registers every discovered
suite into the same `_REGISTRY` the five built-in suites use — `resolve_suites()` and
`available()` see built-in and third-party suites identically, and `sprout eval --suites
all` picks up an installed plugin automatically. **A name collision is a hard error**: a
discovered suite whose name matches an already-registered suite (built-in or another
plugin) raises rather than silently overwriting it — the same fail-closed posture that
governs every other boundary in this harness (ADR-0006's dataset hash, the empty-suite
validator).

**2. A frozen public API surface**, re-exported from `sprout.eval.__init__` with an
explicit `__all__`: `Dataset`/`DatasetItem`/`Provenance`/`TargetResponse` (what a suite
reads), `Judge`/`JudgeDecision`/`DeterministicJudge`/`build_judge` (the one
model-touching seam), `Suite`/`EvalContext` (the contract a suite implements and
receives), `SuiteResult`/`MetricDefinition`/`ExampleOutcome`/`SegmentScore`/`Verdict`
(what a suite must return), and `register`/`available`/`resolve_suites`/
`load_entry_point_suites`/`ENTRY_POINT_GROUP` (the registry). These are Pydantic models
already declared `frozen=True`, or `Protocol`s (`Suite`, `Judge` — the latter marked
`@runtime_checkable`, as is now `Suite`). The commitment: **within a major version,
existing fields on these models are never removed or repurposed, and a `Suite`/`Judge`
implementation that satisfies the Protocol today keeps satisfying it** — only additive,
optional fields/functions land in a minor release. A breaking change to any of these
requires a new ADR superseding this one and a major version bump, mirroring the house
rule already applied to the citation/safety guards.

**3. A worked second-domain example**, `examples/herb-garden-plugin/`: a small,
independently pip-installable package (`sprout-herb-garden-example`) with its own
corpus (three herb-care documents, same manifest/provenance shape as `corpus/`), its own
`config.yaml` pointing `corpus.path`/`corpus.manifest` at that corpus, its own eval cases
(`eval/herb-care.yaml`), and a domain-specific `Suite` — `MustMentionSuite` — registered
purely through the `sprout.eval.suites` entry point, with **zero changes to this repo's
source**. Its committed report (`report/eval-report.json` + the rendered Markdown) is
produced by actually running `sprout eval` against the herb corpus with the plugin
installed, proving both corpus-agnosticism (ADR-0006's claim) and the plugin seam
(EXP-14) in one reproducible artifact.

## Consequences

- **Positive.** A sibling repo (or an external contributor) can add a suite by
  `pip install`-ing a package that declares the entry point — no fork, no PR against this
  repo required to extend what gets measured.
- **Positive.** The frozen API gives suite authors (in-tree and third-party) a stable
  contract to write against; `sprout.eval.__init__`'s docstring and `__all__` are now the
  single source of truth for "what a plugin author is allowed to depend on," instead of
  every internal name being implicitly public.
- **Positive.** The worked example is executable proof, not prose: `make -C
  examples/herb-garden-plugin` (or the equivalent documented steps) reproduces the
  committed numbers offline, the same discipline ADR-0006 applies to the primary corpus.
- **Negative.** The API freeze constrains future refactors of `Dataset`, `Judge`,
  `SuiteResult`, and `MetricDefinition` — a change that would have been a quiet internal
  rename must now go through an ADR and a major version bump. This is accepted per
  EXP-14's own risk note ("do after FIX-02/FIX-12 settle") — those items were already
  landed before this ADR.
- **Negative.** A duplicate-name failure from a misbehaving or stale plugin is a hard
  stop (fail-closed), not a warning — acceptable because a silently shadowed suite is a
  worse failure mode (a plugin's numbers silently never run, or silently replace a
  built-in's).
- **Neutral.** Entry-point discovery only fires when something calls `available()` or
  `resolve_suites()`; importing `sprout.eval` alone does not scan installed package
  metadata, keeping the common case (running the in-tree suites) free of the extra
  filesystem/metadata walk.
