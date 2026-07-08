# 13. Fitted, provenance-stamped confidence constants (`sprout fit-confidence`)

- Status: Accepted
- Date: 2026-07-08
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)
- Related: [ADR-0012](0012-recalibrated-abstention-thresholds-supersedes-0005.md) (the
  abstain/low-confidence thresholds this ADR does not change); FIX-08,
  `docs/ideation/02-large-scale-fixes.md`

## Context

`confidence.py`'s logistic constants (`_MIDPOINT = 0.30`, `_STEEPNESS = 6.0`,
`_MARGIN_BONUS = 0.05`) carried a comment saying "re-fit if the corpus or retrieval
changes materially" since the module was written, but no tool existed to do that re-fit.
ADR-0012 measured that these particular values pass the ECE gate (0.108 ≤ 0.15) — but the
committed eval report's own reliability diagram already shows two mid-range bins failing
their per-bin tolerance (`[0.4,0.5)` and `[0.5,0.6)` in `docs/audits/eval-report.md`)
inside an overall-passing ECE. Every retrieval change (FIX-07/EXP-03-style work) silently
invalidates the fit further, and nothing would notice except a slow ECE drift toward the
0.15 gate.

Hand-tuning a fresh set of constants each time is exactly the failure mode ADR-0012
documented for ADR-0005: a number gets written down and never round-trips through
measurement again.

## Decision

Add `sprout fit-confidence` (`src/sprout/fit_confidence.py`) as the supported way to
produce new logistic constants, and make the constants it produces a first-class,
provenance-stamped config artifact rather than a source comment:

- **Never fits against `eval/suites/`.** It replays the live engine over a **train
  split** — `eval/train/calibration_train.yaml` by default, a disjoint set of
  corpus-derived questions covering the same 16 species on a *different* topic
  (soil/repotting) than the eval suite's calibration cases (watering/light/toxicity/
  common-problems), plus disjoint out-of-scope negatives. This is the same
  tune-only-against-committed-failures / never-tune-to-the-test-set discipline
  `docs/ROADMAP.md` Phase 3 already commits to for retrieval and prompt tuning, applied
  to confidence fitting. Fitting against the eval set would let the fit "know" the exact
  cases the calibration suite grades it on, turning the ECE gate into a check of nothing.
- **Bypasses the confidence gate while collecting evidence.** `Assistant.confidence_signal`
  (a new method, sharing the retrieve→generate→guard pipeline `answer()` already uses via
  `_retrieve_and_render`) returns the raw `(best cosine, margin)` evidence and whether a
  grounded, guard-surviving answer resulted — without ever consulting the *current*
  `abstain_threshold`. Gating evidence collection by the threshold being replaced would be
  circular.
- **Stays a 3-parameter logistic — no learned model.** `fit_constants` grid-searches
  `(midpoint, steepness, margin_bonus)` minimizing binary cross-entropy over a small, fixed
  grid (51 × 12 × 7 points). Not gradient descent, not an external solver, no new
  dependency (no numpy/scipy/sklearn) — the same transparent function `confidence.py`'s
  docstring already promises ("a transparent function of retrieval evidence... It
  deliberately does not depend on answer fluency"), just fitted instead of hand-picked.
  This also makes a fit fully reproducible: same train split + same live engine ⇒ same
  constants, byte for byte.
- **Writes a provenance-stamped artifact, not bare numbers.** The fit is written to
  `confidence.fit` in the target config YAML: `midpoint`, `steepness`, `margin_bonus`,
  `train_dataset_hash` (content hash of the train split actually used),
  `retrieval_config_hash` (content hash of `RetrievalConfig` at fit time), `n_items`, and
  `fitted_at`. It answers "fitted on what, when, against which retrieval config" the way a
  bare constant never could. The write is a targeted text edit
  (`fit_confidence.upsert_confidence_fit`), not a `yaml.safe_load`/`dump` round-trip, so
  every other line of the hand-maintained config file — including its comments — survives
  untouched.
- **`score_confidence` reads from config, not module globals.** `score_confidence(retrieved,
  n_rendered, cfg)` now takes the `ConfidenceConfig`; when `cfg.fit` is present it uses the
  fitted constants, otherwise it falls back to the ADR-0012 defaults (`_MIDPOINT` /
  `_STEEPNESS` / `_MARGIN_BONUS`, unchanged, still the documented safe default for a fresh
  install or before any fit has been run). This is why `confidence.py` remains
  CODEOWNERS-guarded and this change goes through an ADR: the *fallback* behavior for every
  existing config that has never run `fit-confidence` is unchanged.
- **A drift check gates `sprout eval`.** `confidence.fit_drift_warning(cfg.confidence,
  cfg.retrieval)` compares the fit's stamped `retrieval_config_hash` against the live
  retrieval config; a mismatch fails `sprout eval` closed, before it even records the
  engine, with a message naming exactly what to do (`sprout fit-confidence` again).

## Consequences

- **Positive.** The re-fit tool named in `confidence.py`'s own comment now exists, is
  tested (`tests/test_fit_confidence.py`, `tests/test_rag.py`,
  `tests/test_cli.py::test_fit_confidence_cmd_*`), and is wired into the CLI
  (`sprout fit-confidence --train eval/train/calibration_train.yaml --config
  config/sprout.yaml`).
- **Positive.** A future retrieval change (FIX-07, EXP-03) that invalidates the fit is now
  a hard `sprout eval` failure with a clear remediation step, not a silent ECE drift.
- **Neutral — this ADR does not flip the shipped default.** `config/sprout.yaml` and the
  packaged `src/sprout/data/sprout.yaml` still carry `confidence.fit: null` (absent) after
  this change; `score_confidence` therefore still uses the ADR-0012 constants at runtime,
  and `docs/audits/eval-baseline.json` / `eval-report.md` are unchanged. Actually adopting
  a fresh fit as the shipped default is a follow-on decision for the maintainer to make
  deliberately (see the note below) — same posture ADR-0012 itself took toward re-tuning
  ADR-0005's numbers.
- **Negative — the train split is small, and the fit it produces measurably regresses
  the eval set today.** Running `sprout fit-confidence` for real against the shipped
  corpus (`sprout ingest` + `sprout fit-confidence --train
  eval/train/calibration_train.yaml`) produces `midpoint=0.44, steepness=8.0,
  margin_bonus=0.2` from the 24-item train split. Loading that fit and re-running `sprout
  eval --suites calibration` against `eval/suites/` measures **ECE 0.263 — a regression
  against the current 0.108** (ADR-0012), with five of eight reliability bins failing
  their per-bin tolerance (vs. two failing bins today). 24 corpus-derived questions is
  enough to prove the tool works end to end; it is not enough evidence to trust a
  production re-fit on. This is exactly why this ADR does not commit that fit as the
  shipped default — see below.

## Note for the maintainer

This ADR adds the tool FIX-08 asked for and proves it end to end — unit + CLI tests, plus
an actual run against the real bundled corpus (documented above) — but deliberately
leaves `confidence.fit` unset in the shipped config, because that real run's own evidence
(ECE 0.263 vs. the shipped 0.108) says the current 24-item train split is not yet good
enough to re-tune against. Before adopting a fit as the shipped default: expand the train
split (more items; ideally the leave-species-out split
`docs/ideation/02-large-scale-fixes.md` suggests), re-run `sprout fit-confidence`, and
compare the resulting ECE/reliability diagram against 0.108 — the same measure-before-ship
discipline ADR-0012 used. Do not adopt a fit whose measured ECE is worse than what's
already shipped.
