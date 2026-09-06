"""Language-parity suite: do the language slices *pass* at the same rate?

This is deliberately **not** the ``multilingual`` suite's quantity, and the two were
conflated in this repo's docs until 2026-08-29. ``multilingual`` gates *per-case structural
parity* — each Spanish case against its own English anchor, on the refuse/answer decision
and the cited-plant set, at >= 0.85. That says nothing about whether the two languages are
answered *correctly* at the same rate, because it only ever scores the non-reference member
of a pair and never scores the English anchors at all.

This suite scores every recorded case, English anchors included, as its own language slice
and compares the slices:

* the per-case label is :func:`sprout.eval.record._is_correct` — the same predicate the
  calibration suite already trusts, applied identically in every language (it reads the
  case's own authored ``should_refuse`` / ``expected_behavior`` / ``expected_facts``, and
  the guards it consults are language-aware), so neither slice is graded on a softer rule;
* the score is the largest absolute gap between any two language slices' pass rates, which
  for this corpus's two languages is exactly the ledger's ``|EN - ES|``;
* the gate is ``<= 0.05`` (5 percentage points), the target the metrics ledger declares.

**What the headline number can and cannot support.** The interval reported beside the score
is a Newcombe interval on the *gap*, not a Wilson interval on a pass rate, and the
under-powered flag is keyed to the smallest slice rather than the pooled item count —
because the smallest slice is what limits the comparison. The English and Spanish case sets
are also not matched: the corpus authors more English cases, and some case families exist in
English only. A pooled gap therefore mixes a language effect with a case-mix effect. Rather
than average that away, the suite publishes **report-only diagnostic rows** that recompute
the same gap inside strata where both languages are present (the matched ``pair_id`` cases,
and each ``expected_behavior``). Those rows never change this suite's PASS/FAIL — only the
ledger's declared aggregate does — but a reader who wants to know whether the aggregate is
load-bearing can see the answer in the same table, exactly as the calibration suite
publishes its report-only coverage/risk curve beside its gated ECE.

Fail-closed: fewer than two language slices carrying labelled cases is a FAIL, never a
0.0 gap. "Only one language was evaluated" and "both languages passed equally" are not the
same result and must not render as the same number.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from ..dataset import DatasetItem
from ..stats import UNDERPOWERED_N, wilson_difference_interval
from ..suite import (
    EvalContext,
    ExampleOutcome,
    MetricDefinition,
    SegmentScore,
    SuiteResult,
    Verdict,
    aggregate,
    fail_closed,
    register,
)

#: The metrics-ledger target: |EN - ES| <= 5 percentage points.
PARITY_GAP_THRESHOLD = 0.05

#: Counts per language slice, as ``[n_passed, n_total]``.
_Counts = dict[str, list[int]]


def _tally(items: Iterable[DatasetItem]) -> _Counts:
    counts: _Counts = defaultdict(lambda: [0, 0])
    for item in items:
        counts[str(item.language)][0] += int(bool(item.is_correct))
        counts[str(item.language)][1] += 1
    return dict(counts)


def _rates(counts: _Counts) -> dict[str, float]:
    return {lang: passed / total for lang, (passed, total) in counts.items() if total}


def _extremes(rates: dict[str, float]) -> tuple[str, str]:
    """The best- and worst-performing language, tie-broken by language code so the report
    is byte-identical across runs."""
    ordered = sorted(rates, key=lambda lang: (rates[lang], lang))
    return ordered[-1], ordered[0]


def _diagnostic_segments(items: Sequence[DatasetItem]) -> list[SegmentScore]:
    """Report-only rows: the same gap, recomputed inside strata common to both languages.

    A stratum present in only one language is dropped rather than reported, because a gap
    needs two slices to exist at all.
    """
    strata: dict[str, list[DatasetItem]] = defaultdict(list)
    for item in items:
        if item.pair_id:
            strata["matched pairs"].append(item)
        if item.expected_behavior:
            strata[f"behavior={item.expected_behavior}"].append(item)

    segments: list[SegmentScore] = []
    for label, members in sorted(strata.items()):
        rates = _rates(_tally(members))
        if len(rates) < 2:
            continue
        best, worst = _extremes(rates)
        gap = rates[best] - rates[worst]
        segments.append(
            SegmentScore(
                label=f"gap · {label} (report-only)",
                score=round(gap, 4),
                n=len(members),
                verdict=Verdict.PASS if gap <= PARITY_GAP_THRESHOLD else Verdict.FAIL,
            )
        )
    return segments


class LanguageParitySuite:
    name = "language-parity"
    metric = MetricDefinition(
        name="en-es-pass-rate-gap",
        definition=(
            "Largest absolute difference between any two language slices' pass rates over "
            "the recorded per-case correctness label, applied identically in every language "
            "(|EN - ES| for this corpus; English anchors are scored as their own slice). "
            "Distinct from the multilingual suite's per-case structural parity. "
            "Lower is better; the interval shown is a Newcombe interval on the gap and the "
            "under-powered flag is keyed to the smallest slice. Segment rows marked "
            "report-only are diagnostics and do not gate."
        ),
        threshold=PARITY_GAP_THRESHOLD,
        higher_is_better=False,
    )

    def run(self, ctx: EvalContext) -> SuiteResult:
        labelled = [
            item for item in ctx.dataset.items if item.language and item.is_correct is not None
        ]
        counts = _tally(labelled)
        rates = _rates(counts)
        if len(rates) < 2:
            return fail_closed(
                suite=self.name,
                metric=self.metric,
                dataset_version=ctx.dataset.version,
                judge=ctx.judge,
                reason=(
                    "a pass-rate gap needs at least two language slices carrying labelled "
                    f"cases; found {sorted(rates) or 'none'}"
                ),
            )

        best, worst = _extremes(rates)
        gap = rates[best] - rates[worst]
        signed_low, signed_high = wilson_difference_interval(
            counts[best][0], counts[best][1], counts[worst][0], counts[worst][1]
        )
        # `gap` is |best - worst| and so is non-negative by construction; the Newcombe
        # interval is signed and may cross zero (the ordering itself is uncertain), which
        # for the absolute gap means a lower bound of exactly 0, not a negative one.
        gap_low, gap_high = max(0.0, signed_low), min(1.0, signed_high)
        smallest_slice = min(total for _, total in counts.values())

        outcomes = [
            ExampleOutcome(
                item_id=item.id,
                passed=bool(item.is_correct),
                score=1.0 if item.is_correct else 0.0,
                detail=(
                    f"language={item.language}, correct={bool(item.is_correct)} — an input "
                    "to that slice's pass rate, not itself a parity failure"
                ),
            )
            for item in labelled
        ]
        slice_segments = [
            SegmentScore(
                label=f"pass rate · {lang}",
                score=round(rates[lang], 4),
                n=counts[lang][1],
                # The best slice defines parity; a slice more than the threshold below it
                # is the one breaking parity, and the row says so by name.
                verdict=Verdict.PASS
                if rates[best] - rates[lang] <= PARITY_GAP_THRESHOLD
                else Verdict.FAIL,
            )
            for lang in sorted(rates)
        ]
        notes = (
            f"gap={gap:.4f} ({best} {rates[best]:.4f} n={counts[best][1]} vs "
            f"{worst} {rates[worst]:.4f} n={counts[worst][1]}); "
            f"95% CI on the gap [{gap_low:.4f}, {gap_high:.4f}] (Newcombe); "
            f"smallest slice n={smallest_slice}. "
            "The language case sets are not matched, so the pooled gap carries a case-mix "
            "component; the report-only segment rows recompute it within common strata."
        )
        return aggregate(
            suite=self.name,
            metric=self.metric,
            outcomes=outcomes,
            dataset_version=ctx.dataset.version,
            judge=ctx.judge,
            score_override=round(gap, 4),
            ci_override=(gap_low, gap_high),
            underpowered_override=smallest_slice < UNDERPOWERED_N,
            notes=notes,
            segments=slice_segments + _diagnostic_segments(labelled),
        )


register(LanguageParitySuite())
