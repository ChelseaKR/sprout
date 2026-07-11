# 5. Calibrated abstention thresholds

- Status: **Superseded by [0012](0012-recalibrated-abstention-thresholds-supersedes-0005.md)
  (2026-07-05)** — the numbers below (abstain 0.45, low-confidence 0.62, logistic midpoint
  0.22/steepness 12.0) were never the values actually shipped in code, and running the
  calibration suite against them fails the ECE gate (0.184 > 0.15). This record is kept
  verbatim, append-only, for history; do not treat its numbers as current. See ADR-0012.
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

The third behavioral promise is **calibrated uncertainty**: "below a confidence threshold
it abstains rather than guesses," and the stated confidence must *track correctness* — a
0.6 confidence should be right about 60% of the time. Two anti-patterns to avoid:

1. **Confidence from fluency.** Asking the model how sure it is, or scoring on answer
   fluency, rewards confident nonsense — the more fluent the fabrication, the higher the
   self-reported confidence. That inverts the signal we want.
2. **A magic number with no audit.** A threshold nobody validates is a guess wearing a
   number. `AI-EVALUATION-STANDARD` requires calibration to be a *measured, gated* layer
   (reliability + ECE), not a claim.

Confidence has real consequences here — below a threshold the assistant refuses entirely —
so the number must be defensible and the thresholds must be auditable.

## Decision

Confidence is a transparent function of **retrieval evidence only**, and abstention is
driven by two thresholds over it (`confidence.py`, `config.py::ConfidenceConfig`).

- **Score.** `score_confidence()` maps the best passage's cosine through a fixed logistic
  (midpoint 0.22, steepness 12.0), nudged up by the margin over the runner-up passage. It
  deliberately ignores answer fluency. A refusal scores 0.0 (maximally uncertain about the
  answer it declined to give).
- **Two thresholds.** Below `abstain_threshold` (default 0.45) the assistant **refuses**
  rather than guesses, returning a routed refusal with `abstained=True`. Below
  `low_confidence_threshold` (default 0.62) it answers but **flags the answer for human
  review** (`low_confidence=True`). The two-band design separates "don't answer" from
  "answer, but caveat."
- **Held to the claim.** The `calibration` eval suite builds a **reliability diagram** and
  computes **Expected Calibration Error (ECE)** over (confidence, correct) pairs
  (`confidence.py`, `eval/calibration.py`), so the harness verifies the stated confidences
  actually track correctness. The judge config hash is folded into the run fingerprint, so a
  calibration record is invalidated when the judge or thresholds change (ADR-0009).

## Consequences

- **Positive.** Confidence cannot be gamed by fluency; it is grounded in the same retrieval
  evidence that decides answer-vs-refuse, so the whole pipeline tells one consistent story.
- **Positive.** The thresholds are not asserted — they are *audited* by ECE and the
  reliability diagram in a committed suite, and re-validated on every run.
- **Positive.** Abstention below threshold means the assistant's worst case is an honest "I
  don't know," not a confident wrong answer — the safe failure mode.
- **Negative — the honest limit.** Because confidence derives from retrieval similarity over
  a token-hashing embedder (ADR-0001), it measures "how well did we retrieve," not "is the
  extracted sentence correct for this user's exact situation." A well-retrieved but
  situation-mismatched passage can read as high-confidence. The model card states this.
- **Negative.** The logistic constants and thresholds are tuned against the eval set; on a
  swapped corpus they should be re-validated (re-run the calibration suite) rather than
  assumed.
- **Neutral.** Thresholds are config, but they are a named guardrail — changing them is an
  ADR-class change per the README.
