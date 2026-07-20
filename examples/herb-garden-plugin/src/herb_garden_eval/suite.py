"""``herb-actionable-advice``: a domain-specific suite the built-in five don't cover.

The built-in ``groundedness`` suite checks that every claim is entailed by a cited
passage; the built-in ``safety`` suite checks toxicity cases never certify "safe" and
always route to a vet/poison-control line. Neither checks whether a troubleshooting
answer is *actionable* — names the herb and a concrete remedy — rather than merely
descriptive. This suite fills that domain-specific gap, authored entirely outside the
sprout repo and registered through the ``sprout.eval.suites`` entry point declared in
this package's ``pyproject.toml``.

Cases opt in by authoring ``must_mention`` (an existing, already-frozen ``DatasetItem``
field the built-in suites don't read) with the herb's name and a remedy verb, e.g.
``["basil", "drainage"]`` for a case about yellowing leaves.
"""

from __future__ import annotations

from sprout.eval import (
    EvalContext,
    ExampleOutcome,
    MetricDefinition,
    SuiteResult,
    aggregate,
)


class MustMentionSuite:
    """Every case that authors ``must_mention`` gets an actionable-advice check."""

    name = "herb-actionable-advice"
    metric = MetricDefinition(
        name="actionable-advice-coverage",
        definition=(
            "Fraction of answered cases authoring `must_mention` whose answer text "
            "contains every required term (case-insensitive substring) — e.g. the herb's "
            "name plus a concrete remedy action — so a troubleshooting answer reads as "
            "actionable rather than merely descriptive."
        ),
        threshold=0.9,
    )

    def run(self, ctx: EvalContext) -> SuiteResult:
        outcomes: list[ExampleOutcome] = []
        for item in ctx.dataset.items:
            if not item.must_mention:
                continue
            if item.target_response is None or item.target_response.refused:
                outcomes.append(
                    ExampleOutcome(
                        item_id=item.id,
                        passed=False,
                        score=0.0,
                        detail="refused or unanswered; cannot mention required terms",
                    )
                )
                continue
            text = item.target_response.text.lower()
            missing = [t for t in item.must_mention if t.lower() not in text]
            passed = not missing
            outcomes.append(
                ExampleOutcome(
                    item_id=item.id,
                    passed=passed,
                    score=1.0 if passed else 0.0,
                    detail="ok" if passed else f"missing required term(s): {missing}",
                )
            )
        return aggregate(
            suite=self.name,
            metric=self.metric,
            outcomes=outcomes,
            dataset_version=ctx.dataset.version,
            judge=ctx.judge,
        )


def build_suite() -> MustMentionSuite:
    """The entry-point target: a zero-argument factory, per ``ENTRY_POINT_GROUP``'s
    contract in ``sprout.eval.suite``. Returning a fresh instance (rather than a module-
    level singleton) keeps this package import-safe even if sprout re-scans entry points
    more than once in a process that has reset its discovery cache (e.g. in tests)."""
    return MustMentionSuite()
