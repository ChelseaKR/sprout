# 13. Coverage/risk curve in the calibration report (E4)

- Status: Accepted
- Date: 2026-07-09
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

`docs/RESEARCH-ROADMAP.md` E4 asks for a **coverage-vs-risk (selective-prediction) curve**
in the calibration report, beyond ECE: "publish the coverage/risk tradeoff at the abstain
threshold." ECE (ADR-0005/ADR-0012) answers "does stated confidence track correctness on
average," but it does not answer the question a maintainer actually asks when tuning
`abstain_threshold`: *if I raise the bar, how much do I give up in coverage, and how much
risk do I remove?* Selective-prediction literature (EV8 in RESEARCH-ROADMAP) treats this
tradeoff as the formal tool for exactly that question.

`confidence.py` is a CODEOWNERS-guarded file, so this change gets an ADR per the repo's own
rule, even though it adds a new pure function rather than changing any existing one — the
abstain threshold (0.25, per ADR-0012) and the logistic constants are untouched.

## Decision

Add `coverage_risk_curve()` to `confidence.py`: given the same `(confidence, correct)`
pairs the reliability diagram already consumes, and a fixed list of thresholds
(`DEFAULT_COVERAGE_THRESHOLDS`, including the engine's own 0.25 `abstain_threshold`), it
returns one `CoveragePoint(threshold, coverage, risk, n_covered)` per threshold:

- **coverage** — the fraction of labeled cases with confidence at or above the threshold
  (i.e., the fraction the system would answer if abstention were cut there).
- **risk** — the error rate (1 − accuracy) restricted to exactly that covered subset. Risk
  is reported as 0.0 when nothing is covered — "no error observed," not "zero risk."

The `calibration` eval suite (`eval/suites/calibration.py`) computes this curve alongside
the existing reliability bins and appends it to `SuiteResult.segments` — the same generic
mechanism the reliability diagram already uses, so `report.py` needed no changes to render
it. Each point additionally carries an informational PASS/FAIL: FAIL when risk rises more
than `_RISK_MONOTONICITY_TOLERANCE` (0.05) over the previous, lower-threshold point — a
weak calibration smell (raising the bar should not make the covered set *riskier*), tuned
loose enough to absorb small-n jitter.

**This does not add a new gate.** The suite's own PASS/FAIL stays exactly what it was
before this ADR: ECE ≤ 0.15 and abstention enforced below 0.25. The per-point
monotonicity flags are visible in the report table but do not feed `extra_pass` or the
suite verdict — E4 asks the report to *publish* the tradeoff, not to gate on it, and
turning it into a hard gate without first observing real curves across releases would be
exactly the kind of undemonstrated threshold ADR-0012's own audit warns against repeating.

## Consequences

- **Positive.** A maintainer tuning `abstain_threshold` (or re-fitting confidence per
  FIX-08, if built) can read the actual coverage given up per point of risk removed,
  instead of guessing from ECE alone.
- **Positive.** Zero behavior change to `score_confidence`, `should_abstain`,
  `is_low_confidence`, or the suite's PASS/FAIL — purely additive, so existing callers and
  the committed baseline's verdicts are unaffected. Verified locally: `docs/audits/eval-
  report.json`'s diff against the pre-change version is append-only (new `segments`
  entries), with every suite's score/verdict unchanged.
- **Neutral.** The calibration suite's `segments` table grows by up to
  `len(DEFAULT_COVERAGE_THRESHOLDS)` rows (only thresholds with at least one covered case
  are emitted); this is a report-size change, not a behavior change.
- **Negative — honest limit.** With the corpus's current case counts, high thresholds cover
  very few cases (small `n_covered`), so the risk figure at the top of the curve is noisy;
  the report shows `n` per point so this is visible, not hidden. FIX-12 (statistical power)
  improves this the same way it improves the reliability bins.
- **Follow-up.** If a future release wants this curve to actually gate CI, that is a new
  ADR that must first show the metric is stable across releases (the way EXP-13's eval
  trend ledger is designed to demonstrate) — not a decision made in this one.
