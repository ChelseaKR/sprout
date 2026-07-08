"""Completeness suite: does the answer cover every authored facet of a multi-part
question, not just whichever one ranked first?

Applicable to answered, non-refused cases that authored two or more ``expected_facts``
(a single expected fact is a groundedness/accuracy concern, already covered by the
``groundedness`` suite; completeness is specifically about multi-facet coverage). Each
case's score is the fraction of its authored facts the judge finds present in the
rendered answer text — the same fact/anchor check ``judge.contains`` already performs
for calibration probes — so a two-part question ("how often should I water, and does
that change in winter?") must surface both the frequency clause and the seasonal
clause to score 1.0, not repeat one of them twice. This is the deterministic
counterpart to EXP-01's facet-coverage answer planner in
``providers/deterministic.ExtractiveGenerator`` (docs/ideation/03-expansions.md).
"""

from __future__ import annotations

from ..suite import EvalContext, ExampleOutcome, MetricDefinition, SuiteResult, aggregate, register
from ._common import response_text

PER_ITEM_THRESHOLD = 0.9


class CompletenessSuite:
    name = "completeness"
    metric = MetricDefinition(
        name="completeness",
        definition=(
            "Fraction of a multi-facet case's authored expected_facts (cases with >=2) "
            "found present in the rendered answer; an item passes at >=90% facet "
            "coverage. Single-fact cases are out of scope (see groundedness)."
        ),
        threshold=0.9,
    )

    def run(self, ctx: EvalContext) -> SuiteResult:
        outcomes: list[ExampleOutcome] = []
        for item in ctx.dataset.items:
            applicable = (
                item.target_response is not None
                and not item.target_response.refused
                and len(item.expected_facts) >= 2
                and bool(response_text(item))
            )
            if not applicable:
                continue
            text = response_text(item)
            decisions = [ctx.judge.contains(text, fact) for fact in item.expected_facts]
            covered = sum(1 for d in decisions if d.passed)
            ratio = covered / len(item.expected_facts)
            missing = [
                fact
                for fact, decision in zip(item.expected_facts, decisions, strict=True)
                if not decision.passed
            ]
            outcomes.append(
                ExampleOutcome(
                    item_id=item.id,
                    passed=ratio >= PER_ITEM_THRESHOLD,
                    score=round(ratio, 4),
                    detail="all facets covered" if not missing else f"missing facets: {missing}",
                )
            )
        return aggregate(
            suite=self.name,
            metric=self.metric,
            outcomes=outcomes,
            dataset_version=ctx.dataset.version,
            judge=ctx.judge,
        )


register(CompletenessSuite())
