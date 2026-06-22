"""Multilingual suite: Spanish answers preserve their English mirror's facts and citations.

Cases are grouped by ``pair_id``; one member per group is the reference-language anchor
(``is_reference``). Each non-reference member is checked for *parity* with the anchor:
the same refuse/answer decision and the same set of cited plants (a language-invariant key
parsed from the citation, since 'monstera.md' and 'monstera.es.md' describe the same plant).
Cross-lingual lexical equivalence is meaningless to the deterministic judge, so the offline
gate is structural parity; an LLM judge additionally checks semantic equivalence and its
verdict is recorded in the per-item detail.
"""

from __future__ import annotations

from ..dataset import DatasetItem
from ..suite import EvalContext, ExampleOutcome, MetricDefinition, SuiteResult, aggregate, register
from ._common import citations_of, is_refused, plant_set, response_text


class MultilingualSuite:
    name = "multilingual"
    metric = MetricDefinition(
        name="multilingual-parity",
        definition=(
            "Fraction of non-reference language cases that match their reference anchor on "
            "refuse/answer decision and cited-plant set (EN/ES parity)."
        ),
        threshold=0.85,
    )

    def run(self, ctx: EvalContext) -> SuiteResult:
        groups: dict[str, list[DatasetItem]] = {}
        for item in ctx.dataset.items:
            if item.pair_id and item.target_response is not None:
                groups.setdefault(item.pair_id, []).append(item)

        outcomes: list[ExampleOutcome] = []
        for pair_id, members in groups.items():
            refs = [m for m in members if m.is_reference]
            translations = [m for m in members if not m.is_reference]
            # Fail closed on a malformed pair: exactly one anchor and at least one translation.
            if len(refs) != 1 or not translations:
                outcomes.append(
                    ExampleOutcome(
                        item_id=f"pair:{pair_id}",
                        passed=False,
                        score=0.0,
                        detail="pair must have exactly one reference anchor and >=1 translation",
                    )
                )
                continue
            ref = refs[0]
            ref_lang = (ref.target_response and ref.target_response.language) or ref.language
            ref_plants = plant_set(citations_of(ref))
            for member in translations:
                behavior_ok = is_refused(member) == is_refused(ref)
                plants_ok = plant_set(citations_of(member)) == ref_plants
                member_lang = (
                    member.target_response and member.target_response.language
                ) or member.language
                # The pair must actually be bilingual — a same-language (untranslated) copy fails.
                lang_ok = bool(member_lang) and bool(ref_lang) and member_lang != ref_lang
                semantic = ctx.judge.equivalent(response_text(member), response_text(ref))
                # The deterministic judge cannot compare across languages; gate on parity.
                passed = behavior_ok and plants_ok and lang_ok
                detail = (
                    f"behavior_ok={behavior_ok}, plants_ok={plants_ok}, lang_ok={lang_ok}, "
                    f"judge_equiv={semantic.score:.2f}"
                )
                outcomes.append(
                    ExampleOutcome(
                        item_id=member.id,
                        passed=passed,
                        score=1.0 if passed else 0.0,
                        detail=detail,
                    )
                )
        return aggregate(
            suite=self.name,
            metric=self.metric,
            outcomes=outcomes,
            dataset_version=ctx.dataset.version,
            judge=ctx.judge,
        )


register(MultilingualSuite())
