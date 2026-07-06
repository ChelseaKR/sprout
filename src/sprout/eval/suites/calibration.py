"""Calibration suite: do stated confidences track correctness, and abstain when low?

Applicable to cases that carry both a stated ``confidence`` and a ``is_correct`` label.
The suite computes a reliability diagram and the Expected Calibration Error (ECE) — the
count-weighted gap between confidence and accuracy — and gates ECE at <=0.15. It also
enforces abstention: any case answered below the abstain threshold (0.25, ADR-0012) must
have been a refusal. Reliability bins are reported as segments so the diagram is visible
in the report.
"""

from __future__ import annotations

from ...confidence import expected_calibration_error, reliability_diagram
from ..suite import (
    EvalContext,
    ExampleOutcome,
    MetricDefinition,
    SegmentScore,
    SuiteResult,
    Verdict,
    aggregate,
    register,
)
from ._common import is_refused

# Mirrors the engine default confidence.abstain_threshold (ADR-0012, supersedes ADR-0005);
# below it, an answered (non-refused) case is a calibration violation.
ABSTAIN_THRESHOLD = 0.25
N_BINS = 10


class CalibrationSuite:
    name = "calibration"
    metric = MetricDefinition(
        name="expected-calibration-error",
        definition=(
            "Expected Calibration Error over (stated confidence, correctness) pairs "
            "(<=0.15), with abstention enforced below the 0.25 confidence threshold "
            "(ADR-0012)."
        ),
        threshold=0.15,
        higher_is_better=False,
    )

    def run(self, ctx: EvalContext) -> SuiteResult:
        pairs: list[tuple[float, bool]] = []
        outcomes: list[ExampleOutcome] = []
        abstention_ok = True
        for item in ctx.dataset.items:
            if item.confidence is None:
                continue
            # Abstention check spans every confidence-bearing case: low confidence -> refusal.
            if item.confidence < ABSTAIN_THRESHOLD and not is_refused(item):
                abstention_ok = False
            # ECE is measured only over answered, labeled cases — a correct refusal
            # legitimately carries near-zero confidence and would distort the diagram.
            if item.is_correct is None or is_refused(item):
                continue
            pairs.append((item.confidence, item.is_correct))
            directional = item.is_correct == (item.confidence >= 0.5)
            outcomes.append(
                ExampleOutcome(
                    item_id=item.id,
                    passed=directional,
                    score=round(item.confidence, 4),
                    detail=f"confidence={item.confidence:.2f}, correct={item.is_correct}",
                )
            )
        ece = expected_calibration_error(pairs, N_BINS)
        segments = tuple(
            SegmentScore(
                label=f"[{b.lo:.1f},{b.hi:.1f})",
                score=b.accuracy,
                n=b.count,
                verdict=Verdict.PASS
                if abs(b.mean_confidence - b.accuracy) <= 0.15
                else Verdict.FAIL,
            )
            for b in reliability_diagram(pairs, N_BINS)
            if b.count
        )
        notes = f"ECE={ece:.3f}; abstention_below_{ABSTAIN_THRESHOLD}_enforced={abstention_ok}"
        return aggregate(
            suite=self.name,
            metric=self.metric,
            outcomes=outcomes,
            dataset_version=ctx.dataset.version,
            judge=ctx.judge,
            extra_pass=abstention_ok,
            score_override=round(ece, 4),
            notes=notes,
            segments=segments,
        )


register(CalibrationSuite())
