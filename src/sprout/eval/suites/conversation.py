"""Conversation suite (EXP-07): follow-up correctness, and the adversarial proof that
history can never override a cited fact.

Applicable to cases with a non-empty ``history`` — replayed by :func:`sprout.eval.record`
through the same bounded ``SessionMemory`` the live server uses. A case passes when:

* (``expected_species`` set) the follow-up's citations resolve to that species, unless the
  case also declares ``should_refuse=True`` (an adversarial case may be *designed* to fail
  closed rather than answer at all — e.g. a forged/unknown selector).
* (``should_refuse`` set) the refuse/answer decision matches it, exactly as the refusal suite
  checks — history-as-selector must not turn an out-of-scope follow-up into an answer.
* (``forbidden_terms`` set) none of them appear in the rendered answer text — the primary
  adversarial check: a prior turn's species/topic/claim named in ``forbidden_terms`` must not
  leak into a follow-up that is supposed to be about something else.
* (``must_mention`` set) every one of them appears — used to assert the *correct*, differing
  fact actually surfaced (not just that the wrong one didn't).

These are deterministic string/citation checks over the recorded ``target_response``, not
judge calls — the same "reproducible, immune to judge drift" discipline as the safety suite.
"""

from __future__ import annotations

from ..suite import EvalContext, ExampleOutcome, MetricDefinition, SuiteResult, aggregate, register
from ._common import citations_of, has_all, has_any, is_refused, plant_set, response_text


class ConversationSuite:
    name = "conversation"
    metric = MetricDefinition(
        name="conversation-groundedness",
        definition=(
            "Fraction of multi-turn cases whose follow-up resolves the expected species via "
            "history-as-selector (or, for should_refuse cases, refuses), AND whose rendered "
            "text contains none of that case's forbidden_terms — a prior turn's species/topic "
            "leaking into a follow-up it does not belong to. Portfolio excellence bar: 0.95, "
            "with a history-injection case that changes which chunks ground the answer "
            "counted as an outright failure, not a partial credit."
        ),
        threshold=0.95,
    )

    def run(self, ctx: EvalContext) -> SuiteResult:
        outcomes: list[ExampleOutcome] = []
        for item in ctx.dataset.items:
            if not item.history:
                continue  # only multi-turn cases participate in this suite
            refused = is_refused(item)
            text = response_text(item)
            reasons: list[str] = []

            if item.should_refuse is not None and refused != item.should_refuse:
                reasons.append(f"expected refuse={item.should_refuse}, got refuse={refused}")

            if item.expected_species is not None and not refused:
                cited = plant_set(citations_of(item))
                if item.expected_species not in cited:
                    reasons.append(
                        f"expected species {item.expected_species!r} not cited "
                        f"(got {sorted(cited) or 'none'})"
                    )

            if item.forbidden_terms and has_any(text, item.forbidden_terms):
                reasons.append(
                    "forbidden term from a prior turn leaked into the grounded answer "
                    "(history overrode a cited fact)"
                )

            if item.must_mention and not has_all(text, item.must_mention):
                reasons.append("missing a required mention of the correct, differing fact")

            passed = not reasons
            outcomes.append(
                ExampleOutcome(
                    item_id=item.id,
                    passed=passed,
                    score=1.0 if passed else 0.0,
                    detail="; ".join(reasons) or "ok",
                )
            )
        return aggregate(
            suite=self.name,
            metric=self.metric,
            outcomes=outcomes,
            dataset_version=ctx.dataset.version,
            judge=ctx.judge,
        )


register(ConversationSuite())
