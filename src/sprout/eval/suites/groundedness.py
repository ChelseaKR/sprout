"""Groundedness suite: is every claim entailed by the cited passage?

Applicable to answered cases that carry source passages. Each answer is split into claims;
the judge checks each claim's entailment against the cited sources. The deterministic judge
additionally fails a claim whose negation polarity differs from the source (a contradiction,
distinct from merely unsupported). An item passes if at least 80% of its claims are entailed;
the suite passes if at least 95% of items pass.
"""

from __future__ import annotations

from ..suite import EvalContext, ExampleOutcome, MetricDefinition, SuiteResult, aggregate, register
from ._common import claims, response_text

PER_ITEM_THRESHOLD = 0.8


class GroundednessSuite:
    name = "groundedness"
    metric = MetricDefinition(
        name="groundedness",
        definition=(
            "Fraction of answered cases whose claims are all entailed by the cited "
            "passages (>=80% of claims entailed per case; contradictions fail)."
        ),
        threshold=0.95,
    )

    def run(self, ctx: EvalContext) -> SuiteResult:
        outcomes: list[ExampleOutcome] = []
        for item in ctx.dataset.items:
            applicable = (
                item.target_response is not None
                and not item.target_response.refused
                and bool(item.sources)
                and bool(response_text(item))
            )
            if not applicable:
                continue
            item_claims = claims(response_text(item))
            if not item_claims:
                outcomes.append(
                    ExampleOutcome(item_id=item.id, passed=False, score=0.0, detail="no claims")
                )
                continue
            entailed = 0
            worst = ""
            for claim in item_claims:
                decision = ctx.judge.entails(claim, item.sources)
                if decision.passed:
                    entailed += 1
                elif not worst:
                    worst = f"{claim!r}: {decision.detail}"
            ratio = entailed / len(item_claims)
            outcomes.append(
                ExampleOutcome(
                    item_id=item.id,
                    passed=ratio >= PER_ITEM_THRESHOLD,
                    score=round(ratio, 4),
                    detail=worst or "all claims entailed",
                )
            )
        return aggregate(
            suite=self.name,
            metric=self.metric,
            outcomes=outcomes,
            dataset_version=ctx.dataset.version,
            judge=ctx.judge,
        )


register(GroundednessSuite())
