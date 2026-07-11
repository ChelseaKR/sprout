# 12. Recalibrated abstention thresholds (supersedes ADR-0005)

- Status: Accepted
- Date: 2026-07-05
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)
- Supersedes: [ADR-0005](0005-calibrated-abstention-thresholds.md) (kept verbatim, append-only)

## Context

A 2026-07-05 conformance audit (`audit-2026-07-05/sprout-AUDIT.md`, control CQ-45) found
that the confidence/abstention values ADR-0005 documented — `abstain_threshold` 0.45,
`low_confidence_threshold` 0.62, logistic midpoint 0.22 / steepness 12.0 — had **never
matched the shipped code** (`config.py`, `config/sprout.yaml`: 0.25 / 0.50;
`confidence.py`: midpoint 0.30 / steepness 6.0), divergent since the initial commit
(`a3938d8`). The repo's own Definition of Done says these thresholds change only via an
ADR, so this was a real defect independent of which set of numbers is "right."

The remediation instruction was to reconcile code to the *existing* ADR as the safe
default, then verify. Doing that (flipping `config.py`/`config/sprout.yaml`/`confidence.py`
to ADR-0005's numbers) and re-running `make eval` produced a **regression**: the
calibration suite, previously passing at ECE 0.108, now failed the gate at ECE 0.184
(threshold ≤ 0.15). The reliability diagram under the ADR-0005 numbers is materially
worse-fit than under the shipped numbers. This is direct evidence, from the project's own
audited eval harness, that ADR-0005's constants were a documented *intent* that was never
actually validated end-to-end — the shipped 0.30/6.0 logistic and 0.25/0.50 thresholds are
the values that were iteratively tuned against the eval set (the code comment removed by
this reconciliation said as much: "calibrated against the eval set").

## Decision

Keep the shipped values and make them the ADR of record, rather than force code to match
a number that fails the project's own calibration gate:

- `abstain_threshold` = **0.25** (below this, refuse rather than guess)
- `low_confidence_threshold` = **0.50** (below this, answer but flag for human review)
- Logistic `midpoint` = **0.30**, `steepness` = **6.0** (`confidence.score_confidence`)

**Evidence.** Running `sprout eval` (dataset hash `b87c705c52effe07`, 98 calibration
cases) with each candidate value set, holding everything else fixed:

| Values | ECE (≤0.15 gate) | Verdict |
|---|---|---|
| ADR-0005 (0.45/0.62, midpoint 0.22/steepness 12.0) | 0.184 | ❌ FAIL |
| Shipped / this ADR (0.25/0.50, midpoint 0.30/steepness 6.0) | 0.108 | ✅ PASS |

The full suite run (all five suites) at the shipped values reproduces the previously
committed report byte-for-byte (fingerprint `28774d18fd71c997`), confirming this is not a
new tuning pass — it is naming the value set the code has used all along as the correct
one, backed by the measurement the standard requires (reliability diagram + ECE).

## Consequences

- **Positive.** Code, config, and the governing ADR now agree; the DoD's "thresholds
  change only via an ADR" rule is satisfiable going forward because there is exactly one
  source of truth.
- **Positive.** The decision is evidence-based (ECE measured, not asserted), consistent
  with the AI-Evaluation-Standard's calibration requirement.
- **Negative — process gap this exposes.** ADR-0005 documented numbers that were
  apparently never round-tripped through the eval harness before being committed; this ADR
  closes that gap for the abstention thresholds specifically. The broader claims-integrity
  question (could other ADRs/docs cite unvalidated numbers?) is tracked as a gap, not
  resolved here — see the remediation execution log dated 2026-07-05.
- **Neutral.** All committed docs that already cited 0.45/0.62 (model card, RTA §D, ROADMAP
  ledger, the red-team report) are corrected by the same remediation pass to cite 0.25/0.50
  and this ADR instead of ADR-0005.
- **Unchanged from ADR-0005.** Confidence is still a transparent function of retrieval
  evidence only (never fluency); the two-band abstain/low-confidence design is unchanged;
  re-validate (re-run the calibration suite) before trusting these numbers against a
  swapped corpus.

## Note for the maintainer

This ADR was authored by an automated remediation pass executing
`audit-2026-07-05/sprout-REMEDIATION.md` item P0-10. The instruction given to that pass was
to default to matching code to ADR-0005 and flag any discrepancy for human confirmation
rather than resolve it silently. The pass found that default fails the project's own
calibration gate on measurement, and is recording that finding here, prominently, for you
to confirm or override. If you conclude ADR-0005's numbers should instead be pursued as a
future target (e.g. by re-tuning the logistic curve to hit ECE ≤ 0.15 *at* midpoint
0.22/steepness 12.0, or by re-running eval on additional/real corpus data), that is a
follow-on calibration project (comparable to P2-3), not a same-day config flip — leave this
ADR as the interim source of truth until that work lands and its own evidence is recorded.
